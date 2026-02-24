#!/bin/bash
# test-default-tailscale-serve.sh - Test that Tailscale Serve is enabled by default

set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/load-config.sh"

echo "=========================================="
echo "Test Default Tailscale Serve Configuration"
echo "=========================================="
echo ""
echo "This verifies that Tailscale Serve is enabled by default when Tailscale is available."
echo ""

ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" bash << 'SSH_EOF'
set -e

REMOTE_REPO_PATH="${REMOTE_REPO_PATH:-/home/openclaw/openclaw}"
cd "$REMOTE_REPO_PATH"

export PATH="$HOME/.local/venv/clawctl/bin:$PATH"
CLAWCTL_CMD="$(command -v clawctl || echo '$HOME/.local/venv/clawctl/bin/clawctl')"

echo "1. Verifying Tailscale is available..."
TAILSCALE_SOCKET="/var/run/tailscale/tailscaled.sock"
if [ ! -S "$TAILSCALE_SOCKET" ]; then
    echo "   ✗ Tailscale socket not found"
    echo "   Install Tailscale first"
    exit 1
fi
echo "   ✓ Tailscale socket found"

# Clear any TAILSCALE_ENABLED override to test default behavior
unset TAILSCALE_ENABLED

echo ""
echo "2. Testing config generation (should auto-detect Tailscale)..."
python3 << PYTHON_TEST
import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, "$REMOTE_REPO_PATH/src")

# Clear TAILSCALE_ENABLED to test default
if "TAILSCALE_ENABLED" in os.environ:
    del os.environ["TAILSCALE_ENABLED"]

from clawlib.core.openclaw_config import _is_tailscale_available

result = _is_tailscale_available()
print(f"   _is_tailscale_available() = {result}")

if result:
    print("   ✓ Tailscale Serve will be enabled by default")
else:
    print("   ✗ Tailscale Serve will NOT be enabled")
    print("   This is unexpected if Tailscale socket exists!")
    sys.exit(1)
PYTHON_TEST

echo ""
echo "3. Regenerating configs for all users..."
USER_NAMES=$(grep -E '^\s*name\s*=\s*"' "$REMOTE_REPO_PATH/clawctl.toml" | sed 's/.*name\s*=\s*"\(.*\)".*/\1/' || echo "")

for username in $USER_NAMES; do
    echo "   Regenerating $username..."
    unset TAILSCALE_ENABLED  # Ensure default behavior
    "$CLAWCTL_CMD" config regenerate "$username" --config "$REMOTE_REPO_PATH/clawctl.toml" || {
        echo "     ✗ Failed"
        continue
    }
    echo "     ✓ Regenerated"
done

echo ""
echo "4. Verifying Tailscale Serve is enabled in configs..."
ALL_CORRECT=true
for username in $USER_NAMES; do
    CONFIG_FILE="$HOME/data/users/$username/openclaw/openclaw.json"
    if [ ! -f "$CONFIG_FILE" ]; then
        echo "   ⚠ $username: Config file not found"
        continue
    fi
    
    python3 << PYTHON_CHECK
import json
from pathlib import Path

config_file = Path("$CONFIG_FILE")
config = json.loads(config_file.read_text())

gateway = config.get("gateway", {})
bind = gateway.get("bind", "")
tailscale_config = gateway.get("tailscale", {})
tailscale_mode = tailscale_config.get("mode", "")

print(f"   $username:")
print(f"     bind: {bind}")
print(f"     tailscale.mode: {tailscale_mode}")

if bind == "loopback" and tailscale_mode == "serve":
    print(f"     ✓ Tailscale Serve ENABLED")
else:
    print(f"     ✗ Tailscale Serve NOT enabled (bind={bind}, mode={tailscale_mode})")
    exit(1)
PYTHON_CHECK
    
    if [ $? -ne 0 ]; then
        ALL_CORRECT=false
    fi
done

if [ "$ALL_CORRECT" != "true" ]; then
    echo ""
    echo "   ✗ Some configs are incorrect"
    exit 1
fi

echo ""
echo "5. Restarting containers to apply changes..."
for username in $USER_NAMES; do
    echo "   Restarting $username..."
    "$CLAWCTL_CMD" restart "$username" --config "$REMOTE_REPO_PATH/clawctl.toml" || {
        echo "     ⚠ Failed to restart"
        continue
    }
done

echo ""
echo "=========================================="
echo "✓ Test Passed!"
echo "=========================================="
echo ""
echo "Tailscale Serve is enabled by default when Tailscale is available."
echo ""
echo "Gateway URLs (HTTPS via Tailscale Serve):"
TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "")
for username in $USER_NAMES; do
    GATEWAY_TOKEN=$("$CLAWCTL_CMD" status --config "$REMOTE_REPO_PATH/clawctl.toml" 2>/dev/null | grep -A 5 "^\\s*$username" | grep -oE 'token=[^[:space:]]+' | head -1 | cut -d= -f2 || echo "")
    if [ -n "$GATEWAY_TOKEN" ] && [ -n "$TAILSCALE_IP" ]; then
        echo "  $username: https://$TAILSCALE_IP:443?token=$GATEWAY_TOKEN"
    fi
done

SSH_EOF

echo ""
echo "=========================================="
echo "Test Complete"
echo "=========================================="
