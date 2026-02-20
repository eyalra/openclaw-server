#!/bin/bash
# 02-install-dependencies.sh
# Install Docker, Tailscale, AWS CLI, and other dependencies

set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/scripts/load-config.sh"

echo "=========================================="
echo "Installing Dependencies"
echo "=========================================="
echo ""
echo "This script will install:"
echo "  1. Docker and Docker Compose"
echo "  2. Tailscale"
echo "  3. AWS CLI"
echo "  4. Git and utilities"
echo ""
echo "Target server: $SSH_USER@$LIGHTSAIL_IP:$SSH_PORT"
echo ""

# Confirm before proceeding
read -p "Continue with dependency installation? (yes/no): " confirm
if [ "$confirm" != "yes" ]; then
    echo "Aborted."
    exit 1
fi

echo ""
echo "Connecting to server..."

# Execute installation on remote server
ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" << 'REMOTE_SCRIPT'
set -e

echo "Step 1: Installing Docker dependencies..."
sudo apt update
sudo apt install -y apt-transport-https ca-certificates curl software-properties-common

echo ""
echo "Step 2: Adding Docker repository..."
# Add Docker GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Add Docker repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

echo ""
echo "Step 3: Installing Docker..."
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo ""
echo "Step 4: Adding user to docker group..."
sudo usermod -aG docker openclaw
echo "  User 'openclaw' added to docker group"

echo ""
echo "Step 5: Installing Tailscale..."
curl -fsSL https://tailscale.com/install.sh | sh

echo ""
echo "Step 6: Installing AWS CLI..."
# Install AWS CLI v2
cd /tmp
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
sudo apt install -y unzip
unzip -q awscliv2.zip
sudo ./aws/install
rm -rf aws awscliv2.zip

echo ""
echo "Step 7: Installing additional utilities..."
sudo apt install -y git curl wget jq

echo ""
echo "Step 8: Verifying installations..."
echo "  Docker version:"
docker --version || echo "    ⚠ Docker not available (may need logout/login)"
echo "  Tailscale version:"
tailscale version || echo "    ⚠ Tailscale not available"
echo "  AWS CLI version:"
aws --version || echo "    ⚠ AWS CLI not available"
echo "  Git version:"
git --version

echo ""
echo "=========================================="
echo "Dependency installation complete!"
echo "=========================================="
echo ""
echo "IMPORTANT: Tailscale authentication required!"
echo ""
echo "Run on server:"
echo "  sudo tailscale up"
echo ""
echo "Follow the authentication URL in your browser."
echo "After authentication, get Tailscale IP:"
echo "  tailscale ip -4"
echo ""
echo "Then update .lightsail-config with TAILSCALE_IP"
echo ""
echo "NEXT STEPS:"
echo "  1. Authenticate Tailscale (see SOP-03)"
echo "  2. Run: 03-deploy-openclaw.sh"
REMOTE_SCRIPT

echo ""
echo "=========================================="
echo "Installation script completed"
echo "=========================================="
echo ""
echo "To complete Tailscale setup, SSH to server and run:"
echo "  ssh -p $SSH_PORT -i $SSH_KEY $SSH_USER@$LIGHTSAIL_IP"
echo "  sudo tailscale up"
echo ""
echo "See docs/SOP-03-tailscale-setup.md for detailed instructions"
