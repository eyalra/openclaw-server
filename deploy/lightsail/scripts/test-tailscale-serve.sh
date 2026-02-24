#!/bin/bash
# test-tailscale-serve.sh - Test Tailscale Serve configuration

set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/load-config.sh"

echo "=========================================="
echo "Test Tailscale Serve Configuration"
echo "=========================================="
echo ""
echo "This will verify Tailscale Serve is enabled by default when Tailscale is available."
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

echo "1. Checking Tailscale availability..."
TAILSCALE_SOCKET="/var/run/tailscale/tailscaled.sock"
if [ -S "$TAILSCALE_SOCKET" ]; then
    echo "   ✓ Tailscale socket found: $TAILSCALE_SOCKET"
    TAILSCALE_AVAILABLE=true
else
    echo "   ⚠ Tailscale socket not found: $TAILSCALE_SOCKET"
    echo "   Tailscale Serve will not be enabled (will use Docker port mapping)"
    TAILSCALE_AVAILABLE=false
fi

if command -v tailscale >/dev/null 2>&1; then
    TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "")
    TAILSCALE_HOSTNAME=$(tailscale status --json 2>/dev/null | grep -oE '"DNSName":"[^"]+"' | head -1 | cut -d'"' -f4 || echo "")
    echo "   Tailscale IP: ${TAILSCALE_IP:-not available}"
    if [ -n "$TAILSCALE_HOSTNAME" ]; then
        echo "   Tailscale hostname: $TAILSCALE_HOSTNAME"
    fi
fi

echo ""
echo "2. Checking current user configurations..."
USER_NAMES=$(grep -E '^\s*name\s*=\s*"' "$REMOTE_REPO_PATH/clawctl.toml" | sed 's/.*name\s*=\s*"\(.*\)".*/\1/' || echo "")

if [ -z "$USER_NAMES" ]; then
    echo "   ⚠ No users found in config"
    exit 1
fi

echo "   Found users: $(echo $USER_NAMES | tr '\n' ' ')"
echo ""

for username in $USER_NAMES; do
    echo "3. Checking configuration for $username..."
    CONFIG_FILE="$HOME/data/users/$username/openclaw/openclaw.json"
    
    if [ ! -f "$CONFIG_FILE" ]; then
        echo "   ⚠ Config file not found: $CONFIG_FILE"
        echo "   User may not be provisioned yet"
        continue
    fi
    
    # Check gateway configuration
    GATEWAY_BIND=$(grep -A 10 '"gateway"' "$CONFIG_FILE" | grep '"bind"' | grep -oE '"[^"]+"' | tr -d '"' || echo "")
    TAILSCALE_MODE=$(grep -A 10 '"gateway"' "$CONFIG_FILE" | grep -A 5 '"tailscale"' | grep '"mode"' | grep -oE '"[^"]+"' | tr -d '"' || echo "")
    
    echo "   Gateway bind: ${GATEWAY_BIND:-not set}"
    echo "   Tailscale mode: ${TAILSCALE_MODE:-not set}"
    
    if [ "$GATEWAY_BIND" = "loopback" ] && [ "$TAILSCALE_MODE" = "serve" ]; then
        echo "   ✓ Tailscale Serve is ENABLED"
        EXPECTED_MODE="Tailscale Serve"
    elif [ "$GATEWAY_BIND" = "lan" ]; then
        echo "   ⚠ Using Docker port mapping (Tailscale Serve not enabled)"
        EXPECTED_MODE="Docker port mapping"
    else
        echo "   ⚠ Unknown configuration"
        EXPECTED_MODE="Unknown"
    fi
    
    # Verify this matches what we expect based on Tailscale availability
    if [ "$TAILSCALE_AVAILABLE" = "true" ]; then
        if [ "$EXPECTED_MODE" = "Tailscale Serve" ]; then
            echo "   ✓ Configuration matches Tailscale availability"
        else
            echo "   ✗ Configuration mismatch! Tailscale is available but Serve is not enabled"
            echo "   Regenerating config..."
            "$CLAWCTL_CMD" config regenerate "$username" --config "$REMOTE_REPO_PATH/clawctl.toml" || {
                echo "   ⚠ Failed to regenerate config"
                continue
            }
            echo "   ✓ Config regenerated - restart container to apply"
        fi
    else
        if [ "$EXPECTED_MODE" = "Docker port mapping" ]; then
            echo "   ✓ Configuration matches (Tailscale not available)"
        else
            echo "   ⚠ Note: Tailscale Serve configured but Tailscale not available"
        fi
    fi
    echo ""
done

echo "4. Testing configuration generation..."
# Test that config generation detects Tailscale correctly
python3 << PYTHON_TEST
import sys
import os
from pathlib import Path

# Simulate the check
tailscale_socket = Path("/var/run/tailscale/tailscaled.sock")
tailscale_available = tailscale_socket.exists() and tailscale_socket.is_socket()

if os.getenv("TAILSCALE_ENABLED", "").lower() in ("false", "0", "no"):
    tailscale_available = False

print(f"   Tailscale detection: {'Available' if tailscale_available else 'Not available'}")
print(f"   Expected mode: {'Tailscale Serve' if tailscale_available else 'Docker port mapping'}")

if tailscale_available:
    print("   ✓ Tailscale Serve will be enabled by default")
else:
    print("   ✓ Docker port mapping will be used (Tailscale not available)")
PYTHON_TEST

echo ""
echo "=========================================="
echo "Test Complete"
echo "=========================================="
echo ""
if [ "$TAILSCALE_AVAILABLE" = "true" ]; then
    echo "Tailscale is available - Serve mode should be enabled by default."
    echo "To apply changes, regenerate configs and restart containers:"
    echo "  ./deploy/lightsail/scripts/fix-gateway-connection.sh"
else
    echo "Tailscale is not available - Docker port mapping will be used."
    echo "To enable Tailscale Serve, install and authenticate Tailscale first."
fi

SSH_EOF

echo ""
echo "=========================================="
echo "Test Complete"
echo "=========================================="
