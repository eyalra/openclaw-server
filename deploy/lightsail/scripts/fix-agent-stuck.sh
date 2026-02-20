#!/bin/bash
# Fix agent stuck issues by:
# 1. Fixing permissions
# 2. Regenerating config with correct model
# 3. Running openclaw doctor --fix
# 4. Restarting container

set -e

source "$(dirname "$0")/load-config.sh"

USERNAME="${1:-alice}"

echo "=========================================="
echo "Fixing stuck agent for: $USERNAME"
echo "=========================================="

ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" <<EOF
set -e

# Fix permissions
echo "1. Fixing permissions..."
sudo chown -R 1000:1000 /home/openclaw/data/users/$USERNAME/openclaw
sudo chmod -R 775 /home/openclaw/data/users/$USERNAME/openclaw
echo "  ✓ Permissions fixed"

# Regenerate config
echo ""
echo "2. Regenerating config..."
export PATH=~/.local/bin:~/.local/venv/clawctl/bin:\$PATH
cd ~/openclaw
clawctl config regenerate $USERNAME --config clawctl.toml || {
    echo "  ⚠ Config regeneration failed, but continuing..."
}

# Run openclaw doctor --fix inside container
echo ""
echo "3. Running openclaw doctor --fix..."
docker exec openclaw-$USERNAME openclaw doctor --fix 2>&1 || {
    echo "  ⚠ Doctor fix had issues, but continuing..."
}

# Restart container
echo ""
echo "4. Restarting container..."
docker restart openclaw-$USERNAME
sleep 5

# Check status
echo ""
echo "5. Checking status..."
docker logs --tail 20 openclaw-$USERNAME 2>&1 | grep -E '(gateway|agent|model|error|Error|listening)' | tail -10 || true

echo ""
echo "=========================================="
echo "Fix complete!"
echo "=========================================="
EOF
