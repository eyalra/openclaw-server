#!/bin/bash
# remote/setup.sh — Server-side provisioning script for OpenClaw on Lightsail.
#
# Called by: clawctl host setup [--step <step>]
#   The Python CLI SSHes in and runs: sudo /path/to/setup.sh <step>
#
# Idempotent: every step is safe to re-run at any time.
#
# Steps (run individually or all at once):
#   harden  — Create 'openclaw' user, SSH on port 2222, disable root/password login, UFW firewall
#   deps    — 2GB swap, Docker, Tailscale (connect with auth key), Python venv support
#   docker  — Create data dirs, install clawctl in venv, build OpenClaw Docker image
#   users   — For each user in clawctl.toml: fix secret permissions, create container,
#             set Discord tokens, inject OpenRouter API keys
#   web     — Install clawctl-web systemd service, nginx reverse proxy for gateway
#             containers, Tailscale Serve for HTTPS, bcrypt web admin password
#   all     — Run all steps in order (default)
#
# Prerequisites:
#   - Code and secrets already deployed via: clawctl host deploy [--initial]
#   - Secrets layout: data/secrets/<user>/{openrouter_api_key,discord_token,...}
#   - Tailscale auth key:  deploy/lightsail/secrets/tailscale_auth_key
#   - Web admin password:  data/secrets/web_admin/password_plaintext
#
# First-time setup:
#   clawctl host deploy --initial   # as ubuntu@22
#   clawctl host setup --initial    # runs harden, then reboots, SSH resumes on 2222
#
# Subsequent updates:
#   clawctl host deploy             # as openclaw@2222
#   clawctl host setup              # or: clawctl host setup --step users

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(dirname "$SCRIPT_DIR")"
REPO_DIR="$(cd "$DEPLOY_DIR/../.." && pwd)"
HOME_DIR="/home/openclaw"
DATA_DIR="$HOME_DIR/data"
VENV_DIR="$HOME_DIR/.local/venv/clawctl"

STEP="${1:-all}"

log() { echo "==> $*"; }

# ---------------------------------------------------------------------------
# harden — Create openclaw user, move SSH to port 2222, harden sshd, enable UFW
# ---------------------------------------------------------------------------
step_harden() {
    log "Hardening server..."

    # Create openclaw user if needed
    if ! id "openclaw" &>/dev/null; then
        sudo adduser --disabled-password --gecos "" openclaw
        sudo usermod -aG sudo openclaw
        echo "openclaw ALL=(ALL) NOPASSWD: ALL" | sudo tee /etc/sudoers.d/openclaw-nopasswd > /dev/null
        sudo chmod 440 /etc/sudoers.d/openclaw-nopasswd
        sudo mkdir -p /home/openclaw/.ssh
        sudo cp /home/ubuntu/.ssh/authorized_keys /home/openclaw/.ssh/ 2>/dev/null || true
        sudo chown -R openclaw:openclaw /home/openclaw/.ssh
        sudo chmod 700 /home/openclaw/.ssh
        sudo chmod 600 /home/openclaw/.ssh/authorized_keys 2>/dev/null || true
        log "User 'openclaw' created"
    else
        log "User 'openclaw' already exists"
    fi

    # SSH hardening: port 2222, disable root/password auth.
    #
    # Ubuntu 24.04 uses ssh.socket for port binding.
    # Port is set ONLY via ssh.socket override — NOT in sshd_config.
    # sshd_config only holds security settings (PermitRootLogin, etc.).
    # A reboot is required after changes (restarting mid-session kills the connection).

    NEEDS_REBOOT=0

    # 1. sshd_config: security hardening only (no Port directive!)
    if ! grep -q "^PermitRootLogin no" /etc/ssh/sshd_config; then
        sudo cp /etc/ssh/sshd_config /etc/ssh/sshd_config.backup
        # Remove any existing Port/security directives to avoid duplicates
        sudo sed -i '/^#*Port /d; /^#*PermitRootLogin /d; /^#*PasswordAuthentication /d; /^#*PubkeyAuthentication /d' /etc/ssh/sshd_config
        # Append security settings (no Port — that's handled by ssh.socket)
        sudo tee -a /etc/ssh/sshd_config > /dev/null << 'EOF'

# Hardening (managed by setup.sh)
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
EOF
        NEEDS_REBOOT=1
        log "sshd_config hardened (security only, no Port directive)"
    else
        log "sshd_config already hardened"
    fi

    # 2. ssh.socket override: listen on 2222 instead of default 22
    SOCKET_OVERRIDE="/etc/systemd/system/ssh.socket.d/override.conf"
    if [ ! -f "$SOCKET_OVERRIDE" ]; then
        sudo mkdir -p /etc/systemd/system/ssh.socket.d
        sudo tee "$SOCKET_OVERRIDE" > /dev/null << 'EOF'
[Socket]
ListenStream=
ListenStream=0.0.0.0:2222
ListenStream=[::]:2222
EOF
        NEEDS_REBOOT=1
        log "ssh.socket override: port 2222"
    else
        log "ssh.socket override already exists"
    fi

    # 3. Validate and reload (but do NOT restart — reboot handles it)
    if sudo sshd -t; then
        sudo systemctl daemon-reload
        log "Config valid, daemon reloaded (reboot applies port change)"
    else
        sudo cp /etc/ssh/sshd_config.backup /etc/ssh/sshd_config 2>/dev/null || true
        sudo rm -f "$SOCKET_OVERRIDE"
        sudo systemctl daemon-reload
        log "ERROR: sshd config invalid, reverted"
        exit 1
    fi

    # 4. If already on 2222 (idempotent re-run), verify
    if [ "$NEEDS_REBOOT" = "0" ]; then
        if sudo ss -tlnp | grep -q ':2222'; then
            log "SSH already listening on port 2222"
        fi
    fi

    # UFW
    if ! sudo ufw status | grep -q "Status: active"; then
        sudo ufw --force reset
        sudo ufw default deny incoming
        sudo ufw default allow outgoing
        sudo ufw allow 22/tcp
        sudo ufw allow 2222/tcp
        sudo ufw allow 80/tcp
        sudo ufw allow from 100.64.0.0/10
        echo "y" | sudo ufw enable
        log "UFW configured"
    else
        # Ensure our ports are open
        sudo ufw allow 2222/tcp 2>/dev/null || true
        sudo ufw allow 80/tcp 2>/dev/null || true
        sudo ufw allow from 100.64.0.0/10 2>/dev/null || true
        log "UFW already active, rules ensured"
    fi
}

