#!/bin/bash
# regenerate-with-containers-stopped.sh - Stop containers, regenerate, restart

set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/load-config.sh"

echo "=========================================="
echo "Regenerate Configs (Containers Stopped)"
echo "=========================================="
echo ""

ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" bash << 'SSH_EOF'
set -e

REMOTE_REPO_PATH="${REMOTE_REPO_PATH:-/home/openclaw/openclaw}"
cd "$REMOTE_REPO_PATH"

export PATH="$HOME/.local/venv/clawctl/bin:$PATH"
CLAWCTL_CMD="$(command -v clawctl || echo '$HOME/.local/venv/clawctl/bin/clawctl')"

USER_NAMES=$(grep -E '^\s*name\s*=\s*"' "$REMOTE_REPO_PATH/clawctl.toml" | sed 's/.*name\s*=\s*"\(.*\)".*/\1/' || echo "")

echo "1. Stopping all containers..."
for username in $USER_NAMES; do
    echo "   Stopping $username..."
    "$CLAWCTL_CMD" stop "$username" --config "$REMOTE_REPO_PATH/clawctl.toml" 2>/dev/null || {
        echo "     (already stopped or doesn't exist)"
    }
done

echo ""
echo "2. Waiting for containers to fully stop..."
sleep 3

echo ""
echo "3. Regenerating configs..."
for username in $USER_NAMES; do
    echo "   Regenerating $username..."
    unset TAILSCALE_ENABLED
    "$CLAWCTL_CMD" config regenerate "$username" --config "$REMOTE_REPO_PATH/clawctl.toml" || {
        echo "     ✗ Failed"
        continue
    }
    
    # Verify immediately
    CONFIG_FILE="$HOME/data/users/$username/openclaw/openclaw.json"
    python3 << PYTHON_CHECK
import json
from pathlib import Path

config_file = Path("$CONFIG_FILE")
config = json.loads(config_file.read_text())

gateway = config.get("gateway", {})
bind = gateway.get("bind", "")
tailscale_mode = gateway.get("tailscale", {}).get("mode", "")

print(f"     bind: {bind}, tailscale.mode: {tailscale_mode}")

if bind == "loopback" and tailscale_mode == "serve":
    print(f"     ✓ Tailscale Serve enabled")
    exit(0)
else:
    print(f"     ✗ Still wrong!")
    exit(1)
PYTHON_CHECK
    
    if [ $? -eq 0 ]; then
        echo "     ✓ Config verified"
    else
        echo "     ✗ Config verification failed!"
    fi
done

echo ""
echo "4. Starting containers..."
for username in $USER_NAMES; do
    echo "   Starting $username..."
    "$CLAWCTL_CMD" start "$username" --config "$REMOTE_REPO_PATH/clawctl.toml" || {
        echo "     ⚠ Failed to start"
        continue
    }
done

echo ""
echo "=========================================="
echo "✓ Complete"
echo "=========================================="

SSH_EOF

echo ""
echo "=========================================="
echo "Done"
echo "=========================================="
