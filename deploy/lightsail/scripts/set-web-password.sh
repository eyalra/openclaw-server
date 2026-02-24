#!/bin/bash
# set-web-password.sh - Set web interface admin password using clawctl

set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/load-config.sh"

echo "=========================================="
echo "Set Web Interface Password"
echo "=========================================="
echo ""
echo "This will set the admin password for the web interface."
echo "Username: admin (default)"
echo ""
echo "Target server: $SSH_USER@$LIGHTSAIL_IP:$SSH_PORT"
echo ""

# Prompt for password
read -sp "Enter admin password: " PASSWORD
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
echo "Setting password on server..."

ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" bash << EOF
set -e

REMOTE_REPO_PATH="$REMOTE_REPO_PATH"
cd "\$REMOTE_REPO_PATH"

# Ensure PATH includes venv bin
export PATH="\$HOME/.local/venv/clawctl/bin:\$PATH"

# Use clawctl to set password
clawctl web set-password --config "\$REMOTE_REPO_PATH/clawctl.toml" --password "$PASSWORD" || {
    echo "⚠ Failed to set password with clawctl, trying fallback method..."
    
    # Fallback: create password file directly
    # Get data_root from config or use default
    DATA_ROOT="\$(grep -E "^\s*data_root\s*=\s*" "\$REMOTE_REPO_PATH/clawctl.toml" | head -1 | grep -oE '"[^"]+"' | tr -d '"' || echo "\$HOME/data")"
    PASSWORD_DIR="\${DATA_ROOT}/secrets/web_admin"
    mkdir -p "\$PASSWORD_DIR"
    
    # Hash password using Python (bcrypt returns bytes, not a string)
    python3 << PYTHON_HASH
import bcrypt
import sys

password = "$PASSWORD"
hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())

with open("$PASSWORD_DIR/password", "wb") as f:
    f.write(hashed)
PYTHON_HASH
    chmod 600 "\$PASSWORD_DIR/password"
    echo "✓ Password set using fallback method"
    echo "  Password file: \$PASSWORD_DIR/password"
}

echo ""
echo "Password has been set as a secret file."
echo "Username: admin"
echo "Password: (the one you just set)"
EOF

echo ""
echo "=========================================="
echo "Password Set Successfully"
echo "=========================================="
echo ""
echo "You can now log in to the web interface with:"
echo "  Username: admin"
echo "  Password: (the password you just set)"
echo ""
echo "The password is stored as a secret file at:"
echo "  ~/data/secrets/web_admin/password"
echo ""