# ---------------------------------------------------------------------------
# deps — 2GB swap, Docker engine, Tailscale (auto-connect), Python venv tools
# ---------------------------------------------------------------------------
step_deps() {
    log "Installing dependencies..."

    # Swap (2GB) — essential for the small_3_0 instance running two containers
    if ! swapon --show | grep -q '/swapfile'; then
        sudo fallocate -l 2G /swapfile
        sudo chmod 600 /swapfile
        sudo mkswap /swapfile
        sudo swapon /swapfile
        grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
        log "Swap enabled (2GB)"
    else
        log "Swap already active"
    fi

    # Docker
    if ! command -v docker >/dev/null 2>&1; then
        sudo apt-get update -qq
        sudo apt-get install -y -qq apt-transport-https ca-certificates curl software-properties-common
        sudo install -m 0755 -d /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
            | sudo gpg --batch --yes --dearmor -o /etc/apt/keyrings/docker.gpg
        sudo chmod a+r /etc/apt/keyrings/docker.gpg
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
            $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
            | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
        sudo apt-get update -qq
        sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
        sudo usermod -aG docker openclaw
        log "Docker installed"
    else
        log "Docker already installed: $(docker --version)"
    fi

    # Tailscale
    if ! command -v tailscale >/dev/null 2>&1; then
        curl -fsSL https://tailscale.com/install.sh | sh
        log "Tailscale installed"
    else
        log "Tailscale already installed"
    fi

    # Tailscale connect
    TS_STATUS=$(sudo tailscale status 2>&1 | head -1 || true)
    if echo "$TS_STATUS" | grep -qi "logged out\|NeedsLogin\|stopped"; then
        TS_KEY_FILE="$DEPLOY_DIR/secrets/tailscale_auth_key"
        if [ -f "$TS_KEY_FILE" ]; then
            TS_KEY=$(cat "$TS_KEY_FILE" | tr -d '[:space:]')
            sudo tailscale up --authkey "$TS_KEY" --accept-routes
            log "Tailscale connected: $(tailscale ip -4)"
        else
            log "WARNING: Tailscale not connected and no auth key at secrets/tailscale_auth_key"
        fi
    else
        log "Tailscale already connected: $(tailscale ip -4 2>/dev/null || echo '?')"
    fi

    # Python venv support + utilities
    sudo apt-get install -y -qq git curl wget jq unzip python3-venv python3-pip
}

