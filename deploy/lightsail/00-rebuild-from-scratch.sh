#!/bin/bash
# 00-rebuild-from-scratch.sh
# Complete rebuild: wipe everything and start fresh
# Uses existing clawctl clean command

set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/scripts/load-config.sh"

echo "=========================================="
echo "Complete Rebuild from Scratch"
echo "=========================================="
echo ""
echo "⚠ WARNING: This will DESTROY all data!"
echo ""
echo "This script will:"
echo "  1. Stop all containers"
echo "  2. Remove all containers and networks"
echo "  3. Clean all user data (secrets, workspaces)"
echo "  4. Remove Docker images (optional)"
echo "  5. Re-run deployment scripts"
echo ""
echo "Target server: $SSH_USER@$LIGHTSAIL_IP:$SSH_PORT"
echo ""

# Parse arguments
KEEP_KNOWLEDGE=false
RESTORE_SNAPSHOT=""
REMOVE_IMAGES=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --keep-knowledge)
            KEEP_KNOWLEDGE=true
            shift
            ;;
        --restore-snapshot)
            RESTORE_SNAPSHOT="$2"
            shift 2
            ;;
        --remove-images)
            REMOVE_IMAGES=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--keep-knowledge] [--restore-snapshot NAME] [--remove-images]"
            exit 1
            ;;
    esac
done

# Safety confirmation
echo "Are you ABSOLUTELY SURE you want to rebuild from scratch?"
read -p "Type 'REBUILD' to confirm: " confirm
if [ "$confirm" != "REBUILD" ]; then
    echo "Aborted. (You must type 'REBUILD' exactly)"
    exit 1
fi

echo ""
echo "Starting rebuild process..."

# Execute rebuild on remote server
ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" << REMOTE_SCRIPT
set -e

cd $REMOTE_REPO_PATH

echo "Step 1: Stopping all containers..."
if command -v clawctl >/dev/null 2>&1 && [ -f "clawctl.toml" ]; then
    clawctl stop-all --config clawctl.toml 2>/dev/null || true
    echo "  Containers stopped"
else
    # Fallback: stop containers manually
    docker ps --filter "name=openclaw-" --format "{{.Names}}" | while read -r container; do
        docker stop "\$container" 2>/dev/null || true
    done
fi

echo ""
echo "Step 2: Cleaning all data..."
if command -v clawctl >/dev/null 2>&1 && [ -f "clawctl.toml" ]; then
    # Backup config first
    cp clawctl.toml clawctl.toml.backup 2>/dev/null || true
    
    # Clean everything
    echo "y" | clawctl clean --all --config clawctl.toml --yes 2>/dev/null || {
        echo "  ⚠ clawctl clean failed, cleaning manually..."
        # Manual cleanup
        docker ps -a --filter "name=openclaw-" --format "{{.Names}}" | while read -r container; do
            docker rm -f "\$container" 2>/dev/null || true
        done
        docker network ls --filter "name=openclaw-net-" --format "{{.Name}}" | while read -r network; do
            docker network rm "\$network" 2>/dev/null || true
        done
        rm -rf $REMOTE_HOME/data/users
        rm -rf $REMOTE_HOME/data/secrets
        rm -rf $REMOTE_HOME/build
    }
else
    echo "  ⚠ clawctl not available, cleaning manually..."
    docker ps -a --filter "name=openclaw-" --format "{{.Names}}" | while read -r container; do
        docker rm -f "\$container" 2>/dev/null || true
    done
    rm -rf $REMOTE_HOME/data/users
    rm -rf $REMOTE_HOME/data/secrets
    rm -rf $REMOTE_HOME/build
fi

# Preserve knowledge directory if requested
if [ "$KEEP_KNOWLEDGE" = true ]; then
    echo "  ✓ Preserving knowledge directory"
    if [ -d "$REMOTE_HOME/data/knowledge" ]; then
        mv $REMOTE_HOME/data/knowledge $REMOTE_HOME/data/knowledge.backup
        mkdir -p $REMOTE_HOME/data/knowledge
        mv $REMOTE_HOME/data/knowledge.backup/* $REMOTE_HOME/data/knowledge/ 2>/dev/null || true
        rm -rf $REMOTE_HOME/data/knowledge.backup
    fi
else
    echo "  Knowledge directory will be removed"
fi

echo ""
echo "Step 3: Removing Docker images (if requested)..."
if [ "$REMOVE_IMAGES" = true ]; then
    docker rmi openclaw-instance:latest 2>/dev/null || echo "  Image not found or in use"
    echo "  Images removed"
else
    echo "  Keeping Docker images (use --remove-images to remove)"
fi

echo ""
echo "Step 4: Recreating directory structure..."
mkdir -p $REMOTE_HOME/data/{secrets,users,knowledge/{transcripts,newsletters,emails}}
mkdir -p $REMOTE_HOME/build/logs
chmod -R 755 $REMOTE_HOME/data/knowledge
echo "  Directory structure recreated"

echo ""
echo "=========================================="
echo "Cleanup complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. Run: 03-deploy-openclaw.sh (to rebuild image)"
echo "  2. Run: 04-configure-users.sh (to recreate users)"
echo "  3. Run: 05-verify-deployment.sh (to verify)"
REMOTE_SCRIPT

echo ""
echo "=========================================="
echo "Rebuild cleanup completed"
echo "=========================================="
echo ""
echo "Server is now clean. Run deployment scripts to rebuild:"
echo "  1. ./03-deploy-openclaw.sh"
echo "  2. ./04-configure-users.sh"
echo "  3. ./05-verify-deployment.sh"
