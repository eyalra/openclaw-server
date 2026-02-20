#!/bin/bash
# 01-harden-server.sh
# Server hardening: SSH configuration, firewall, non-root user
# Based on: https://dev.to/aws-builders/deploy-your-own-247-ai-agent-on-aws-ec2-with-docker-tailscale-the-secure-way-53aa

set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/scripts/load-config.sh"

echo "=========================================="
echo "OpenClaw Server Hardening"
echo "=========================================="
echo ""
echo "This script will:"
echo "  1. Update system packages"
echo "  2. Create non-root user 'openclaw'"
echo "  3. Configure SSH (port 2222, key-only)"
echo "  4. Configure UFW firewall"
echo ""
echo "Target server: $SSH_USER@$LIGHTSAIL_IP:$SSH_PORT"
echo ""

# Confirm before proceeding
read -p "Continue with server hardening? (yes/no): " confirm
if [ "$confirm" != "yes" ]; then
    echo "Aborted."
    exit 1
fi

echo ""
echo "Connecting to server..."

# Execute hardening steps on remote server
ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" << 'REMOTE_SCRIPT'
set -e

echo "Step 1: Updating system packages..."
sudo apt update && sudo apt upgrade -y

echo ""
echo "Step 2: Creating non-root user 'openclaw'..."
if id "openclaw" &>/dev/null; then
    echo "  User 'openclaw' already exists, skipping creation"
else
    sudo adduser --disabled-password --gecos "" openclaw
    echo "  User 'openclaw' created"
fi

# Grant sudo rights
sudo usermod -aG sudo openclaw
echo "  Sudo rights granted"

# Configure passwordless sudo for openclaw (service account)
echo "openclaw ALL=(ALL) NOPASSWD: ALL" | sudo tee /etc/sudoers.d/openclaw-nopasswd > /dev/null
sudo chmod 440 /etc/sudoers.d/openclaw-nopasswd
echo "  Passwordless sudo configured"

echo ""
echo "Step 3: Setting up SSH keys for new user..."
# Create SSH directory
sudo mkdir -p /home/openclaw/.ssh

# Copy authorized keys from ubuntu user
if [ -f /home/ubuntu/.ssh/authorized_keys ]; then
    sudo cp /home/ubuntu/.ssh/authorized_keys /home/openclaw/.ssh/
    echo "  SSH keys copied"
else
    echo "  Warning: No authorized_keys found for ubuntu user"
fi

# Fix permissions (CRITICAL)
sudo chown -R openclaw:openclaw /home/openclaw/.ssh
sudo chmod 700 /home/openclaw/.ssh
sudo chmod 600 /home/openclaw/.ssh/authorized_keys
echo "  Permissions set correctly"

echo ""
echo "Step 4: Configuring SSH..."
# Backup original config
sudo cp /etc/ssh/sshd_config /etc/ssh/sshd_config.backup

# Configure SSH - be careful not to break the connection!
# First, test the config before applying changes
sudo cp /etc/ssh/sshd_config /etc/ssh/sshd_config.new

# Remove all existing Port lines (commented and uncommented) to avoid duplicates
sudo sed -i '/^#*Port /d' /etc/ssh/sshd_config.new

# Remove all existing PermitRootLogin lines
sudo sed -i '/^#*PermitRootLogin /d' /etc/ssh/sshd_config.new

# Remove all existing PasswordAuthentication lines
sudo sed -i '/^#*PasswordAuthentication /d' /etc/ssh/sshd_config.new

# Remove all existing PubkeyAuthentication lines
sudo sed -i '/^#*PubkeyAuthentication /d' /etc/ssh/sshd_config.new

# Add the new settings after the first non-comment line (usually after a comment block)
# Find a good insertion point (after any initial comments, before Match blocks)
INSERT_LINE=$(grep -n "^[^#]" /etc/ssh/sshd_config.new | head -1 | cut -d: -f1)
if [ -z "$INSERT_LINE" ]; then
    INSERT_LINE=1
fi

# Insert the new settings
sudo sed -i "${INSERT_LINE}a\\
Port 2222\\
PermitRootLogin no\\
PasswordAuthentication no\\
PubkeyAuthentication yes" /etc/ssh/sshd_config.new

