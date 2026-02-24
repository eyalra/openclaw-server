#!/bin/bash
# check-users.sh - Check configured users on the server

set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/load-config.sh"

echo "=========================================="
echo "Check Configured Users"
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

echo "1. Checking clawctl.toml configuration..."
if [ -f "$REMOTE_REPO_PATH/clawctl.toml" ]; then
    echo "   ✓ Config file exists: $REMOTE_REPO_PATH/clawctl.toml"
    echo ""
    echo "   Configured users:"
    grep -E '^\s*name\s*=\s*' "$REMOTE_REPO_PATH/clawctl.toml" | grep -v '^#' | sed 's/.*name\s*=\s*"\(.*\)".*/     - \1/' || echo "     (none found)"
    echo ""
else
    echo "   ✗ Config file not found: $REMOTE_REPO_PATH/clawctl.toml"
fi

echo "2. Checking user status with clawctl..."
if command -v clawctl >/dev/null 2>&1 || [ -f "$HOME/.local/venv/clawctl/bin/clawctl" ]; then
    CLAWCTL_CMD="$(command -v clawctl || echo "$HOME/.local/venv/clawctl/bin/clawctl")"
    echo "   Using: $CLAWCTL_CMD"
    echo ""
    "$CLAWCTL_CMD" status --config "$REMOTE_REPO_PATH/clawctl.toml" 2>&1 || echo "   (status command failed)"
else
    echo "   ⚠ clawctl not found"
fi

echo ""
echo "3. Checking Docker containers..."
echo "   Containers:"
docker ps -a --format "   {{.Names}}\t{{.Status}}" | grep "^   openclaw-" || echo "   (no openclaw containers found)"

echo ""
echo "4. Checking user data directories..."
if [ -d "$HOME/data/users" ]; then
    echo "   User directories:"
    ls -1 "$HOME/data/users/" 2>/dev/null | sed 's/^/     - /' || echo "     (none found)"
else
    echo "   ⚠ User data directory not found: $HOME/data/users"
fi

SSH_EOF

echo ""
echo "=========================================="
echo "Check Complete"
echo "=========================================="
