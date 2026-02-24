#!/bin/bash
# fix-gateway-connection.sh - Fix gateway connection errors by regenerating configs

set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/load-config.sh"

echo "=========================================="
echo "Fix Gateway Connection Errors"
echo "=========================================="
echo ""
echo "As of OpenClaw 2026.2.21, the gateway requires HTTPS or localhost"
echo "for device identity, even with allowInsecureAuth enabled."
echo ""
echo "Solutions:"
echo "  1. Use SSH port forwarding to access via localhost"
echo "  2. Enable Tailscale Serve mode for HTTPS"
echo "  3. Use a reverse proxy (nginx/Caddy) for HTTPS"
echo ""
echo "This script will regenerate configs and show you the localhost URLs."
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

echo "1. Reading users from clawctl.toml..."
if [ ! -f "$REMOTE_REPO_PATH/clawctl.toml" ]; then
    echo "   ✗ Config file not found: $REMOTE_REPO_PATH/clawctl.toml"
    exit 1
fi

# Extract all user names from config
USER_NAMES=$(grep -E '^\s*name\s*=\s*"' "$REMOTE_REPO_PATH/clawctl.toml" | sed 's/.*name\s*=\s*"\(.*\)".*/\1/' || echo "")

if [ -z "$USER_NAMES" ]; then
    echo "   ⚠ No users found in config file"
    exit 1
fi

echo "   Found users: $(echo $USER_NAMES | tr '\n' ' ')"
echo ""

# Regenerate configs for all users
for username in $USER_NAMES; do
    echo "=========================================="
    echo "Fixing gateway config for $username"
    echo "=========================================="
    
    if command -v clawctl >/dev/null 2>&1 || [ -f "$HOME/.local/venv/clawctl/bin/clawctl" ]; then
        echo "   Regenerating openclaw.json..."
        "$CLAWCTL_CMD" config regenerate "$username" --config "$REMOTE_REPO_PATH/clawctl.toml" || {
            echo "   ⚠ Failed to regenerate config for $username"
            continue
        }
        
        echo "   Restarting container..."
        "$CLAWCTL_CMD" restart "$username" --config "$REMOTE_REPO_PATH/clawctl.toml" || {
            echo "   ⚠ Failed to restart container for $username"
            continue
        }
        
        echo "   ✓ Successfully updated $username"
    else
        echo "   ✗ ERROR: clawctl not found"
        exit 1
    fi
    echo ""
done

echo "=========================================="
echo "Gateway Fix Complete!"
echo "=========================================="
echo ""
echo "Final status:"
"$CLAWCTL_CMD" status --config "$REMOTE_REPO_PATH/clawctl.toml" || true

SSH_EOF

echo ""
echo "=========================================="
echo "Fix Applied"
echo "=========================================="
echo ""
echo "To access the gateway, use one of these methods:"
echo ""
echo "1. SSH Port Forwarding (Recommended):"
echo "   ssh -L 32768:localhost:32768 -p $SSH_PORT -i $SSH_KEY $SSH_USER@$LIGHTSAIL_IP"
echo "   Then access: http://localhost:32768?token=<token>"
echo ""
echo "2. Enable Tailscale Serve (for HTTPS):"
echo "   See deploy/lightsail/docs/SOP-03-tailscale-setup.md"
echo ""
echo "3. Use localhost URLs from the status output above"
echo ""
