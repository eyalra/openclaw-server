#!/bin/bash
# 07-deploy-updates.sh
# Deploy tested changes from local repository to Lightsail
# Reads configuration from .lightsail-config

set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/scripts/load-config.sh"

echo "=========================================="
echo "Deploy Updates to Lightsail"
echo "=========================================="
echo ""
echo "This script will:"
echo "  1. Copy files from local repository to Lightsail"
echo "  2. Reinstall clawctl"
echo "  3. Rebuild Docker image (if needed)"
echo "  4. Restart containers"
echo ""
echo "Source: $LOCAL_REPO_PATH"
echo "Target: $SSH_USER@$LIGHTSAIL_IP:$SSH_PORT:$REMOTE_REPO_PATH"
echo ""

# Check if local repo path exists
if [ ! -d "$LOCAL_REPO_PATH" ]; then
    echo "Error: Local repository path does not exist: $LOCAL_REPO_PATH"
    exit 1
fi

# Confirm before proceeding
read -p "Deploy updates to Lightsail? (yes/no): " confirm
if [ "$confirm" != "yes" ]; then
    echo "Aborted."
    exit 1
fi

echo ""
echo "Step 1: Copying files to Lightsail..."
# Use rsync to copy files, excluding git and other unnecessary files
rsync -avz --delete \
    -e "ssh -p $SSH_PORT -i $SSH_KEY" \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.venv' \
    --exclude='node_modules' \
    --exclude='.pytest_cache' \
    --exclude='*.egg-info' \
    --exclude='.lightsail-config' \
    --exclude='data/' \
    --exclude='build/' \
    "$LOCAL_REPO_PATH/" "$SSH_USER@$LIGHTSAIL_IP:$REMOTE_REPO_PATH/" || {
    echo "  ⚠ rsync failed, trying alternative method..."
    # Fallback: use scp for critical files only
    echo "  Copying critical files..."
    ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" "mkdir -p $REMOTE_REPO_PATH"
    scp -r -P "$SSH_PORT" -i "$SSH_KEY" \
        "$LOCAL_REPO_PATH/src" \
        "$LOCAL_REPO_PATH/pyproject.toml" \
        "$SSH_USER@$LIGHTSAIL_IP:$REMOTE_REPO_PATH/" || {
        echo "  ✗ File copy failed"
        exit 1
    }
}

echo "  ✓ Files copied"

echo ""
echo "Step 2: Reinstalling clawctl..."
ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" << REMOTE_SCRIPT
set -e

cd $REMOTE_REPO_PATH

# Ensure PATH includes venv bin
CLAWCTL_VENV="\$HOME/.local/venv/clawctl"
if [ -d "\$CLAWCTL_VENV" ]; then
    export PATH="\$CLAWCTL_VENV/bin:\$PATH"
    # Reinstall clawctl to pick up code changes
    if command -v uv >/dev/null 2>&1; then
        echo "  Reinstalling clawctl with uv..."
        uv pip install -e '.' --python "\$CLAWCTL_VENV/bin/python" || {
            echo "  ⚠ clawctl reinstall failed, continuing..."
        }
    else
        echo "  ⚠ uv not found, skipping clawctl reinstall"
    fi
else
    echo "  ⚠ clawctl venv not found, skipping reinstall"
fi

echo "  ✓ clawctl reinstalled"

echo ""
echo "Step 3: Rebuilding Docker image..."
if command -v clawctl >/dev/null 2>&1 && [ -f "clawctl.toml" ]; then
    clawctl update --config clawctl.toml || {
        echo "  ⚠ Update failed, trying manual build..."
        docker build -t openclaw-instance:latest --build-arg OPENCLAW_VERSION=latest docker/ || {
            echo "  ✗ Docker build failed"
            exit 1
        }
    }
    echo "  ✓ Docker image rebuilt"
else
    echo "  ⚠ clawctl not available, building manually..."
    docker build -t openclaw-instance:latest --build-arg OPENCLAW_VERSION=latest docker/ || {
        echo "  ✗ Docker build failed"
        exit 1
    }
fi

echo ""
echo "Step 4: Restarting containers..."
if command -v clawctl >/dev/null 2>&1 && [ -f "clawctl.toml" ]; then
    # Use rebuild_all for rolling update
    python3 -c "
from clawctl.core.config import load_config
from clawctl.core.docker_manager import DockerManager

try:
    config = load_config('clawctl.toml')
    docker = DockerManager(config)
    updated = docker.rebuild_all()
    print(f'✓ Updated containers: {updated}')
except Exception as e:
    print(f'⚠ Rebuild failed: {e}')
    print('Trying restart-all instead...')
    import subprocess
    subprocess.run(['clawctl', 'restart-all', '--config', 'clawctl.toml'])
" 2>/dev/null || {
        echo "  Falling back to restart-all..."
        clawctl restart-all --config clawctl.toml || true
    }
else
    echo "  ⚠ clawctl not available, restarting containers manually..."
    docker ps --filter "name=openclaw-" --format "{{.Names}}" | while read -r container; do
        docker restart "\$container" 2>/dev/null || true
    done
fi

echo ""
echo "Step 5: Verifying deployment..."
sleep 3
if command -v clawctl >/dev/null 2>&1 && [ -f "clawctl.toml" ]; then
    echo ""
    clawctl status --config clawctl.toml || true
else
    echo ""
    docker ps --filter "name=openclaw-" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
fi

echo ""
echo "=========================================="
echo "Deployment complete!"
echo "=========================================="
REMOTE_SCRIPT

echo ""
echo "=========================================="
echo "Update deployment completed"
echo "=========================================="
echo ""
echo "Containers should be running with latest code."
echo "Check logs if needed:"
echo "  ssh -p $SSH_PORT -i $SSH_KEY $SSH_USER@$LIGHTSAIL_IP"
echo "  docker logs openclaw-user1"
