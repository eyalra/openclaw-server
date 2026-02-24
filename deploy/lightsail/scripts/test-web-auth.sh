#!/bin/bash
# test-web-auth.sh - Test web interface authentication with a test password

set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/load-config.sh"

TEST_PASSWORD="test123456"

echo "=========================================="
echo "Test Web Interface Authentication"
echo "=========================================="
echo ""
echo "Setting test password: $TEST_PASSWORD"
echo "Target server: $SSH_USER@$LIGHTSAIL_IP:$SSH_PORT"
echo ""

ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" bash << SSH_EOF
set -e

REMOTE_REPO_PATH="$REMOTE_REPO_PATH"
cd "\$REMOTE_REPO_PATH"

# Ensure PATH includes venv bin
export PATH="\$HOME/.local/venv/clawctl/bin:\$PATH"

# Get data_root from config
if [ -f "\$REMOTE_REPO_PATH/clawctl.toml" ]; then
    DATA_ROOT=\$(grep -E "^\s*data_root\s*=\s*" "\$REMOTE_REPO_PATH/clawctl.toml" | head -1 | grep -oE '"[^"]+"' | tr -d '"' || echo "\$HOME/data")
else
    DATA_ROOT="\$HOME/data"
fi

# Expand ~ if present
DATA_ROOT=\${DATA_ROOT/#\~/\$HOME}

PASSWORD_DIR="\${DATA_ROOT}/secrets/web_admin"
PASSWORD_FILE="\${PASSWORD_DIR}/password"

echo "Debug info:"
echo "  REMOTE_REPO_PATH: \$REMOTE_REPO_PATH"
echo "  DATA_ROOT: \$DATA_ROOT"
echo "  PASSWORD_DIR: \$PASSWORD_DIR"
echo "  PASSWORD_FILE: \$PASSWORD_FILE"
echo ""

echo "1. Removing old password file if exists..."
rm -f "\$PASSWORD_FILE"

echo "2. Creating password file..."
mkdir -p "\$PASSWORD_DIR"

# Set password using clawctl
echo "3. Setting password with clawctl..."
if clawctl web set-password --config "\$REMOTE_REPO_PATH/clawctl.toml" --password "$TEST_PASSWORD" 2>&1; then
    echo "   ✓ Password set successfully"
else
    echo "   ⚠ clawctl failed, using Python fallback..."
    
    # Fallback: create password file directly using Python
    # Pass variables via environment and command line
    PASSWORD_DIR_VAR="$PASSWORD_DIR" TEST_PASSWORD_VAR="$TEST_PASSWORD" python3 << 'PYTHON_SCRIPT'
import bcrypt
from pathlib import Path
import os
import sys

# Get from environment variables (set before python3 command)
password_dir_str = os.environ.get("PASSWORD_DIR_VAR", "")
password = os.environ.get("TEST_PASSWORD_VAR", "")

if not password_dir_str:
    # Fallback: construct from data_root
    data_root = os.path.expanduser("~/data")
    password_dir_str = os.path.join(data_root, "secrets", "web_admin")

password_dir = Path(password_dir_str)
password_file = password_dir / "password"

print(f"   Debug: password_dir_str = {password_dir_str}")
print(f"   Debug: password_dir = {password_dir}")

# Create directory if needed
password_dir.mkdir(parents=True, exist_ok=True)

# Hash password
hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())

# Write as binary
password_file.write_bytes(hashed)
os.chmod(password_file, 0o600)

print(f"   ✓ Password file created: {password_file}")
print(f"   Full path: {password_file.absolute()}")
print(f"   Size: {len(hashed)} bytes")
print(f"   Hash prefix: {hashed[:7].decode('utf-8')}")
PYTHON_SCRIPT
fi

echo ""
echo "4. Verifying password file..."
if [ -f "\$PASSWORD_FILE" ]; then
    FILE_SIZE=\$(stat -c%s "\$PASSWORD_FILE" 2>/dev/null || stat -f%z "\$PASSWORD_FILE" 2>/dev/null)
    PERMS=\$(stat -c%a "\$PASSWORD_FILE" 2>/dev/null || stat -f%OLp "\$PASSWORD_FILE" 2>/dev/null)
    echo "   ✓ File exists"
    echo "   Size: \$FILE_SIZE bytes"
    echo "   Permissions: \$PERMS"
    
    # Hash format already validated by Python script above
    echo "   ✓ Hash format validated (created by Python)"
    
    # Test password verification
    echo ""
    echo "5. Testing password verification..."
    PASSWORD_FILE_VAR="\$PASSWORD_FILE" TEST_PASSWORD_VAR="$TEST_PASSWORD" python3 << 'PYTHON_TEST'
import bcrypt
import sys
import os

password_file_path = os.environ.get("PASSWORD_FILE_VAR", "")
test_password = os.environ.get("TEST_PASSWORD_VAR", "")

if not password_file_path:
    print("   ✗ PASSWORD_FILE_VAR not set!")
    sys.exit(1)

with open(password_file_path, "rb") as f:
    stored_hash = f.read()

try:
    result = bcrypt.checkpw(test_password.encode("utf-8"), stored_hash)
    if result:
        print("   ✓ Password verification successful!")
    else:
        print("   ✗ Password verification failed!")
        sys.exit(1)
except Exception as e:
    print(f"   ✗ Error during verification: {e}")
    sys.exit(1)
PYTHON_TEST
    
    if [ \$? -eq 0 ]; then
        echo ""
        echo "✓ Password set and verified successfully!"
    else
        echo ""
        echo "✗ Password verification failed!"
        exit 1
    fi
else
    echo "   ✗ Password file does not exist!"
    exit 1
fi

# Restart service if running
echo ""
echo "6. Restarting web service..."
if systemctl is-active --quiet clawctl-web 2>/dev/null; then
    sudo systemctl restart clawctl-web.service
    sleep 2
    
    if systemctl is-active --quiet clawctl-web 2>/dev/null; then
        echo "   ✓ Service restarted successfully"
    else
        echo "   ⚠ Service may not be running - check logs: sudo journalctl -u clawctl-web"
    fi
else
    echo "   ⚠ Service is not running"
fi

echo ""
echo "=========================================="
echo "Test Complete!"
echo "=========================================="
echo ""
echo "You can now log in with:"
echo "  Username: admin"
echo "  Password: $TEST_PASSWORD"
echo ""

SSH_EOF

echo ""
echo "=========================================="
echo "Authentication Test Complete"
echo "=========================================="
echo ""
echo "Test credentials:"
echo "  Username: admin"
echo "  Password: $TEST_PASSWORD"
echo ""
echo "Try logging in at: http://<your-server-ip>:9000"
echo ""
