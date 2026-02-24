#!/bin/bash
# gateway-port-forward.sh - Create SSH port forward for gateway access

set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/load-config.sh"

if [ -z "$1" ]; then
    echo "Usage: $0 <username> [local_port]"
    echo ""
    echo "Example: $0 alice 32768"
    echo ""
    echo "This creates an SSH port forward so you can access the gateway"
    echo "via localhost (which satisfies the secure context requirement)."
    exit 1
fi

USERNAME="$1"
LOCAL_PORT="${2:-32768}"

echo "=========================================="
echo "Gateway Port Forward for $USERNAME"
echo "=========================================="
echo ""

# Get the remote port
REMOTE_PORT=$(ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" bash << EOF
cd ${REMOTE_REPO_PATH:-/home/openclaw/openclaw}
export PATH="\$HOME/.local/venv/clawctl/bin:\$PATH"
CLAWCTL_CMD="\$(command -v clawctl || echo '\$HOME/.local/venv/clawctl/bin/clawctl')"
"\$CLAWCTL_CMD" status --config "\${REMOTE_REPO_PATH:-/home/openclaw/openclaw}/clawctl.toml" 2>/dev/null | grep -E "^\\s*$USERNAME" | awk '{print \$3}' || echo ""
EOF
)

if [ -z "$REMOTE_PORT" ] || [ "$REMOTE_PORT" = "-" ]; then
    echo "✗ Could not determine port for user '$USERNAME'"
    echo "  Make sure the container is running: ./deploy/lightsail/scripts/check-users.sh"
    exit 1
fi

echo "Remote port: $REMOTE_PORT"
echo "Local port: $LOCAL_PORT"
echo ""
echo "Creating SSH port forward..."
echo "  Local: http://localhost:$LOCAL_PORT"
echo "  Remote: localhost:$REMOTE_PORT"
echo ""
echo "Press Ctrl+C to stop the port forward"
echo ""

# Get gateway token
GATEWAY_TOKEN=$(ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" bash << EOF
cd ${REMOTE_REPO_PATH:-/home/openclaw/openclaw}
export PATH="\$HOME/.local/venv/clawctl/bin:\$PATH"
CLAWCTL_CMD="\$(command -v clawctl || echo '\$HOME/.local/venv/clawctl/bin/clawctl')"
"\$CLAWCTL_CMD" status --config "\${REMOTE_REPO_PATH:-/home/openclaw/openclaw}/clawctl.toml" 2>/dev/null | grep -A 5 "^\\s*$USERNAME" | grep -oE 'token=[^[:space:]]+' | head -1 | cut -d= -f2 || echo ""
EOF
)

if [ -n "$GATEWAY_TOKEN" ]; then
    echo "Gateway URL:"
    echo "  http://localhost:$LOCAL_PORT?token=$GATEWAY_TOKEN"
    echo ""
fi

# Create port forward
ssh -L "$LOCAL_PORT:localhost:$REMOTE_PORT" -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP"
