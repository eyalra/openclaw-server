#!/bin/bash
# check-web-password.sh - Check web interface password file status

set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/load-config.sh"

echo "=========================================="
echo "Check Web Interface Password Status"
echo "=========================================="
echo ""
echo "Target server: $SSH_USER@$LIGHTSAIL_IP:$SSH_PORT"
echo ""

ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" bash << 'EOF'
set -e

REMOTE_REPO_PATH="${REMOTE_REPO_PATH:-/home/openclaw/openclaw}"
cd "$REMOTE_REPO_PATH"

# Get data_root from config
if [ -f "$REMOTE_REPO_PATH/clawctl.toml" ]; then
    DATA_ROOT=$(grep -E "^\s*data_root\s*=\s*" "$REMOTE_REPO_PATH/clawctl.toml" | head -1 | grep -oE '"[^"]+"' | tr -d '"' || echo "$HOME/data")
else
    DATA_ROOT="$HOME/data"
fi

PASSWORD_FILE="${DATA_ROOT}/secrets/web_admin/password"

echo "Configuration:"
echo "  Config file: $REMOTE_REPO_PATH/clawctl.toml"
echo "  Data root: $DATA_ROOT"
echo "  Password file: $PASSWORD_FILE"
echo ""

# Check if password file exists
if [ -f "$PASSWORD_FILE" ]; then
    echo "✓ Password file exists"
    echo "  File size: $(stat -c%s "$PASSWORD_FILE" 2>/dev/null || stat -f%z "$PASSWORD_FILE" 2>/dev/null) bytes"
    echo "  Permissions: $(stat -c%a "$PASSWORD_FILE" 2>/dev/null || stat -f%OLp "$PASSWORD_FILE" 2>/dev/null)"
    echo "  Owner: $(stat -c%U "$PASSWORD_FILE" 2>/dev/null || stat -f%Su "$PASSWORD_FILE" 2>/dev/null)"
    
    # Check if it's a valid bcrypt hash (starts with $2a$, $2b$, or $2y$)
    FIRST_BYTES=$(head -c 4 "$PASSWORD_FILE" 2>/dev/null || echo "")
    if echo "$FIRST_BYTES" | grep -qE '^\$2[aby]\$'; then
        echo "  ✓ Valid bcrypt hash format detected"
    else
        echo "  ⚠ WARNING: File doesn't appear to be a valid bcrypt hash!"
        echo "    First 20 bytes: $(head -c 20 "$PASSWORD_FILE" | od -An -tx1 | tr -d ' \n')"
    fi
    
    # Test if bcrypt can read it
    if command -v python3 >/dev/null 2>&1; then
        echo ""
        echo "Testing bcrypt compatibility..."
        python3 << PYTHON_TEST
import bcrypt
import sys

try:
    with open("$PASSWORD_FILE", "rb") as f:
        stored_hash = f.read()
    
    # Try to verify with a dummy password (will fail, but tests if hash is valid)
    try:
        bcrypt.checkpw(b"dummy", stored_hash)
        print("  ✓ Hash format is valid (verification test passed)")
    except ValueError as e:
        print(f"  ✗ Hash format error: {e}")
    except Exception as e:
        # This is expected - we're using a dummy password
        if "Invalid" in str(e) or "Invalid" in str(type(e)):
            print("  ✓ Hash format is valid (bcrypt accepted the hash)")
        else:
            print(f"  ⚠ Unexpected error: {e}")
except Exception as e:
    print(f"  ✗ Error reading/verifying hash: {e}")
    sys.exit(1)
PYTHON_TEST
    fi
else
    echo "  ⚠ python3 not available for hash validation"
fi
else
    echo "✗ Password file does not exist!"
    echo ""
    echo "To set the password, run:"
    echo "  ./deploy/lightsail/scripts/set-web-password.sh"
    echo ""
    echo "Or manually on the server:"
    echo "  clawctl web set-password --config $REMOTE_REPO_PATH/clawctl.toml"
fi

echo ""
echo "Environment check:"
if [ -n "${WEB_ADMIN_PASSWORD:-}" ]; then
    echo "  WEB_ADMIN_PASSWORD is set (will be used if password file doesn't exist)"
else
    echo "  WEB_ADMIN_PASSWORD is not set"
fi

echo ""
echo "Service status:"
if systemctl is-active --quiet clawctl-web 2>/dev/null; then
    echo "  ✓ clawctl-web service is running"
    echo "  Note: If you just set/changed the password, restart the service:"
    echo "    sudo systemctl restart clawctl-web"
else
    echo "  ⚠ clawctl-web service is not running (or systemctl not available)"
fi

EOF

echo ""
echo "=========================================="
echo "Check Complete"
echo "=========================================="
