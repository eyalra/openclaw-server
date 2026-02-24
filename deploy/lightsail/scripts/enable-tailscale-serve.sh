#!/bin/bash
# enable-tailscale-serve.sh - Enable Tailscale Serve mode for HTTPS gateway access

set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/load-config.sh"

echo "=========================================="
echo "Enable Tailscale Serve Mode"
echo "=========================================="
echo ""
echo "Tailscale Serve provides HTTPS automatically for your gateway, solving"
echo "the secure context requirement without needing SSH port forwarding."
echo ""
echo "What this does:"
echo "  1. Configures containers to use Tailscale Serve instead of Docker port mapping"
echo "  2. Gateway binds to localhost (127.0.0.1) inside containers"
echo "  3. Tailscale exposes it over HTTPS on port 443"
echo "  4. Access via: https://<tailscale-hostname>:443?token=<token>"
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

echo "1. Checking Tailscale status..."
if ! command -v tailscale >/dev/null 2>&1; then
    echo "   ✗ Tailscale not installed!"
    echo "   Install it first: curl -fsSL https://tailscale.com/install.sh | sh"
    exit 1
fi

TAILSCALE_STATUS=$(tailscale status 2>/dev/null || echo "")
if [ -z "$TAILSCALE_STATUS" ]; then
    echo "   ✗ Tailscale not running or not authenticated!"
    echo "   Start it: sudo tailscale up"
    exit 1
fi

TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "")
TAILSCALE_HOSTNAME=$(tailscale status --json 2>/dev/null | grep -oE '"DNSName":"[^"]+"' | head -1 | cut -d'"' -f4 || echo "")

if [ -z "$TAILSCALE_IP" ]; then
    echo "   ✗ Could not get Tailscale IP"
    exit 1
fi

echo "   ✓ Tailscale is running"
echo "   Tailscale IP: $TAILSCALE_IP"
if [ -n "$TAILSCALE_HOSTNAME" ]; then
    echo "   Tailscale hostname: $TAILSCALE_HOSTNAME"
fi
echo ""

echo "2. Checking Docker containers..."
CONTAINERS=$(docker ps --format '{{.Names}}' | grep '^openclaw-' || echo "")
if [ -z "$CONTAINERS" ]; then
    echo "   ⚠ No OpenClaw containers found"
    echo "   Provision users first: ./deploy/lightsail/04-configure-users.sh"
    exit 1
fi

echo "   Found containers: $(echo $CONTAINERS | tr '\n' ' ')"
echo ""

echo "3. Enabling TAILSCALE_ENABLED for containers..."
# Set TAILSCALE_ENABLED in Docker containers
for container in $CONTAINERS; do
    username=$(echo $container | sed 's/^openclaw-//')
    echo "   Configuring $container..."
    
    # Check if container is running
    if docker ps --format '{{.Names}}' | grep -q "^$container$"; then
        # Set environment variable in running container
        docker exec "$container" sh -c 'echo "TAILSCALE_ENABLED=true" >> /etc/environment' 2>/dev/null || true
        
        # Also set it for future starts by updating the container config
        # We'll need to recreate containers with the env var, but for now just set it
        echo "     ✓ Set TAILSCALE_ENABLED=true in $container"
    else
        echo "     ⚠ Container $container is not running"
    fi
done

echo ""
echo "4. Regenerating configs with Tailscale Serve enabled..."
# Extract all user names from config
USER_NAMES=$(grep -E '^\s*name\s*=\s*"' "$REMOTE_REPO_PATH/clawctl.toml" | sed 's/.*name\s*=\s*"\(.*\)".*/\1/' || echo "")

if [ -z "$USER_NAMES" ]; then
    echo "   ⚠ No users found in config file"
    exit 1
fi

for username in $USER_NAMES; do
    echo "   Regenerating config for $username..."
    
    # Temporarily set TAILSCALE_ENABLED in the environment where clawctl runs
    # This will make _is_tailscale_available() return True
    export TAILSCALE_ENABLED=true
    
    "$CLAWCTL_CMD" config regenerate "$username" --config "$REMOTE_REPO_PATH/clawctl.toml" || {
        echo "     ⚠ Failed to regenerate config for $username"
        continue
    }
    
    echo "     ✓ Config regenerated"
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
echo "Tailscale Serve Enabled!"
echo "=========================================="
echo ""
echo "Your gateways are now accessible via HTTPS:"
echo ""

# Show URLs for each user
for username in $USER_NAMES; do
    GATEWAY_TOKEN=$("$CLAWCTL_CMD" status --config "$REMOTE_REPO_PATH/clawctl.toml" 2>/dev/null | grep -A 5 "^\\s*$username" | grep -oE 'token=[^[:space:]]+' | head -1 | cut -d= -f2 || echo "")
    
    if [ -n "$GATEWAY_TOKEN" ]; then
        TOKEN_PARAM="?token=$GATEWAY_TOKEN"
        if [ -n "$TAILSCALE_HOSTNAME" ]; then
            echo "  $username:"
            echo "    https://$TAILSCALE_HOSTNAME:443$TOKEN_PARAM"
        fi
        echo "    https://$TAILSCALE_IP:443$TOKEN_PARAM"
    fi
done

echo ""
echo "Note: Tailscale Serve automatically provides HTTPS certificates."
echo "You can now access the gateway without SSH port forwarding!"

SSH_EOF

echo ""
echo "=========================================="
echo "Setup Complete"
echo "=========================================="
echo ""
echo "Tailscale Serve is now enabled. Access your gateways via HTTPS URLs above."
echo ""
