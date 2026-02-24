#!/bin/bash
# trace-config-generation.sh - Trace why config generation isn't working

set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/load-config.sh"

ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" bash << 'SSH_EOF'
set -e

REMOTE_REPO_PATH="${REMOTE_REPO_PATH:-/home/openclaw/openclaw}"
cd "$REMOTE_REPO_PATH"

export PATH="$HOME/.local/venv/clawctl/bin:$PATH"
CLAWCTL_CMD="$(command -v clawctl || echo '$HOME/.local/venv/clawctl/bin/clawctl')"

echo "1. Checking clawctl Python environment..."
"$CLAWCTL_CMD" --version || true
PYTHON_USED=$("$CLAWCTL_CMD" --help 2>&1 | head -1 || echo "")
echo "   Command: $CLAWCTL_CMD"

# Check what Python clawctl uses
if [ -f "$CLAWCTL_CMD" ]; then
    CLAWCTL_PYTHON=$(head -1 "$CLAWCTL_CMD" | sed 's/^#!//' | tr -d ' ')
    echo "   Python: $CLAWCTL_PYTHON"
fi

echo ""
echo "2. Testing import path..."
"$CLAWCTL_PYTHON" << PYTHON_TRACE
import sys
import os
from pathlib import Path

print(f"Python executable: {sys.executable}")
print(f"Python path: {sys.path[:3]}")

# Add src to path
sys.path.insert(0, "$REMOTE_REPO_PATH/src")

# Clear environment
if "TAILSCALE_ENABLED" in os.environ:
    del os.environ["TAILSCALE_ENABLED"]

print(f"\nTesting Tailscale detection...")
from clawlib.core.openclaw_config import _is_tailscale_available

result = _is_tailscale_available()
print(f"_is_tailscale_available() = {result}")

# Check socket directly
socket_path = Path("/var/run/tailscale/tailscaled.sock")
print(f"\nSocket check:")
print(f"  Path: {socket_path}")
print(f"  Exists: {socket_path.exists()}")
if socket_path.exists():
    print(f"  Is socket: {socket_path.is_socket()}")
    print(f"  Stat: {socket_path.stat()}")

# Check environment
print(f"\nEnvironment:")
print(f"  TAILSCALE_ENABLED: {os.getenv('TAILSCALE_ENABLED', 'not set')}")
PYTHON_TRACE

echo ""
echo "3. Testing actual config regeneration with Python trace..."
"$CLAWCTL_PYTHON" << PYTHON_REGEN
import sys
import os
from pathlib import Path

sys.path.insert(0, "$REMOTE_REPO_PATH/src")

# Clear environment
if "TAILSCALE_ENABLED" in os.environ:
    del os.environ["TAILSCALE_ENABLED"]

from clawlib.core.config import load_config
from clawlib.core.openclaw_config import generate_openclaw_config, write_openclaw_config
from clawlib.core.paths import Paths
from clawlib.core.secrets import SecretsManager
from clawlib.core.user_manager import GATEWAY_TOKEN_SECRET_NAME

cfg = load_config(Path("$REMOTE_REPO_PATH/clawctl.toml"))
user = cfg.get_user("alice")

if not user:
    print("User 'alice' not found")
    sys.exit(1)

paths = Paths(cfg.clawctl.data_root, cfg.clawctl.build_root)
secrets_mgr = SecretsManager(paths)

gateway_token = secrets_mgr.read_secret("alice", GATEWAY_TOKEN_SECRET_NAME)
if not gateway_token:
    import secrets as secrets_module
    gateway_token = secrets_module.token_urlsafe(32)
    secrets_mgr.write_secret("alice", GATEWAY_TOKEN_SECRET_NAME, gateway_token)

print("Generating config...")
config = generate_openclaw_config(user, cfg.clawctl.defaults, gateway_token=gateway_token)

gateway = config.get("gateway", {})
bind = gateway.get("bind", "")
tailscale_mode = gateway.get("tailscale", {}).get("mode", "")

print(f"\nGenerated config:")
print(f"  bind: {bind}")
print(f"  tailscale.mode: {tailscale_mode}")

if bind == "loopback" and tailscale_mode == "serve":
    print("\n✓ Config generation works!")
    
    # Write it
    config_path = paths.user_openclaw_config("alice")
    write_openclaw_config(user, cfg.clawctl.defaults, config_path, gateway_token=gateway_token)
    print(f"✓ Config written to {config_path}")
else:
    print(f"\n✗ Config generation failed!")
    print(f"  Expected: bind=loopback, tailscale.mode=serve")
    print(f"  Got: bind={bind}, tailscale.mode={tailscale_mode}")
    sys.exit(1)
PYTHON_REGEN

echo ""
echo "4. Verifying written config..."
CONFIG_FILE="$HOME/data/users/alice/openclaw/openclaw.json"
python3 << PYTHON_CHECK
import json
from pathlib import Path

config_file = Path("$CONFIG_FILE")
config = json.loads(config_file.read_text())

gateway = config.get("gateway", {})
bind = gateway.get("bind", "")
tailscale_mode = gateway.get("tailscale", {}).get("mode", "")

print(f"Config file contents:")
print(f"  bind: {bind}")
print(f"  tailscale.mode: {tailscale_mode}")

if bind == "loopback" and tailscale_mode == "serve":
    print("\n✓ Config is correct!")
else:
    print(f"\n✗ Config is still wrong!")
PYTHON_CHECK

SSH_EOF
