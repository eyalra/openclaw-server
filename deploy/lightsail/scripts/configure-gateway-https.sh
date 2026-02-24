#!/bin/bash
# configure-gateway-https.sh - Configure Tailscale Serve for gateway HTTPS access

set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/load-config.sh"

echo "=========================================="
echo "Configure Gateway HTTPS Access"
echo "=========================================="
echo ""
echo "This configures Tailscale Serve to provide HTTPS for gateway containers."
echo "Gateways will be accessible via path-based routing."
echo ""

ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" bash << 'SSH_EOF'
set -e

REMOTE_REPO_PATH="${REMOTE_REPO_PATH:-/home/openclaw/openclaw}"
cd "$REMOTE_REPO_PATH"

export PATH="$HOME/.local/venv/clawctl/bin:$PATH"
CLAWCTL_CMD="$(command -v clawctl || echo '$HOME/.local/venv/clawctl/bin/clawctl')"

echo "1. Getting gateway container ports..."
USER_NAMES=$(grep -E '^\s*name\s*=\s*"' "$REMOTE_REPO_PATH/clawctl.toml" | sed 's/.*name\s*=\s*"\(.*\)".*/\1/' || echo "")

declare -A GATEWAY_PORTS
declare -A GATEWAY_TOKENS

for username in $USER_NAMES; do
    STATUS_OUTPUT=$("$CLAWCTL_CMD" status --config "$REMOTE_REPO_PATH/clawctl.toml" 2>/dev/null || echo "")
    PORT=$(echo "$STATUS_OUTPUT" | grep -A 5 "^\\s*$username" | grep -oE '[0-9]+' | head -1 || echo "")
    TOKEN=$(echo "$STATUS_OUTPUT" | grep -A 5 "^\\s*$username" | grep -oE 'token=[^[:space:]]+' | head -1 | cut -d= -f2 || echo "")
    
    if [ -n "$PORT" ] && [ "$PORT" != "-" ]; then
        GATEWAY_PORTS[$username]=$PORT
        GATEWAY_TOKENS[$username]=$TOKEN
        echo "   $username: port $PORT"
    fi
done

echo ""
echo "2. Configuring Tailscale Serve with path-based routing..."

# Reset existing config
sudo tailscale serve reset 2>/dev/null || true
sleep 1

# Configure web interface on root path
echo "   Configuring web interface (/)..."
sudo tailscale serve --bg --https 443 http://127.0.0.1:9000 2>&1 | grep -v "Serve started" || true

sleep 2

# Configure each gateway on its own path
TAILSCALE_HOSTNAME=$(tailscale status --json 2>/dev/null | grep -oE '"DNSName":"[^"]+"' | head -1 | cut -d'"' -f4 | sed 's/\.$//' || echo "")

echo ""
echo "3. Gateway HTTPS URLs (via SSH port forwarding recommended):"
echo ""
echo "   For secure context (HTTPS or localhost), use SSH port forwarding:"
echo "   ssh -L <local_port>:127.0.0.1:<gateway_port> $SSH_USER@$LIGHTSAIL_IP"
echo ""
for username in "${!GATEWAY_PORTS[@]}"; do
    PORT=${GATEWAY_PORTS[$username]}
    TOKEN=${GATEWAY_TOKENS[$username]}
    if [ -n "$PORT" ] && [ -n "$TOKEN" ]; then
        echo "   $username:"
        echo "     ssh -L 8080:127.0.0.1:$PORT $SSH_USER@$LIGHTSAIL_IP"
        echo "     Then access: http://localhost:8080?token=$TOKEN"
        echo ""
    fi
done

echo ""
echo "Note: Tailscale Serve on port 443 is reserved for the web interface."
echo "      Gateways use Docker port mapping (HTTP) which doesn't satisfy"
echo "      the secure context requirement. Use SSH port forwarding for HTTPS/localhost access."

SSH_EOF

echo ""
echo "=========================================="
echo "Configuration Complete"
echo "=========================================="
