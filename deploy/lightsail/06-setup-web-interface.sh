#!/bin/bash
# 06-setup-web-interface.sh
# Set up web management interface as a systemd daemon

set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/scripts/load-config.sh"

echo "=========================================="
echo "Setting Up Web Management Interface"
echo "=========================================="
echo ""
echo "This script will:"
echo "  1. Update clawctl to include web command"
echo "  2. Create systemd service for web interface"
echo "  3. Enable and start the service"
echo "  4. Configure firewall (if needed)"
echo ""
echo "Target server: $SSH_USER@$LIGHTSAIL_IP:$SSH_PORT"
echo ""

# Confirm before proceeding
read -p "Continue with web interface setup? (yes/no): " confirm
if [ "$confirm" != "yes" ]; then
    echo "Aborted."
    exit 1
fi

echo ""
echo "Connecting to server..."

# Execute setup on remote server
ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" << REMOTE_SCRIPT
set -e

# Ensure PATH includes standard directories
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:\$PATH"

echo "Step 1: Updating clawctl installation..."
cd $REMOTE_REPO_PATH

# Ensure uv is available
export PATH="\$HOME/.local/bin:\$PATH"
if ! command -v uv >/dev/null 2>&1; then
    echo "  Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="\$HOME/.local/bin:\$PATH"
fi

# Update clawctl in venv
CLAWCTL_VENV="\$HOME/.local/venv/clawctl"
if [ ! -d "\$CLAWCTL_VENV" ]; then
    echo "  Creating virtual environment..."
    uv venv "\$CLAWCTL_VENV"
fi

echo "  Installing/updating clawctl..."
uv pip install -e '.' --python "\$CLAWCTL_VENV/bin/python" || {
    echo "  ⚠ Installation failed, checking for missing dependencies..."
    echo "  Attempting to install web dependencies..."
    uv pip install "fastapi>=0.115.0" "uvicorn[standard]>=0.32.0" --python "\$CLAWCTL_VENV/bin/python" || true
    echo "  Retrying installation..."
    uv pip install -e '.' --python "\$CLAWCTL_VENV/bin/python" || {
        echo "  ⚠ Installation still failed, but continuing..."
    }
}

# Verify web command is available
export PATH="\$CLAWCTL_VENV/bin:\$PATH"
if clawctl web --help >/dev/null 2>&1; then
    echo "  ✓ clawctl web command available"
else
    echo "  ⚠ Warning: clawctl web command not found, but continuing..."
fi

echo ""
echo "Step 2: Creating systemd service file..."

# Determine web port from config if available
WEB_PORT=9000
WEB_HOST="0.0.0.0"
if [ -f "$REMOTE_REPO_PATH/clawctl.toml" ]; then
    # Try to extract port from config (basic parsing)
    # Look for [web] section with port = value
    CONFIG_PORT=\$(grep -A 5 "\[web\]" "$REMOTE_REPO_PATH/clawctl.toml" | grep -E "^\s*port\s*=\s*[0-9]+" | head -1 | grep -oE "[0-9]+" || echo "")
    if [ -n "\$CONFIG_PORT" ]; then
        WEB_PORT=\$CONFIG_PORT
    fi
    # Look for [web] section with host = value
    CONFIG_HOST=\$(grep -A 5 "\[web\]" "$REMOTE_REPO_PATH/clawctl.toml" | grep -E "^\s*host\s*=\s*\"" | head -1 | grep -oE '"[^"]+"' | tr -d '"' || echo "")
    if [ -n "\$CONFIG_HOST" ]; then
        WEB_HOST=\$CONFIG_HOST
    fi
fi

# Create systemd service file
# Use absolute paths to avoid variable expansion issues
CONFIG_FILE_PATH="/home/openclaw/openclaw/clawctl.toml"
WORK_DIR="/home/openclaw/openclaw"
sudo tee /etc/systemd/system/clawctl-web.service > /dev/null << SERVICE_FILE
[Unit]
Description=OpenClaw Web Management Interface
After=network.target docker.service
Wants=network-online.target

