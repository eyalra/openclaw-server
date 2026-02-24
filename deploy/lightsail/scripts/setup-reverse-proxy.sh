#!/bin/bash
# setup-reverse-proxy.sh - Set up nginx reverse proxy for HTTPS gateway access

set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/load-config.sh"

echo "=========================================="
echo "Setup Reverse Proxy for HTTPS Gateways"
echo "=========================================="
echo ""
echo "This will:"
echo "  1. Install and configure nginx as a reverse proxy"
echo "  2. Configure Tailscale Serve to proxy HTTPS to nginx"
echo "  3. Route admin UI and gateways through HTTPS"
echo ""

ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" bash << 'SSH_EOF'
set -e

REMOTE_REPO_PATH="${REMOTE_REPO_PATH:-/home/openclaw/openclaw}"
cd "$REMOTE_REPO_PATH"

export PATH="$HOME/.local/venv/clawctl/bin:$PATH"
CLAWCTL_CMD="$(command -v clawctl || echo '$HOME/.local/venv/clawctl/bin/clawctl')"

echo "1. Installing nginx..."
if ! command -v nginx >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y nginx
else
    echo "   ✓ nginx already installed"
fi

echo ""
echo "2. Getting gateway ports..."
USER_NAMES=$(grep -E '^\s*name\s*=\s*"' "$REMOTE_REPO_PATH/clawctl.toml" | sed 's/.*name\s*=\s*"\(.*\)".*/\1/' || echo "")

declare -A GATEWAY_PORTS
for username in $USER_NAMES; do
    STATUS_OUTPUT=$("$CLAWCTL_CMD" status --config "$REMOTE_REPO_PATH/clawctl.toml" 2>/dev/null || echo "")
    PORT=$(echo "$STATUS_OUTPUT" | grep -A 5 "^\\s*$username" | grep -oE '[0-9]+' | head -1 || echo "")
    if [ -n "$PORT" ] && [ "$PORT" != "-" ]; then
        GATEWAY_PORTS[$username]=$PORT
        echo "   $username: port $PORT"
    fi
done

WEB_PORT="9000"
if systemctl is-active --quiet clawctl-web; then
    WEB_PORT=$(systemctl show clawctl-web --property=ExecStart --value | grep -oE 'port=[0-9]+' | cut -d= -f2 || echo "9000")
fi
echo "   Web UI: port $WEB_PORT"

echo ""
echo "3. Creating nginx configuration..."
NGINX_CONFIG="/etc/nginx/sites-available/openclaw-proxy"

# Start server block
sudo tee "$NGINX_CONFIG" > /dev/null << SERVER_START
server {
    listen 127.0.0.1:8080;
    server_name _;
    
    # Admin UI - root path
    location / {
        proxy_pass http://127.0.0.1:${WEB_PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        
        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }
    
SERVER_START

# Add gateway routes
for username in "${!GATEWAY_PORTS[@]}"; do
    PORT=${GATEWAY_PORTS[$username]}
    sudo tee -a "$NGINX_CONFIG" > /dev/null << GATEWAY_BLOCK

    # Gateway: $username
    # With basePath configured, gateway serves at /gateway/$username/
    # Pass the full path including prefix to the gateway
    location ~ ^/gateway/$username(/.*)?$ {
        proxy_pass http://127.0.0.1:${PORT}\$request_uri;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Host \$host;
        
        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
        proxy_buffering off;
    }
GATEWAY_BLOCK
done

# Close server block
sudo tee -a "$NGINX_CONFIG" > /dev/null << 'SERVER_CLOSE'
}
SERVER_CLOSE

echo ""
echo "4. Enabling nginx configuration..."
sudo ln -sf /etc/nginx/sites-available/openclaw-proxy /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true
sudo nginx -t
sudo systemctl restart nginx
sudo systemctl enable nginx

echo ""
echo "5. Configuring Tailscale Serve..."
sudo tailscale serve reset 2>/dev/null || true
sleep 1

# Configure Tailscale Serve to proxy HTTPS to nginx
sudo tailscale serve --bg --https 443 http://127.0.0.1:8080 2>&1 | grep -v "Serve started" || true

sleep 2

echo ""
echo "6. Verifying configuration..."
echo "   Tailscale Serve status:"
sudo tailscale serve status 2>&1 | head -5 || echo "   (Could not get status)"

echo ""
echo "   nginx status:"
sudo systemctl status nginx --no-pager | head -5 || echo "   (Could not get status)"

TAILSCALE_HOSTNAME=$(tailscale status --json 2>/dev/null | grep -oE '"DNSName":"[^"]+"' | head -1 | cut -d'"' -f4 | sed 's/\.$//' || echo "")

echo ""
echo "=========================================="
echo "Configuration Complete"
echo "=========================================="
echo ""
echo "Admin UI: https://${TAILSCALE_HOSTNAME}/"
echo ""
echo "Gateway URLs:"
for username in "${!GATEWAY_PORTS[@]}"; do
    PORT=${GATEWAY_PORTS[$username]}
    echo "  $username: https://${TAILSCALE_HOSTNAME}/gateway/$username?token=<token>"
done
echo ""
echo "Note: Update the dashboard to generate these HTTPS URLs automatically."

SSH_EOF

echo ""
echo "Setup complete!"