# ---------------------------------------------------------------------------
# docker — Create data directories, install clawctl venv, build Docker image
# ---------------------------------------------------------------------------
step_docker() {
    log "Setting up Docker image and clawctl..."
    export PATH="$HOME/.local/bin:$VENV_DIR/bin:$PATH"

    # Directory structure
    mkdir -p "$DATA_DIR"/{secrets,users,shared,knowledge/{transcripts,newsletters,emails}}
    mkdir -p "$HOME_DIR/build/logs"

    # clawctl virtualenv (system Python, owned by openclaw)
    cd "$REPO_DIR"
    if [ ! -f "$VENV_DIR/bin/python" ]; then
        sudo -u openclaw python3 -m venv "$VENV_DIR"
    fi
    sudo -u openclaw "$VENV_DIR/bin/pip" install -e "." -q
    log "clawctl installed"

    # Docker image
    if ! docker images --format '{{.Repository}}' | grep -q "^openclaw-instance$"; then
        log "Building Docker image (this takes a few minutes)..."
        docker build -t openclaw-instance:latest --build-arg OPENCLAW_VERSION=latest docker/
        log "Docker image built"
    else
        log "Docker image already exists"
    fi
}

# ---------------------------------------------------------------------------
# users — Fix secret permissions, provision containers, inject Discord + OpenRouter keys
# ---------------------------------------------------------------------------
step_users() {
    log "Configuring users..."
    export PATH="$HOME/.local/bin:$VENV_DIR/bin:$PATH"
    cd "$REPO_DIR"

    SECRETS_DIR="$REPO_DIR/data/secrets"

    USER_NAMES=$(grep -E '^\s*name\s*=' clawctl.toml | sed 's/.*"\(.*\)".*/\1/' || true)
    if [ -z "$USER_NAMES" ]; then
        log "No users in clawctl.toml"
        return
    fi

    for username in $USER_NAMES; do
        # Secret files must be readable by the container's node user (UID 1000)
        if [ -d "$SECRETS_DIR/$username" ]; then
            sudo chown -R 1000:1000 "$SECRETS_DIR/$username"
            sudo chmod 755 "$SECRETS_DIR/$username"
            sudo chmod 644 "$SECRETS_DIR/$username"/* 2>/dev/null || true
        fi

        if docker ps -a --format '{{.Names}}' | grep -q "^openclaw-${username}$"; then
            log "$username: container exists — skipping"
        else
            log "$username: provisioning..."
            sudo chown -R openclaw:openclaw "$REPO_DIR/data" 2>/dev/null || true
            # Re-fix secrets after the chown above
            if [ -d "$SECRETS_DIR/$username" ]; then
                sudo chown -R 1000:1000 "$SECRETS_DIR/$username"
            fi

            clawctl user add "$username" --config clawctl.toml --non-interactive
            log "$username: container created"
        fi

        # Fix permissions for container (UID 1000)
        sudo chown -R 1000:1000 "$REPO_DIR/data/users/$username/openclaw" 2>/dev/null || true
        sudo chmod -R 775 "$REPO_DIR/data/users/$username/openclaw" 2>/dev/null || true
    done

    # Discord tokens
    for username in $USER_NAMES; do
        TOKEN_FILE="$SECRETS_DIR/$username/discord_token"
        if [ -f "$TOKEN_FILE" ] && [ -s "$TOKEN_FILE" ]; then
            log "$username: setting Discord token..."
            OC_DIR="$REPO_DIR/data/users/$username/openclaw"
            sudo chown -R openclaw:openclaw "$OC_DIR" 2>/dev/null || true
            clawctl user set-discord --token "$(cat "$TOKEN_FILE")" --config clawctl.toml "$username" 2>&1 || \
                log "WARNING: Discord token failed for $username"
            sudo chown -R 1000:1000 "$OC_DIR" 2>/dev/null || true
        fi
    done

    # OpenRouter keys — inject into running containers
    for username in $USER_NAMES; do
        KEY_FILE="$SECRETS_DIR/$username/openrouter_api_key"
        if [ -f "$KEY_FILE" ] && [ -s "$KEY_FILE" ]; then
            KEY=$(cat "$KEY_FILE" | tr -d '[:space:]')
            CONTAINER="openclaw-$username"
            if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
                log "$username: injecting OpenRouter key..."
                docker exec -i "$CONTAINER" python3 - "$KEY" << 'PYEOF'
import json, pathlib, sys
key = sys.argv[1].strip()
path = pathlib.Path("/home/node/.openclaw/agents/main/agent/auth-profiles.json")
path.parent.mkdir(parents=True, exist_ok=True)
try:
    data = json.loads(path.read_text())
except Exception:
    data = {}
data.setdefault("profiles", {})["openrouter:manual"] = {
    "type": "token", "provider": "openrouter", "token": key
}
path.write_text(json.dumps(data, indent=2) + "\n")
PYEOF
                log "$username: OpenRouter key injected"
            fi
        fi
    done

    log "Users done"
}

# ---------------------------------------------------------------------------
# web — clawctl-web systemd service, nginx reverse proxy, Tailscale Serve HTTPS
# ---------------------------------------------------------------------------
step_web() {
    log "Setting up web interface..."
    export PATH="$VENV_DIR/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"

    # Reinstall clawctl (picks up latest)
    cd "$REPO_DIR"
    sudo -u openclaw "$VENV_DIR/bin/pip" install -e "." -q 2>&1 | tail -3

    CONFIG_PATH="$REPO_DIR/clawctl.toml"

    # Web admin password: read plaintext from secrets, generate bcrypt hash
    PW_PLAINTEXT="$REPO_DIR/data/secrets/web_admin/password_plaintext"
    PW_HASH_FILE="$REPO_DIR/data/secrets/web_admin/password"
    WEB_ADMIN_PW_ENV=""
    if [ -f "$PW_PLAINTEXT" ]; then
        WEB_ADMIN_PW=$(cat "$PW_PLAINTEXT" | tr -d '[:space:]')
        if [ -n "$WEB_ADMIN_PW" ]; then
            # Generate bcrypt hash and write it directly
            "$VENV_DIR/bin/python" -c "
import bcrypt, pathlib, sys
pw = sys.argv[1].encode('utf-8')
hashed = bcrypt.hashpw(pw, bcrypt.gensalt())
p = pathlib.Path('$PW_HASH_FILE')
p.parent.mkdir(parents=True, exist_ok=True)
p.write_bytes(hashed)
p.chmod(0o600)
" "$WEB_ADMIN_PW"
            sudo chown openclaw:openclaw "$PW_HASH_FILE"
            log "Web admin password hash created"
        fi
    else
        log "WARNING: No web_admin_password secret found — login will fail"
        log "  Create: deploy/lightsail/secrets/web_admin_password"
    fi

    sudo tee /etc/systemd/system/clawctl-web.service > /dev/null << EOF
[Unit]
Description=OpenClaw Web Management Interface
After=network.target docker.service

[Service]
Type=simple
User=openclaw
Group=openclaw
WorkingDirectory=$REPO_DIR
Environment="PATH=$VENV_DIR/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ExecStart=$VENV_DIR/bin/python -m clawctl_web.server $CONFIG_PATH
Restart=on-failure
RestartSec=5
ReadWritePaths=$DATA_DIR
ReadWritePaths=$VENV_DIR

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    sudo systemctl enable clawctl-web
    sudo systemctl restart clawctl-web
    sleep 2

    if sudo systemctl is-active --quiet clawctl-web; then
        log "Web interface running"
    else
        log "WARNING: Web interface failed to start"
        sudo journalctl -u clawctl-web -n 10 --no-pager
    fi

    sudo ufw allow 9000/tcp 2>/dev/null || true

    # Reverse proxy (nginx) for gateway containers
    if ! command -v nginx >/dev/null 2>&1; then
        sudo apt-get install -y -qq nginx
        log "nginx installed"
    fi

    # Build nginx config from user ports in clawctl.toml
    NGINX_GATEWAYS=""
    for username in $(grep -E '^\s*name\s*=' "$CONFIG_PATH" | sed 's/.*"\(.*\)".*/\1/'); do
        # Extract port for this user (look for port = NNNN after the user's name line)
        USER_PORT=$(awk "/name *= *\"$username\"/{found=1} found && /^port *=/{print \$3; exit}" "$CONFIG_PATH")
        if [ -n "$USER_PORT" ]; then
            NGINX_GATEWAYS="$NGINX_GATEWAYS
    location /gateway/$username {
        proxy_pass http://127.0.0.1:$USER_PORT;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \"upgrade\";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 86400;
    }
"
            log "nginx: /gateway/$username/ -> 127.0.0.1:$USER_PORT"
        fi
    done

    sudo tee /etc/nginx/sites-available/openclaw > /dev/null << NGINXEOF
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
$NGINX_GATEWAYS
    location / {
        return 404;
    }
}
NGINXEOF

    sudo ln -sf /etc/nginx/sites-available/openclaw /etc/nginx/sites-enabled/openclaw
    sudo rm -f /etc/nginx/sites-enabled/default
    if sudo nginx -t 2>&1; then
        sudo systemctl reload nginx
        log "nginx configured and running"
    else
        log "ERROR: nginx config invalid"
    fi

    # Tailscale Serve: HTTPS -> nginx (port 80)
    sudo tailscale serve reset 2>/dev/null || true
    sudo tailscale serve --bg 80 2>&1 | tail -5
    log "Tailscale Serve: HTTPS -> nginx:80"
}

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
case "$STEP" in
    harden)  step_harden ;;
    deps)    step_deps ;;
    docker)  step_docker ;;
    users)   step_users ;;
    web)     step_web ;;
    all)
        step_harden
        step_deps
        step_docker
        step_users
        step_web
        ;;
    *)
        echo "Usage: $0 [harden|deps|docker|users|web|all]"
        exit 1
        ;;
esac

log "Done: $STEP"
