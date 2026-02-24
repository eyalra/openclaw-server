#!/bin/bash
# test-tailscale-serve-working.sh - Test if Tailscale Serve is actually working

set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/load-config.sh"

echo "=========================================="
echo "Test Tailscale Serve (Practical Test)"
echo "=========================================="
echo ""

ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" bash << 'SSH_EOF'
set -e

REMOTE_REPO_PATH="${REMOTE_REPO_PATH:-/home/openclaw/openclaw}"
cd "$REMOTE_REPO_PATH"

export PATH="$HOME/.local/venv/clawctl/bin:$PATH"
CLAWCTL_CMD="$(command -v clawctl || echo '$HOME/.local/venv/clawctl/bin/clawctl')"

echo "1. Checking Tailscale status..."
TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "")
TAILSCALE_HOSTNAME=$(tailscale status --json 2>/dev/null | grep -oE '"DNSName":"[^"]+"' | head -1 | cut -d'"' -f4 || echo "")

if [ -z "$TAILSCALE_IP" ]; then
    echo "   ✗ Tailscale not connected"
    exit 1
fi

echo "   ✓ Tailscale IP: $TAILSCALE_IP"
if [ -n "$TAILSCALE_HOSTNAME" ]; then
    echo "   ✓ Tailscale hostname: $TAILSCALE_HOSTNAME"
fi

echo ""
echo "2. Checking Tailscale Serve status..."
SERVE_STATUS=$(tailscale serve status 2>/dev/null || echo "")
if [ -n "$SERVE_STATUS" ]; then
    echo "$SERVE_STATUS" | head -20
else
    echo "   ⚠ No Tailscale Serve configured"
fi

echo ""
echo "3. Checking container status and gateway tokens..."
"$CLAWCTL_CMD" status --config "$REMOTE_REPO_PATH/clawctl.toml" || true

echo ""
echo "4. Testing HTTPS access to gateway via Tailscale..."
USER_NAMES=$(grep -E '^\s*name\s*=\s*"' "$REMOTE_REPO_PATH/clawctl.toml" | sed 's/.*name\s*=\s*"\(.*\)".*/\1/' || echo "")

for username in $USER_NAMES; do
    GATEWAY_TOKEN=$("$CLAWCTL_CMD" status --config "$REMOTE_REPO_PATH/clawctl.toml" 2>/dev/null | grep -A 5 "^\\s*$username" | grep -oE 'token=[^[:space:]]+' | head -1 | cut -d= -f2 || echo "")
    
    if [ -n "$GATEWAY_TOKEN" ]; then
        echo ""
        echo "   Testing $username..."
        URL="https://$TAILSCALE_IP:443?token=$GATEWAY_TOKEN"
        echo "   URL: $URL"
        
        # Test HTTPS connection
        HTTP_CODE=$(curl -k -s -o /dev/null -w "%{http_code}" --max-time 5 "$URL" || echo "000")
        
        if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "302" ] || [ "$HTTP_CODE" = "401" ]; then
            echo "   ✓ HTTPS connection works! (HTTP $HTTP_CODE)"
            echo "   Tailscale Serve is WORKING!"
        elif [ "$HTTP_CODE" = "000" ]; then
            echo "   ⚠ Connection failed (timeout or connection refused)"
            echo "   Tailscale Serve may not be configured"
        else
            echo "   ⚠ HTTP $HTTP_CODE"
        fi
    fi
done

echo ""
echo "=========================================="
echo "Test Complete"
echo "=========================================="

SSH_EOF

echo ""
echo "=========================================="
echo "Done"
echo "=========================================="
