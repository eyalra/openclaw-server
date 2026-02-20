#!/bin/bash
# 05-verify-deployment.sh
# Verify deployment: check containers, show status, test access

set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/scripts/load-config.sh"

echo "=========================================="
echo "Verify OpenClaw Deployment"
echo "=========================================="
echo ""

# Verify on remote server
ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" << REMOTE_SCRIPT
set -e

cd $REMOTE_REPO_PATH

# Ensure PATH includes venv bin if clawctl is installed there
CLAWCTL_VENV="\$HOME/.local/venv/clawctl"
if [ -d "\$CLAWCTL_VENV" ]; then
    export PATH="\$CLAWCTL_VENV/bin:\$PATH"
fi

echo "Step 1: Checking Docker..."
if command -v docker >/dev/null 2>&1; then
    echo "  ✓ Docker installed"
    docker --version
else
    echo "  ✗ Docker not found"
    exit 1
fi

echo ""
echo "Step 2: Checking containers..."
CONTAINERS=\$(docker ps -a --filter "name=openclaw-" --format "{{.Names}}" || echo "")
if [ -z "\$CONTAINERS" ]; then
    echo "  ⚠ No OpenClaw containers found"
    echo "  Run: clawctl user add <username> to create containers"
else
    echo "  Found containers:"
    echo "\$CONTAINERS" | while read -r container; do
        STATUS=\$(docker inspect --format='{{.State.Status}}' "\$container" 2>/dev/null || echo "unknown")
        echo "    - \$container: \$STATUS"
    done
fi

echo ""
echo "Step 3: Checking Tailscale..."
if command -v tailscale >/dev/null 2>&1; then
    TAILSCALE_STATUS=\$(tailscale status 2>/dev/null | head -1 || echo "not connected")
    if echo "\$TAILSCALE_STATUS" | grep -q "100\."; then
        TAILSCALE_IP=\$(tailscale ip -4)
        echo "  ✓ Tailscale connected"
        echo "  Tailscale IP: \$TAILSCALE_IP"
    else
        echo "  ⚠ Tailscale not connected"
        echo "  Run: sudo tailscale up"
    fi
else
    echo "  ⚠ Tailscale not installed"
fi

echo ""
echo "Step 4: Checking knowledge directory..."
if [ -d "$REMOTE_HOME/data/knowledge" ]; then
    echo "  ✓ Knowledge directory exists"
    ls -la "$REMOTE_HOME/data/knowledge" | head -5
else
    echo "  ⚠ Knowledge directory not found"
fi

echo ""
echo "Step 5: Container status (using clawctl)..."
if command -v clawctl >/dev/null 2>&1 && [ -f "clawctl.toml" ]; then
    echo ""
    clawctl status --config clawctl.toml || echo "  ⚠ Status check failed"
else
    echo "  ⚠ clawctl not available or config not found"
fi

echo ""
echo "=========================================="
echo "Verification Summary"
echo "=========================================="
echo ""
echo "Access URLs (if containers are running):"
if command -v tailscale >/dev/null 2>&1; then
    TAILSCALE_IP=\$(tailscale ip -4 2>/dev/null || echo "")
    if [ -n "\$TAILSCALE_IP" ]; then
        echo "  Tailscale: http://\$TAILSCALE_IP:18789 (user1)"
        echo "             http://\$TAILSCALE_IP:18790 (user2)"
    fi
fi

PUBLIC_IP=\$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "")
if [ -n "\$PUBLIC_IP" ]; then
    echo "  Public IP: http://\$PUBLIC_IP:18789 (user1)"
    echo "             http://\$PUBLIC_IP:18790 (user2)"
    echo "  (Note: Only accessible via Tailscale or SSH tunnel)"
fi

echo ""
echo "To view logs:"
echo "  docker logs openclaw-user1"
echo "  docker logs openclaw-user2"
echo ""
echo "To restart containers:"
echo "  clawctl restart-all --config clawctl.toml"
REMOTE_SCRIPT

echo ""
echo "=========================================="
echo "Verification complete!"
echo "=========================================="
echo ""
echo "If containers are not running, check:"
echo "  1. Run: clawctl user add <username> (if users not created)"
echo "  2. Check logs: docker logs openclaw-<username>"
echo "  3. Verify secrets exist: ls $REMOTE_HOME/data/secrets/<username>/"
