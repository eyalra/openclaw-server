#!/bin/bash
# reset-web-password.sh - Reset web interface password and verify it works

set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/load-config.sh"

echo "=========================================="
echo "Reset Web Interface Password"
echo "=========================================="
echo ""
echo "This will reset the admin password for the web interface."
echo "Username: admin (default)"
echo ""
echo "Target server: $SSH_USER@$LIGHTSAIL_IP:$SSH_PORT"
echo ""

# Prompt for password
read -sp "Enter new admin password: " PASSWORD
echo ""
read -sp "Confirm password: " PASSWORD_CONFIRM
echo ""

if [ "$PASSWORD" != "$PASSWORD_CONFIRM" ]; then
    echo "✗ Passwords do not match!"
    exit 1
fi

if [ -z "$PASSWORD" ]; then
    echo "✗ Password cannot be empty!"
    exit 1
fi

echo ""
echo "Resetting password on server..."

ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" bash << EOF
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

PASSWORD_DIR="\${DATA_ROOT}/secrets/web_admin"
PASSWORD_FILE="\${PASSWORD_DIR}/password"

echo "Data root: \$DATA_ROOT"
echo "Password file: \$PASSWORD_FILE"

# Remove old password file if it exists
if [ -f "\$PASSWORD_FILE" ]; then
    echo "Removing old password file..."
    rm -f "\$PASSWORD_FILE"
fi

# Create directory
mkdir -p "\$PASSWORD_DIR"

# Set password using clawctl (preferred method)
echo "Setting password with clawctl..."
if clawctl web set-password --config "\$REMOTE_REPO_PATH/clawctl.toml" --password "$PASSWORD" 2>&1; then
    echo "✓ Password set successfully with clawctl"
else
    echo "⚠ clawctl failed, using fallback method..."
    
    # Fallback: create password file directly using Python
    python3 << PYTHON_HASH
import bcrypt
import sys
from pathlib import Path

password = "$PASSWORD"
password_dir = Path("$PASSWORD_DIR")
password_file = password_dir / "password"

# Create directory if needed
password_dir.mkdir(parents=True, exist_ok=True)

# Hash password
hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())

# Write as binary
password_file.write_bytes(hashed)
password_file.chmod(0o600)

print(f"✓ Password set using fallback method")
print(f"  File: {password_file}")
print(f"  Size: {len(hashed)} bytes")
print(f"  Hash prefix: {hashed[:7].decode('utf-8')}")
PYTHON_HASH
    
    if [ -f "\$PASSWORD_FILE" ]; then
        echo "✓ Password file created"
    else
        echo "✗ Failed to create password file"
        exit 1
    fi
fi

# Verify the password file
echo ""
echo "Verifying password file..."
if [ -f "\$PASSWORD_FILE" ]; then
    FILE_SIZE=\$(stat -c%s "\$PASSWORD_FILE" 2>/dev/null || stat -f%z "\$PASSWORD_FILE" 2>/dev/null)
    PERMS=\$(stat -c%a "\$PASSWORD_FILE" 2>/dev/null || stat -f%OLp "\$PASSWORD_FILE" 2>/dev/null)
    echo "  ✓ File exists"
    echo "  Size: \$FILE_SIZE bytes"
    echo "  Permissions: \$PERMS"
    
    # Check hash format
    if head -c 2 "\$PASSWORD_FILE" 2>/dev/null | grep -q '\$2'; then
        HASH_PREFIX=\$(head -c 7 "\$PASSWORD_FILE" 2>/dev/null)
        echo "  ✓ Valid bcrypt hash prefix: \$HASH_PREFIX"
    else
        echo "  ✗ WARNING: Invalid hash format!"
        exit 1
    fi
    
    # Test password verification
    echo ""
    echo "Testing password verification..."
    python3 << PYTHON_TEST
import bcrypt
from pathlib import Path

password_file = Path("$PASSWORD_FILE")
stored_hash = password_file.read_bytes()
test_password = "$PASSWORD"

try:
    result = bcrypt.checkpw(test_password.encode("utf-8"), stored_hash)
    if result:
        print("  ✓ Password verification successful!")
    else:
        print("  ✗ Password verification failed!")
        exit(1)
except Exception as e:
    print(f"  ✗ Error during verification: {e}")
    exit(1)
PYTHON_TEST
    
    if [ \$? -eq 0 ]; then
        echo ""
        echo "✓ Password reset and verified successfully!"
    else
        echo ""
        echo "✗ Password verification failed!"
        exit 1
    fi
else
    echo "  ✗ Password file does not exist!"
    exit 1
fi

# Restart service if running
echo ""
if systemctl is-active --quiet clawctl-web 2>/dev/null; then
    echo "Restarting web service..."
    sudo systemctl restart clawctl-web.service
    sleep 2
    
    if systemctl is-active --quiet clawctl-web 2>/dev/null; then
        echo "✓ Service restarted successfully"
    else
        echo "⚠ Service may not be running - check logs: sudo journalctl -u clawctl-web"
    fi
else
    echo "Service is not running (start it with: sudo systemctl start clawctl-web)"
fi

EOF

echo ""
echo "=========================================="
echo "Password Reset Complete"
echo "=========================================="
echo ""
echo "You can now log in to the web interface with:"
echo "  Username: admin"
echo "  Password: (the password you just set)"
echo ""
