#!/bin/bash
# verify-tailscale-serve.sh - Verify Tailscale Serve is properly configured

set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/load-config.sh"

echo "=========================================="
echo "Verify Tailscale Serve Configuration"
echo "=========================================="
echo ""

ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" bash << 'SSH_EOF'
set -e

REMOTE_REPO_PATH="${REMOTE_REPO_PATH:-/home/openclaw/openclaw}"
cd "$REMOTE_REPO_PATH"

export PATH="$HOME/.local/venv/clawctl/bin:$PATH"
CLAWCTL_CMD="$(command -v clawctl || echo '$HOME/.local/venv/clawctl/bin/clawctl')"

USER_NAMES=$(grep -E '^\s*name\s*=\s*"' "$REMOTE_REPO_PATH/clawctl.toml" | sed 's/.*name\s*=\s*"\(.*\)".*/\1/' || echo "")

for username in $USER_NAMES; do
    echo "Checking $username..."
    CONFIG_FILE="$HOME/data/users/$username/openclaw/openclaw.json"
    
    if [ ! -f "$CONFIG_FILE" ]; then
        echo "  ✗ Config file not found"
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

print(f"  Gateway bind: {bind}")
print(f"  Tailscale mode: {tailscale_mode}")

if bind == "loopback" and tailscale_mode == "serve":
    print("  ✓ Tailscale Serve is ENABLED")
    print("  ✓ Configuration is correct")
elif bind == "lan":
    print("  ⚠ Using Docker port mapping (Tailscale Serve not enabled)")
else:
    print(f"  ⚠ Unexpected configuration: bind={bind}, tailscale_mode={tailscale_mode}")
PYTHON_CHECK
    
    echo ""
done

echo "Container status:"
"$CLAWCTL_CMD" status --config "$REMOTE_REPO_PATH/clawctl.toml" || true

SSH_EOF

echo ""
echo "=========================================="
echo "Verification Complete"
echo "=========================================="
