#!/bin/bash
# debug-web-auth.sh - Debug web interface authentication issues

set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/load-config.sh"

echo "=========================================="
echo "Debug Web Interface Authentication"
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

echo "1. Checking password file..."
if [ -f "$PASSWORD_FILE" ]; then
    echo "  ✓ Password file exists: $PASSWORD_FILE"
    echo "  Size: $(stat -c%s "$PASSWORD_FILE" 2>/dev/null || stat -f%z "$PASSWORD_FILE" 2>/dev/null) bytes"
    echo "  Permissions: $(stat -c%a "$PASSWORD_FILE" 2>/dev/null || stat -f%OLp "$PASSWORD_FILE" 2>/dev/null)"
    echo "  Owner: $(stat -c%U "$PASSWORD_FILE" 2>/dev/null || stat -f%Su "$PASSWORD_FILE" 2>/dev/null)"
    
    # Check first few bytes
    FIRST_BYTES=$(head -c 10 "$PASSWORD_FILE" 2>/dev/null | od -An -tx1 | tr -d ' \n')
    echo "  First 10 bytes (hex): $FIRST_BYTES"
    
    # Check if it starts with $2
    if head -c 2 "$PASSWORD_FILE" 2>/dev/null | grep -q '\$2'; then
        echo "  ✓ Starts with bcrypt prefix"
        HASH_PREFIX=$(head -c 7 "$PASSWORD_FILE" 2>/dev/null)
        echo "  Hash prefix: $HASH_PREFIX"
    else
        echo "  ✗ WARNING: Does not start with bcrypt prefix (\$2a, \$2b, or \$2y)"
    fi
else
    echo "  ✗ Password file does not exist!"
fi

echo ""
echo "2. Testing password file with Python..."
if command -v python3 >/dev/null 2>&1; then
    python3 << 'PYTHON_TEST'
import sys
from pathlib import Path

password_file = Path("$PASSWORD_FILE")

if password_file.exists():
    try:
        stored_hash = password_file.read_bytes()
        print(f"  ✓ Read {len(stored_hash)} bytes")
        
        # Check format
        if stored_hash.startswith(b"$2"):
            print(f"  ✓ Valid bcrypt prefix: {stored_hash[:7].decode('utf-8', errors='ignore')}")
        else:
            print(f"  ✗ Invalid prefix. First 20 bytes: {stored_hash[:20]}")
            sys.exit(1)
        
        # Try to import bcrypt
        try:
            import bcrypt
            print("  ✓ bcrypt module available")
            
            # Test with dummy password (will fail but tests hash validity)
            try:
                bcrypt.checkpw(b"dummy_test_password", stored_hash)
                print("  ⚠ Unexpected: dummy password matched (hash might be corrupted)")
            except ValueError as e:
                print(f"  ✗ Hash format error: {e}")
                sys.exit(1)
            except Exception as e:
                # Expected - dummy password doesn't match
                if "Invalid" in str(e) or "Invalid" in str(type(e)):
                    print("  ✓ Hash format is valid (bcrypt accepted it)")
                else:
                    print(f"  ✓ Hash format valid (expected error with dummy password)")
        except ImportError:
            print("  ✗ bcrypt module not available")
            sys.exit(1)
    except Exception as e:
        print(f"  ✗ Error reading file: {e}")
        sys.exit(1)
else:
    print("  ⚠ python3 not available")
PYTHON_TEST
else
    echo "  ⚠ python3 not available"
fi

echo ""
echo "3. Checking service logs (last 20 lines)..."
if systemctl is-active --quiet clawctl-web 2>/dev/null; then
    echo "  Service is running"
    echo ""
    echo "  Recent log entries:"
    sudo journalctl -u clawctl-web -n 20 --no-pager | tail -20 || echo "  (Could not read logs)"
else
    echo "  ⚠ Service is not running"
fi

echo ""
echo "4. Environment variables..."
if [ -n "${WEB_ADMIN_PASSWORD:-}" ]; then
    echo "  WEB_ADMIN_PASSWORD is set (length: ${#WEB_ADMIN_PASSWORD} chars)"
else
    echo "  WEB_ADMIN_PASSWORD is not set"
fi

echo ""
echo "5. Testing authentication manually..."
echo "  To test authentication, try:"
echo "    curl -u admin:YOUR_PASSWORD http://localhost:9000/api/system/config"
echo ""
echo "  Or check logs with debug enabled:"
echo "    sudo systemctl stop clawctl-web"
echo "    cd $REMOTE_REPO_PATH"
echo "    WEB_DEBUG=true ~/.local/venv/clawctl/bin/python -m clawctl_web.server $REMOTE_REPO_PATH/clawctl.toml"

EOF

echo ""
echo "=========================================="
echo "Debug Complete"
echo "=========================================="
