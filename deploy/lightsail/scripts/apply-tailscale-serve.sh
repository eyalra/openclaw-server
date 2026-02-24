#!/bin/bash
# apply-tailscale-serve.sh - Apply Tailscale Serve configuration to all users

set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/load-config.sh"

echo "=========================================="
echo "Apply Tailscale Serve Configuration"
echo "=========================================="
echo ""
echo "This will regenerate configs and restart containers to enable Tailscale Serve."
echo ""
echo "Target server: $SSH_USER@$LIGHTSAIL_IP:$SSH_PORT"
echo ""

ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" bash << 'SSH_EOF'
set -e

REMOTE_REPO_PATH="${REMOTE_REPO_PATH:-/home/openclaw/openclaw}"
cd "$REMOTE_REPO_PATH"

# Ensure PATH includes venv bin
export PATH="$HOME/.local/venv/clawctl/bin:$PATH"

CLAWCTL_CMD="$(command -v clawctl || echo '$HOME/.local/venv/clawctl/bin/clawctl')"

echo "1. Verifying Tailscale availability..."
TAILSCALE_SOCKET="/var/run/tailscale/tailscaled.sock"
if [ ! -S "$TAILSCALE_SOCKET" ]; then
    echo "   ✗ Tailscale socket not found: $TAILSCALE_SOCKET"
    echo "   Install and authenticate Tailscale first"
    exit 1
fi

TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "")
TAILSCALE_HOSTNAME=$(tailscale status --json 2>/dev/null | grep -oE '"DNSName":"[^"]+"' | head -1 | cut -d'"' -f4 || echo "")

echo "   ✓ Tailscale is available"
echo "   Tailscale IP: $TAILSCALE_IP"
if [ -n "$TAILSCALE_HOSTNAME" ]; then
    echo "   Tailscale hostname: $TAILSCALE_HOSTNAME"
fi
echo ""

echo "2. Reading users from config..."
USER_NAMES=$(grep -E '^\s*name\s*=\s*"' "$REMOTE_REPO_PATH/clawctl.toml" | sed 's/.*name\s*=\s*"\(.*\)".*/\1/' || echo "")

if [ -z "$USER_NAMES" ]; then
    echo "   ⚠ No users found in config"
    exit 1
fi

echo "   Found users: $(echo $USER_NAMES | tr '\n' ' ')"
echo ""

echo "3. Regenerating configs with Tailscale Serve enabled..."
for username in $USER_NAMES; do
    echo "   Regenerating config for $username..."
    "$CLAWCTL_CMD" config regenerate "$username" --config "$REMOTE_REPO_PATH/clawctl.toml" || {
        echo "     ⚠ Failed to regenerate config for $username"
        continue
    }
    echo "     ✓ Config regenerated"
done

echo ""
echo "4. Verifying Tailscale Serve is enabled in configs..."
for username in $USER_NAMES; do
    CONFIG_FILE="$HOME/data/users/$username/openclaw/openclaw.json"
    if [ -f "$CONFIG_FILE" ]; then
        # Check if Tailscale Serve is configured
        if python3 -c "import json; c=json.load(open('$CONFIG_FILE')); g=c.get('gateway',{}); print('serve' if g.get('tailscale',{}).get('mode')=='serve' else 'port-mapping')" 2>/dev/null | grep -q serve; then
            echo "   ✓ $username: Tailscale Serve enabled"
        else
            echo "   ⚠ $username: Still using port mapping"
        fi
    fi
done

echo ""
echo "5. Restarting containers to apply changes..."
for username in $USER_NAMES; do
    echo "   Restarting $username..."
    "$CLAWCTL_CMD" restart "$username" --config "$REMOTE_REPO_PATH/clawctl.toml" || {
        echo "     ⚠ Failed to restart $username"
        continue
    }
    echo "     ✓ Restarted"
done

echo ""
echo "=========================================="
echo "Tailscale Serve Applied!"
echo "=========================================="
echo ""
echo "Gateway URLs (HTTPS via Tailscale Serve):"
echo ""

# Show URLs for each user
for username in $USER_NAMES; do
    GATEWAY_TOKEN=$("$CLAWCTL_CMD" status --config "$REMOTE_REPO_PATH/clawctl.toml" 2>/dev/null | grep -A 5 "^\\s*$username" | grep -oE 'token=[^[:space:]]+' | head -1 | cut -d= -f2 || echo "")
    
    if [ -n "$GATEWAY_TOKEN" ]; then
        TOKEN_PARAM="?token=$GATEWAY_TOKEN"
        echo "  $username:"
        if [ -n "$TAILSCALE_HOSTNAME" ]; then
            echo "    https://$TAILSCALE_HOSTNAME:443$TOKEN_PARAM"
        fi
        echo "    https://$TAILSCALE_IP:443$TOKEN_PARAM"
        echo ""
    fi
done

echo "Note: These HTTPS URLs satisfy the gateway's secure context requirement."
echo "You can now access the gateway directly without SSH port forwarding!"

SSH_EOF

echo ""
echo "=========================================="
echo "Configuration Applied"
echo "=========================================="
