#!/bin/bash
# 00-prepare-ssh.sh
# Prepare SSH access on fresh Ubuntu server
# Ensures SSH is accessible on port 22 before hardening

set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/scripts/load-config.sh"

echo "=========================================="
echo "Prepare SSH Access"
echo "=========================================="
echo ""
echo "This script ensures SSH is ready on port 22"
echo "before running the hardening script."
echo ""
echo "Target server: $SSH_USER@$LIGHTSAIL_IP"
echo ""

# Force port 22 for initial connection
INITIAL_PORT="22"
if [ "$SSH_PORT" != "22" ]; then
    echo "⚠ Config has SSH_PORT=$SSH_PORT, but connecting on port 22 initially"
    echo "  (Hardening script will change it to 2222)"
fi

# Test connection on port 22
echo "Testing SSH connection on port 22..."
if ssh -p "$INITIAL_PORT" -i "$SSH_KEY" -o ConnectTimeout=10 -o StrictHostKeyChecking=no "$SSH_USER@$LIGHTSAIL_IP" "echo 'SSH connection successful'" 2>&1; then
    echo "✓ SSH connection works on port 22"
else
    echo "✗ Cannot connect to server on port 22"
    echo ""
    echo "Troubleshooting:"
    echo "  1. Verify instance is running in Lightsail console"
    echo "  2. Check firewall rule for port 22 exists"
    echo "  3. Verify SSH key path: $SSH_KEY"
    echo "  4. Check key permissions: chmod 600 $SSH_KEY"
    echo "  5. Verify IP address: $LIGHTSAIL_IP"
    exit 1
fi

echo ""
echo "Ensuring SSH service is running..."
ssh -p "$INITIAL_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" << 'REMOTE_SCRIPT'
set -e

# Ensure SSH is running
if ! sudo systemctl is-active --quiet ssh; then
    echo "Starting SSH service..."
    sudo systemctl start ssh
fi

# Verify SSH is listening on port 22
if sudo ss -tulpn | grep -q ':22.*LISTEN'; then
    echo "✓ SSH is listening on port 22"
else
    echo "⚠ Warning: SSH may not be listening on port 22"
    echo "  Checking SSH status..."
    sudo systemctl status ssh --no-pager -l | head -5
fi

# Ensure UFW allows port 22 (if UFW is enabled)
if sudo ufw status | grep -q "Status: active"; then
    if sudo ufw status | grep -q "22/tcp"; then
        echo "✓ UFW allows port 22"
    else
        echo "Adding UFW rule for port 22..."
        sudo ufw allow 22/tcp
    fi
else
    echo "✓ UFW is not active (default Ubuntu state)"
fi
REMOTE_SCRIPT

echo ""
echo "=========================================="
echo "SSH Preparation Complete"
echo "=========================================="
echo ""
echo "SSH is ready on port 22. You can now run:"
echo "  ./01-harden-server.sh"
echo ""
echo "The hardening script will:"
echo "  1. Connect on port 22"
echo "  2. Change SSH to port 2222"
echo "  3. Create 'openclaw' user"
echo "  4. Configure firewall"
