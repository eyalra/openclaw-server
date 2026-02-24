#!/bin/bash
# debug-tailscale-detection.sh - Debug why Tailscale Serve isn't being detected

set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/load-config.sh"

echo "=========================================="
echo "Debug Tailscale Detection"
echo "=========================================="
echo ""

ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" bash << 'SSH_EOF'
set -e

REMOTE_REPO_PATH="${REMOTE_REPO_PATH:-/home/openclaw/openclaw}"
cd "$REMOTE_REPO_PATH"

export PATH="$HOME/.local/venv/clawctl/bin:$PATH"

echo "1. Checking Tailscale socket..."
TAILSCALE_SOCKET="/var/run/tailscale/tailscaled.sock"
if [ -S "$TAILSCALE_SOCKET" ]; then
    echo "   ✓ Socket exists and is a socket"
    ls -l "$TAILSCALE_SOCKET"
else
    echo "   ✗ Socket not found or not a socket"
    ls -la /var/run/tailscale/ 2>/dev/null || echo "   Directory doesn't exist"
fi

echo ""
echo "2. Testing Python detection..."
python3 << PYTHON_TEST
import os
from pathlib import Path

# Simulate the detection logic
tailscale_socket = Path("/var/run/tailscale/tailscaled.sock")
print(f"Socket path: {tailscale_socket}")
print(f"Exists: {tailscale_socket.exists()}")
if tailscale_socket.exists():
    print(f"Is socket: {tailscale_socket.is_socket()}")
    print(f"Stat: {tailscale_socket.stat()}")

# Check environment
tailscale_enabled = os.getenv("TAILSCALE_ENABLED", "")
print(f"\nTAILSCALE_ENABLED env var: '{tailscale_enabled}'")

# Run the actual check
if tailscale_enabled.lower() in ("false", "0", "no"):
    result = False
    print("Result: False (explicitly disabled)")
else:
    if tailscale_socket.exists() and tailscale_socket.is_socket():
        result = True
        print("Result: True (Tailscale available)")
    else:
        result = False
        print("Result: False (Tailscale not available)")

print(f"\nFinal result: {result}")
PYTHON_TEST

echo ""
echo "3. Testing config generation directly..."
python3 << PYTHON_GEN
import sys
sys.path.insert(0, "$REMOTE_REPO_PATH/src")

from clawlib.core.openclaw_config import _is_tailscale_available

result = _is_tailscale_available()
print(f"   _is_tailscale_available() returns: {result}")

if result:
    print("   ✓ Tailscale Serve should be enabled")
else:
    print("   ⚠ Tailscale Serve will NOT be enabled")
PYTHON_GEN

echo ""
echo "4. Checking actual config file..."
USERNAME="alice"
CONFIG_FILE="$HOME/data/users/$USERNAME/openclaw/openclaw.json"
if [ -f "$CONFIG_FILE" ]; then
    echo "   Current config:"
    python3 << PYTHON_CHECK
import json
from pathlib import Path

config_file = Path("$CONFIG_FILE")
config = json.loads(config_file.read_text())

gateway = config.get("gateway", {})
print(f"   bind: {gateway.get('bind', 'not set')}")
print(f"   tailscale: {gateway.get('tailscale', {})}")
PYTHON_CHECK
else
    echo "   Config file not found: $CONFIG_FILE"
fi

SSH_EOF

echo ""
echo "=========================================="
echo "Debug Complete"
echo "=========================================="