# Test SSH configuration before applying
if sudo sshd -t -f /etc/ssh/sshd_config.new; then
    # Config is valid, apply it
    sudo mv /etc/ssh/sshd_config.new /etc/ssh/sshd_config
    echo "  SSH configuration updated and validated"
else
    echo "  ERROR: SSH configuration test failed! Restoring backup..."
    sudo cp /etc/ssh/sshd_config.backup /etc/ssh/sshd_config
    exit 1
fi

echo ""
echo "Step 5: Disabling systemd socket activation (Ubuntu 24.04)..."
# Stop and disable socket listener
sudo systemctl stop ssh.socket 2>/dev/null || true
sudo systemctl disable ssh.socket 2>/dev/null || true
echo "  Socket activation disabled"

echo ""
echo "Step 6: Configuring UFW firewall..."
# Set default policies
sudo ufw --force reset
sudo ufw default deny incoming
sudo ufw default allow outgoing

# Allow current SSH port (safety net)
sudo ufw allow 22/tcp comment 'SSH - temporary, remove after testing port 2222'

# Allow new SSH port
sudo ufw allow 2222/tcp comment 'SSH - hardened port'

# Allow Tailscale network
sudo ufw allow from 100.64.0.0/10 comment 'Tailscale network'

# Enable firewall
echo "y" | sudo ufw enable
echo "  Firewall configured"

echo ""
echo "Step 7: Restarting SSH service..."
# Use the correct service name for Ubuntu
if sudo systemctl restart ssh; then
    echo "  SSH service restarted"
    # Wait a moment for SSH to start
    sleep 3
    # Verify SSH is running
    if sudo systemctl is-active --quiet ssh; then
        echo "  ✓ SSH service is running"
    else
        echo "  ⚠ Warning: SSH service may not be running"
        echo "    Status: $(sudo systemctl status ssh --no-pager -l | head -3)"
    fi
else
    echo "  ERROR: Failed to restart SSH service!"
    echo "    Attempting to start SSH..."
    sudo systemctl start ssh || {
        echo "    CRITICAL: Cannot start SSH service!"
        echo "    Restoring SSH config backup..."
        sudo cp /etc/ssh/sshd_config.backup /etc/ssh/sshd_config
        sudo systemctl start ssh
    }
fi

echo ""
echo "Step 8: Verifying SSH port change..."
sleep 2
# Check what port SSH is actually listening on
SSH_PORT=$(sudo ss -tulpn | grep -E 'sshd|ssh' | grep LISTEN | grep -oP ':\K[0-9]+' | head -1)
if [ -n "$SSH_PORT" ]; then
    if [ "$SSH_PORT" = "2222" ]; then
        echo "  ✓ SSH is now listening on port 2222"
    else
        echo "  ⚠ Warning: SSH is listening on port $SSH_PORT (expected 2222)"
        echo "    Check manually: sudo ss -tulpn | grep ssh"
    fi
else
    echo "  ⚠ Warning: Could not determine SSH listening port"
    echo "    Check manually: sudo ss -tulpn | grep ssh"
fi

echo ""
echo "=========================================="
echo "Server hardening complete!"
echo "=========================================="
echo ""
echo "IMPORTANT: Test SSH connection on new port before closing this session!"
echo ""
echo "Test command:"
echo "  ssh -p 2222 -i <your-key.pem> openclaw@$LIGHTSAIL_IP"
echo ""
echo "If connection works:"
echo "  1. Remove port 22 from Lightsail firewall (Lightsail Console → Networking)"
echo "  2. Remove port 22 from UFW: sudo ufw delete allow 22/tcp"
echo "  3. Update .lightsail-config: SSH_PORT=\"2222\" and SSH_USER=\"openclaw\""
REMOTE_SCRIPT

echo ""
echo "=========================================="
echo "Hardening script completed on server"
echo "=========================================="
echo ""
echo "NEXT STEPS:"
echo "  1. Test SSH connection on port 2222:"
echo "     ssh -p 2222 -i $SSH_KEY openclaw@$LIGHTSAIL_IP"
echo ""
echo "  2. If successful, update .lightsail-config:"
echo "     SSH_PORT=\"2222\""
echo "     SSH_USER=\"openclaw\""
echo ""
echo "  3. Remove port 22 from Lightsail firewall (Lightsail Console)"
echo ""
echo "  4. Then run: 02-install-dependencies.sh"
