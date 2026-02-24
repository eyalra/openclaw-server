#!/bin/bash
# force-regenerate-tailscale.sh - Force regenerate configs with Tailscale Serve

set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/load-config.sh"

echo "=========================================="
echo "Force Regenerate with Tailscale Serve"
echo "=========================================="
echo ""

ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" bash << 'SSH_EOF'
set -e

REMOTE_REPO_PATH="${REMOTE_REPO_PATH:-/home/openclaw/openclaw}"
cd "$REMOTE_REPO_PATH"

export PATH="$HOME/.local/venv/clawctl/bin:$PATH"
CLAWCTL_CMD="$(command -v clawctl || echo '$HOME/.local/venv/clawctl/bin/clawctl')"

echo "1. Clearing Python cache..."
find "$REMOTE_REPO_PATH/src" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$REMOTE_REPO_PATH/src" -name "*.pyc" -delete 2>/dev/null || true
echo "   ✓ Cache cleared"

echo ""
echo "2. Verifying Tailscale detection..."
python3 << PYTHON_TEST
import sys
import os
from pathlib import Path

sys.path.insert(0, "$REMOTE_REPO_PATH/src")

# Clear any environment override
if "TAILSCALE_ENABLED" in os.environ:
    del os.environ["TAILSCALE_ENABLED"]

from clawlib.core.openclaw_config import _is_tailscale_available

result = _is_tailscale_available()
print(f"   _is_tailscale_available() = {result}")

if not result:
    print("   ✗ Tailscale not detected!")
    sys.exit(1)

print("   ✓ Tailscale detection works")
PYTHON_TEST

echo ""
echo "3. Regenerating configs for all users..."
USER_NAMES=$(grep -E '^\s*name\s*=\s*"' "$REMOTE_REPO_PATH/clawctl.toml" | sed 's/.*name\s*=\s*"\(.*\)".*/\1/' || echo "")

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

if bind == "loopback" and tailscale_mode == "serve":
    print(f"     ✓ Tailscale Serve enabled")
else:
    print(f"     ✗ Still wrong: bind={bind}, mode={tailscale_mode}")
    exit(1)
PYTHON_CHECK
    
    if [ $? -eq 0 ]; then
        echo "     ✓ Config verified"
    else
        echo "     ✗ Config verification failed!"
    fi
done

echo ""
echo "4. Restarting containers..."
for username in $USER_NAMES; do
    echo "   Restarting $username..."
    "$CLAWCTL_CMD" restart "$username" --config "$REMOTE_REPO_PATH/clawctl.toml" || {
        echo "     ⚠ Failed to restart"
        continue
    }
done

echo ""
echo "=========================================="
echo "✓ Regeneration Complete"
echo "=========================================="

SSH_EOF

echo ""
echo "=========================================="
echo "Done"
echo "=========================================="