[Service]
Type=simple
User=openclaw
Group=openclaw
WorkingDirectory=$WORK_DIR
Environment="PATH=/home/openclaw/.local/venv/clawctl/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="WEB_PORT=$WEB_PORT"
Environment="WEB_HOST=$WEB_HOST"
ExecStart=/home/openclaw/.local/venv/clawctl/bin/python -m clawctl_web.server $CONFIG_FILE_PATH
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=clawctl-web

# Security settings
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/home/openclaw/openclaw
ReadWritePaths=/home/openclaw/.local/venv/clawctl

[Install]
WantedBy=multi-user.target
SERVICE_FILE

echo "  ✓ Systemd service file created"

echo ""
echo "Step 3: Reloading systemd and enabling service..."
sudo systemctl daemon-reload
sudo systemctl enable clawctl-web.service
echo "  ✓ Service enabled"

echo ""
echo "Step 4: Starting web interface service..."
sudo systemctl start clawctl-web.service
sleep 2

# Check status
if sudo systemctl is-active --quiet clawctl-web.service; then
    echo "  ✓ Web interface service is running"
else
    echo "  ⚠ Warning: Service may not be running properly"
    echo "  Check status with: sudo systemctl status clawctl-web"
    echo "  Check logs with: sudo journalctl -u clawctl-web -f"
fi

echo ""
echo "Step 5: Checking firewall configuration..."
if command -v ufw >/dev/null 2>&1 && sudo ufw status | grep -q "Status: active"; then
    echo "  UFW is active, checking port $WEB_PORT..."
    if sudo ufw status | grep -q "$WEB_PORT"; then
        echo "  ✓ Port $WEB_PORT already allowed"
    else
        echo "  Adding UFW rule for port $WEB_PORT..."
        sudo ufw allow $WEB_PORT/tcp comment 'OpenClaw Web Management Interface'
        echo "  ✓ Port $WEB_PORT allowed"
    fi
else
    echo "  UFW not active or not installed, skipping firewall configuration"
fi

echo ""
echo "Step 6: Verifying web interface is accessible..."
sleep 2
if curl -sf http://localhost:$WEB_PORT/ >/dev/null 2>&1; then
    echo "  ✓ Web interface is responding on localhost:$WEB_PORT"
else
    echo "  ⚠ Warning: Web interface not responding on localhost:$WEB_PORT"
    echo "  Service status:"
    sudo systemctl status clawctl-web --no-pager -l | head -10
fi

echo ""
echo "Step 7: Password Configuration"
echo "  ⚠ IMPORTANT: Web interface password is NOT set yet!"
echo "  Username: admin (default)"
echo "  Password: Must be set using: ./scripts/set-web-password.sh"
echo "  Or manually set WEB_ADMIN_PASSWORD environment variable in systemd service"

echo ""
echo "=========================================="
echo "Web Interface Setup Complete"
echo "=========================================="
echo ""
echo "Service Information:"
echo "  Status: sudo systemctl status clawctl-web"
echo "  Logs:   sudo journalctl -u clawctl-web -f"
echo "  Stop:   sudo systemctl stop clawctl-web"
echo "  Start:  sudo systemctl start clawctl-web"
echo "  Restart: sudo systemctl restart clawctl-web"
echo ""
echo "Access URLs:"
echo "  Local:  http://localhost:$WEB_PORT"
echo "  Remote: http://$LIGHTSAIL_IP:$WEB_PORT"
if [ -n "$TAILSCALE_IP" ] && [ "$TAILSCALE_IP" != "" ]; then
    echo "  Tailscale: http://$TAILSCALE_IP:$WEB_PORT"
fi
echo ""
REMOTE_SCRIPT

echo ""
echo "=========================================="
echo "Web interface setup completed on server"
echo "=========================================="
echo ""
echo "The web management interface should now be running as a systemd service."
echo ""
echo "To check status:"
echo "  ssh -p $SSH_PORT -i $SSH_KEY $SSH_USER@$LIGHTSAIL_IP"
echo "  sudo systemctl status clawctl-web"
echo ""
echo "To view logs:"
echo "  sudo journalctl -u clawctl-web -f"
echo ""
