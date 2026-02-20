#!/bin/bash
# get-urls.sh - Get dashboard URLs for all running containers

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../scripts/load-config.sh"

# Run on remote server
ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" << 'REMOTE_SCRIPT'
set -e

cd $REMOTE_REPO_PATH

# Ensure PATH includes venv bin
CLAWCTL_VENV="$HOME/.local/venv/clawctl"
if [ -d "$CLAWCTL_VENV" ]; then
    export PATH="$CLAWCTL_VENV/bin:$PATH"
fi

# Get Tailscale IP if available
TAILSCALE_IP=""
if command -v tailscale >/dev/null 2>&1; then
    TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "")
fi

# Function to get container port
get_port() {
    local container=$1
    docker port "$container" 18789/tcp 2>/dev/null | cut -d: -f2 || echo ""
}

# Function to get gateway token
get_token() {
    local username=$1
    # Try both possible token file names (current and legacy)
    if [ -f "$REMOTE_HOME/data/secrets/$username/openclaw_gateway_token" ]; then
        cat "$REMOTE_HOME/data/secrets/$username/openclaw_gateway_token" 2>/dev/null || echo ""
    elif [ -f "$REMOTE_HOME/data/secrets/$username/gateway_token" ]; then
        cat "$REMOTE_HOME/data/secrets/$username/gateway_token" 2>/dev/null || echo ""
    fi
}

echo "Dashboard URLs:"
echo ""

# Check each container
for container in $(docker ps --filter "name=openclaw-" --format "{{.Names}}" 2>/dev/null); do
    username=$(echo "$container" | sed 's/openclaw-//')
    port=$(get_port "$container")
    token=$(get_token "$username")
    
    if [ -n "$port" ]; then
        if [ -n "$TAILSCALE_IP" ]; then
            if [ -n "$token" ]; then
                echo "$username: http://$TAILSCALE_IP:$port?token=$token"
            else
                echo "$username: http://$TAILSCALE_IP:$port"
            fi
        else
            if [ -n "$token" ]; then
                echo "$username: http://localhost:$port?token=$token"
            else
                echo "$username: http://localhost:$port"
            fi
        fi
    fi
done

echo ""
echo "To get just URLs (one per line):"
echo "  $0 | grep '^[a-z]*: http' | cut -d' ' -f2"
REMOTE_SCRIPT
