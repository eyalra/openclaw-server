#!/bin/bash
# enable-web-https.sh - Enable HTTPS for web management interface via Tailscale Serve

set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/load-config.sh"

echo "=========================================="
echo "Enable HTTPS for Web Management Interface"
echo "=========================================="
echo ""
echo "This will configure Tailscale Serve to expose the web interface over HTTPS."
echo ""

ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" bash << 'SSH_EOF'
set -e

echo "1. Checking Tailscale status..."
if ! command -v tailscale >/dev/null 2>&1; then
    echo "   ✗ Tailscale not installed!"
    exit 1
fi

TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "")
TAILSCALE_HOSTNAME=$(tailscale status --json 2>/dev/null | grep -oE '"DNSName":"[^"]+"' | head -1 | cut -d'"' -f4 || echo "")

if [ -z "$TAILSCALE_IP" ]; then
    echo "   ✗ Tailscale not connected"
    exit 1
fi

echo "   ✓ Tailscale is running"
echo "   Tailscale IP: $TAILSCALE_IP"
if [ -n "$TAILSCALE_HOSTNAME" ]; then
    echo "   Tailscale hostname: $TAILSCALE_HOSTNAME"
fi

echo ""
echo "2. Checking web service status..."
if systemctl is-active --quiet clawctl-web; then
    echo "   ✓ Web service is running"
    WEB_PORT=$(systemctl show clawctl-web --property=ExecStart --value | grep -oE 'port=[0-9]+' | cut -d= -f2 || echo "9000")
    if [ -z "$WEB_PORT" ]; then
        WEB_PORT="9000"
    fi
    echo "   Web service port: $WEB_PORT"
else
    echo "   ⚠ Web service is not running"
    WEB_PORT="9000"
fi

echo ""
echo "3. Stopping any existing Tailscale Serve processes..."
sudo pkill -f 'tailscale serve' 2>/dev/null || true
sudo tailscale serve reset 2>/dev/null || true
sleep 1

echo ""
echo "4. Configuring Tailscale Serve for web interface..."
# Tailscale Serve exposes localhost:9000 over HTTPS on port 443
# Format: tailscale serve --bg --https 443 http://127.0.0.1:9000

SERVE_OUTPUT=$(sudo tailscale serve --bg --https 443 http://127.0.0.1:${WEB_PORT} 2>&1)
SERVE_EXIT=$?

if [ $SERVE_EXIT -ne 0 ]; then
    if echo "$SERVE_OUTPUT" | grep -q "Serve is not enabled"; then
        echo "   ⚠ Tailscale Serve is not enabled on your tailnet"
        echo ""
        echo "   To enable Tailscale Serve:"
        echo "   1. Visit the URL shown below"
        echo "   2. Enable Serve in your Tailscale admin console"
        echo "   3. Run this script again"
        echo ""
        echo "$SERVE_OUTPUT" | grep -A 1 "To enable"
        echo ""
        echo "   Alternatively, you can enable it via:"
        echo "   tailscale set --serve-config=/path/to/config.json"
        exit 1
    elif echo "$SERVE_OUTPUT" | grep -q "foreground listener already exists"; then
        echo "   ⚠ Port 443 is already in use by a foreground process"
        echo "   Stopping existing process and retrying..."
        sudo pkill -f 'tailscale serve' || true
        sleep 2
        SERVE_OUTPUT=$(sudo tailscale serve --bg --https 443 http://127.0.0.1:${WEB_PORT} 2>&1)
        SERVE_EXIT=$?
        if [ $SERVE_EXIT -ne 0 ]; then
            echo "   ✗ Failed to configure Tailscale Serve:"
            echo "$SERVE_OUTPUT"
            exit 1
        fi
    else
        echo "   ✗ Failed to configure Tailscale Serve:"
        echo "$SERVE_OUTPUT"
        exit 1
    fi
fi

echo "   ✓ Tailscale Serve configured"

echo ""
echo "5. Verifying Tailscale Serve configuration..."
SERVE_STATUS=$(sudo tailscale serve status 2>&1 || echo "")
if [ -n "$SERVE_STATUS" ]; then
    echo "$SERVE_STATUS"
else
    echo "   ⚠ Could not get serve status"
fi

echo ""
echo "6. Updating web service to bind to localhost..."
# The web service should bind to 127.0.0.1 so Tailscale Serve can handle HTTPS
# Check current systemd service configuration
SERVICE_FILE="/etc/systemd/system/clawctl-web.service"
if [ -f "$SERVICE_FILE" ]; then
    # Check if WEB_HOST is already set
    if grep -q "WEB_HOST" "$SERVICE_FILE"; then
        echo "   WEB_HOST already configured in service file"
        # Update it to 127.0.0.1
        sudo sed -i 's/WEB_HOST=.*/WEB_HOST=127.0.0.1/' "$SERVICE_FILE" || {
            echo "   ⚠ Could not update WEB_HOST (may need manual edit)"
        }
    else
        echo "   Adding WEB_HOST=127.0.0.1 to service file..."
        # Add Environment line before ExecStart
        sudo sed -i '/^ExecStart=/i Environment="WEB_HOST=127.0.0.1"' "$SERVICE_FILE" || {
            echo "   ⚠ Could not add WEB_HOST (may need manual edit)"
        }
    fi
    
    echo "   Reloading systemd..."
    sudo systemctl daemon-reload
    
    echo "   Restarting web service..."
    sudo systemctl restart clawctl-web
    
    sleep 2
    if systemctl is-active --quiet clawctl-web; then
        echo "   ✓ Web service restarted successfully"
    else
        echo "   ⚠ Web service may not have started correctly"
        systemctl status clawctl-web --no-pager | head -10
    fi
else
    echo "   ⚠ Service file not found: $SERVICE_FILE"
fi

echo ""
echo "=========================================="
echo "✓ HTTPS Configuration Complete"
echo "=========================================="
echo ""
echo "Web Management Interface URLs:"
if [ -n "$TAILSCALE_HOSTNAME" ]; then
    echo "  HTTPS: https://$TAILSCALE_HOSTNAME/"
fi
echo "  HTTPS: https://$TAILSCALE_IP/"
echo ""
echo "Note: The web interface is now only accessible via Tailscale HTTPS."
echo "      HTTP access on port 9000 is disabled (bound to localhost)."

SSH_EOF

echo ""
echo "=========================================="
echo "Done"
echo "=========================================="
