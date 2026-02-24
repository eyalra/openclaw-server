#!/bin/bash
# fix-web-interface.sh - Fix web interface by installing dependencies and updating service

set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/load-config.sh"

echo "=========================================="
echo "Fixing Web Interface"
echo "=========================================="
echo ""

ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" << 'REMOTE_SCRIPT'
set -e

echo "Step 1: Stopping service..."
sudo systemctl stop clawctl-web.service || true

echo ""
echo "Step 2: Installing missing dependencies..."
export PATH="$HOME/.local/bin:$PATH"
CLAWCTL_VENV="$HOME/.local/venv/clawctl"

if [ ! -d "$CLAWCTL_VENV" ]; then
    echo "  ⚠ Virtual environment not found, creating..."
    uv venv "$CLAWCTL_VENV"
fi

echo "  Installing fastapi, uvicorn, and bcrypt..."
uv pip install "fastapi>=0.115.0" "uvicorn[standard]>=0.32.0" "bcrypt>=4.0.0" --python "$CLAWCTL_VENV/bin/python" || {
    echo "  ⚠ Failed to install dependencies"
    exit 1
}

echo "  ✓ Dependencies installed"

echo ""
echo "Step 3: Updating clawctl installation..."
cd $REMOTE_REPO_PATH
uv pip install -e '.' --python "$CLAWCTL_VENV/bin/python" || {
    echo "  ⚠ Installation update failed, but continuing..."
}

echo ""
echo "Step 4: Determining web port and host..."
WEB_PORT=9000
WEB_HOST="0.0.0.0"

if [ -f "$REMOTE_REPO_PATH/clawctl.toml" ]; then
    # Try to extract port from config
    CONFIG_PORT=$(grep -E "^\s*port\s*=\s*[0-9]+" "$REMOTE_REPO_PATH/clawctl.toml" | head -1 | grep -oE "[0-9]+" || echo "")
    if [ -n "$CONFIG_PORT" ]; then
        WEB_PORT=$CONFIG_PORT
        echo "  Found port in config: $WEB_PORT"
    fi
    
    # Try to extract host from config
    CONFIG_HOST=$(grep -E "^\s*host\s*=\s*\"" "$REMOTE_REPO_PATH/clawctl.toml" | head -1 | grep -oE '"[^"]+"' | tr -d '"' || echo "")
    if [ -n "$CONFIG_HOST" ]; then
        WEB_HOST=$CONFIG_HOST
        echo "  Found host in config: $WEB_HOST"
    fi
fi

echo "  Using WEB_PORT=$WEB_PORT"
echo "  Using WEB_HOST=$WEB_HOST"

echo ""
echo "Step 5: Updating systemd service file..."
# Use absolute paths - REMOTE_REPO_PATH should be /home/openclaw/openclaw
CONFIG_FILE_PATH="/home/openclaw/openclaw/clawctl.toml"
WORK_DIR="/home/openclaw/openclaw"
echo "  Config file path: $CONFIG_FILE_PATH"
echo "  Working directory: $WORK_DIR"
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

echo "  ✓ Service file updated"

echo ""
echo "Step 6: Reloading systemd..."
sudo systemctl daemon-reload

echo ""
echo "Step 7: Starting service..."
sudo systemctl start clawctl-web.service
sleep 3

echo ""
echo "Step 8: Checking service status..."
if sudo systemctl is-active --quiet clawctl-web.service; then
    echo "  ✓ Service is running"
    echo ""
    echo "  Service status:"
    sudo systemctl status clawctl-web --no-pager -l | head -15
else
    echo "  ⚠ Service is not running"
    echo ""
    echo "  Service status:"
    sudo systemctl status clawctl-web --no-pager -l | head -20
    echo ""
    echo "  Recent logs:"
    sudo journalctl -u clawctl-web -n 20 --no-pager
    exit 1
fi

echo ""
echo "Step 9: Verifying web interface..."
sleep 2
if curl -sf http://localhost:$WEB_PORT/ >/dev/null 2>&1; then
    echo "  ✓ Web interface is responding on localhost:$WEB_PORT"
else
    echo "  ⚠ Web interface not responding yet (may need a moment to start)"
    echo "  Check logs: sudo journalctl -u clawctl-web -f"
fi

echo ""
echo "Step 10: Checking firewall..."
if command -v ufw >/dev/null 2>&1 && sudo ufw status | grep -q "Status: active"; then
    if sudo ufw status | grep -q "$WEB_PORT"; then
        echo "  ✓ Port $WEB_PORT already allowed"
    else
        echo "  Adding UFW rule for port $WEB_PORT..."
        sudo ufw allow $WEB_PORT/tcp comment 'OpenClaw Web Management Interface'
        echo "  ✓ Port $WEB_PORT allowed"
    fi
fi

echo ""
echo "=========================================="
echo "Fix Complete"
echo "=========================================="
echo ""
echo "Access URLs:"
echo "  Local:  http://localhost:$WEB_PORT"
echo "  Remote: http://$(hostname -I | awk '{print $1}'):$WEB_PORT"
echo ""
echo "To check logs: sudo journalctl -u clawctl-web -f"
REMOTE_SCRIPT

echo ""
echo "✓ Web interface fix completed"
