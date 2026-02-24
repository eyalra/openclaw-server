#!/bin/bash
# provision-all-users.sh - Provision all users from clawctl.toml that aren't provisioned yet

set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/load-config.sh"

echo "=========================================="
echo "Provision All Unprovisioned Users"
echo "=========================================="
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

# Check which users need provisioning
UNPROVISIONED=()
for username in $USER_NAMES; do
    if docker ps -a --format '{{.Names}}' | grep -q "^openclaw-$username$"; then
        echo "   ✓ $username: already provisioned"
    else
        echo "   ⚠ $username: not provisioned"
        UNPROVISIONED+=("$username")
    fi
done

echo ""

if [ ${#UNPROVISIONED[@]} -eq 0 ]; then
    echo "✓ All users are already provisioned!"
    exit 0
fi

echo "2. Provisioning ${#UNPROVISIONED[@]} user(s)..."
echo ""

# Provision each unprovisioned user
for username in "${UNPROVISIONED[@]}"; do
    echo "=========================================="
    echo "Provisioning $username"
    echo "=========================================="
    
    if command -v clawctl >/dev/null 2>&1 || [ -f "$HOME/.local/venv/clawctl/bin/clawctl" ]; then
        echo "   Running: $CLAWCTL_CMD user add $username"
        "$CLAWCTL_CMD" user add "$username" --config "$REMOTE_REPO_PATH/clawctl.toml" || {
            echo "   ✗ Provisioning failed for $username"
            echo "   You may need to run manually: clawctl user add $username"
            continue
        }
        echo "   ✓ Successfully provisioned $username"
    else
        echo "   ✗ ERROR: clawctl not found"
        echo "   Install it first:"
        echo "     uv venv ~/.local/venv/clawctl"
        echo "     uv pip install -e '.' --python ~/.local/venv/clawctl/bin/python"
        exit 1
    fi
    echo ""
done

echo "=========================================="
echo "Provisioning Complete!"
echo "=========================================="
echo ""
echo "Final status:"
"$CLAWCTL_CMD" status --config "$REMOTE_REPO_PATH/clawctl.toml" || true

SSH_EOF

echo ""
echo "=========================================="
echo "All Users Provisioned"
echo "=========================================="
