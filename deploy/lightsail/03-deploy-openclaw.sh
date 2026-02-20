#!/bin/bash
# 03-deploy-openclaw.sh
# Clone repository, build Docker image, create directory structure

set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/scripts/load-config.sh"

echo "=========================================="
echo "Deploying OpenClaw"
echo "=========================================="
echo ""
echo "This script will:"
echo "  1. Clone OpenClaw repository"
echo "  2. Create directory structure"
echo "  3. Build Docker image"
echo "  4. Set up knowledge directory"
echo ""
echo "Target server: $SSH_USER@$LIGHTSAIL_IP:$SSH_PORT"
echo ""

# Get repository URL (try to detect from local git)
REPO_URL=""
# Try to detect from LOCAL_REPO_PATH first
if [ -n "$LOCAL_REPO_PATH" ] && [ -d "$LOCAL_REPO_PATH/.git" ]; then
    REPO_URL=$(cd "$LOCAL_REPO_PATH" && git remote get-url origin 2>/dev/null || echo "")
fi

# If that didn't work, try from current directory (script might be run from repo root)
if [ -z "$REPO_URL" ] && [ -d ".git" ]; then
    REPO_URL=$(git remote get-url origin 2>/dev/null || echo "")
fi

# If still no URL, try from script's parent directory
if [ -z "$REPO_URL" ]; then
    SCRIPT_PARENT="$(cd "$SCRIPT_DIR/../.." && pwd)"
    if [ -d "$SCRIPT_PARENT/.git" ]; then
        REPO_URL=$(cd "$SCRIPT_PARENT" && git remote get-url origin 2>/dev/null || echo "")
    fi
fi

# Convert SSH URLs to HTTPS (SSH aliases won't work on server)
if [ -n "$REPO_URL" ]; then
    # Convert git@host:user/repo.git to https://host/user/repo.git
    if [[ "$REPO_URL" =~ ^git@([^:]+):(.+)\.git$ ]]; then
        GIT_HOST="${BASH_REMATCH[1]}"
        REPO_PATH="${BASH_REMATCH[2]}"
        # Handle common git hosting services
        if [[ "$GIT_HOST" == "github.com" ]] || [[ "$GIT_HOST" == *"github"* ]]; then
            REPO_URL="https://github.com/$REPO_PATH.git"
        elif [[ "$GIT_HOST" == "gitlab.com" ]] || [[ "$GIT_HOST" == *"gitlab"* ]]; then
            REPO_URL="https://gitlab.com/$REPO_PATH.git"
        else
            # Generic conversion
            REPO_URL="https://$GIT_HOST/$REPO_PATH.git"
        fi
        echo "  Converted SSH URL to HTTPS: $REPO_URL"
    # If it's already HTTPS or has an alias, try to resolve it
    elif [[ "$REPO_URL" =~ ^[^@]+@[^:]+: ]]; then
        # SSH URL with alias (like github-personal), convert to HTTPS
        if [[ "$REPO_URL" =~ :(.+)\.git$ ]]; then
            REPO_PATH="${BASH_REMATCH[1]}"
            # Try common hosting services
            if [[ "$REPO_PATH" =~ ^[^/]+/[^/]+$ ]]; then
                REPO_URL="https://github.com/$REPO_PATH.git"
                echo "  Converted SSH alias URL to GitHub HTTPS: $REPO_URL"
            fi
        fi
    fi
fi

if [ -z "$REPO_URL" ]; then
    echo "⚠ Could not auto-detect repository URL"
    read -p "Enter OpenClaw repository URL (HTTPS preferred): " REPO_URL
fi

echo "  Using repository URL: $REPO_URL"

# Confirm before proceeding
read -p "Continue with OpenClaw deployment? (yes/no): " confirm
if [ "$confirm" != "yes" ]; then
    echo "Aborted."
    exit 1
fi

echo ""
echo "Connecting to server..."

# Execute deployment on remote server
ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" << REMOTE_SCRIPT
set -e

# Ensure PATH includes standard directories
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:\$PATH"

echo "Step 1: Creating directory structure..."
# Ensure we're using the correct home directory for openclaw user
CURRENT_USER=\$(whoami 2>/dev/null || echo "\$USER")
if [ "\$CURRENT_USER" != "openclaw" ]; then
    # If running as ubuntu or root, use sudo
    sudo mkdir -p $REMOTE_HOME/data/{secrets,users,knowledge/{transcripts,newsletters,emails}}
    sudo mkdir -p $REMOTE_HOME/build/logs
    sudo chown -R openclaw:openclaw $REMOTE_HOME
else
    # If already running as openclaw, create directly
    mkdir -p $REMOTE_HOME/data/{secrets,users,knowledge/{transcripts,newsletters,emails}}
    mkdir -p $REMOTE_HOME/build/logs
fi
echo "  Directory structure created"

echo ""
echo "Step 2: Cloning OpenClaw repository..."
if [ -n "$REPO_URL" ] && [ "$REPO_URL" != "" ]; then
    if [ -d "$REMOTE_REPO_PATH" ]; then
        echo "  Repository already exists, pulling latest..."
        cd $REMOTE_REPO_PATH
        sudo -u openclaw git pull origin main || sudo -u openclaw git pull origin master
    else
        echo "  Cloning repository..."
        sudo -u openclaw git clone "$REPO_URL" $REMOTE_REPO_PATH
        sudo chown -R openclaw:openclaw $REMOTE_REPO_PATH
    fi
else
    echo "  ⚠ No repository URL provided"
    echo "  You'll need to upload the repository manually or clone it later"
    echo "  Creating directory: $REMOTE_REPO_PATH"
    CURRENT_USER=\$(whoami 2>/dev/null || echo "\$USER")
    if [ "\$CURRENT_USER" != "openclaw" ]; then
        sudo mkdir -p $REMOTE_REPO_PATH
        sudo chown -R openclaw:openclaw $REMOTE_REPO_PATH
    else
        mkdir -p $REMOTE_REPO_PATH
    fi
fi

echo ""
echo "Step 3: Installing Python dependencies (if needed)..."
if [ -f "$REMOTE_REPO_PATH/pyproject.toml" ]; then
    cd $REMOTE_REPO_PATH
    # Check if Python 3 is available
    if command -v python3 >/dev/null 2>&1; then
        echo "  Installing clawctl with uv..."
        # Install uv if not present, then install clawctl as openclaw user
        sudo -u openclaw bash -c "
            export PATH=\$HOME/.local/bin:\$PATH
            if ! command -v uv >/dev/null 2>&1; then
                echo '    Installing uv...'
                curl -LsSf https://astral.sh/uv/install.sh | sh
                export PATH=\$HOME/.local/bin:\$PATH
            fi
            cd $REMOTE_REPO_PATH
            CLAWCTL_VENV=\$HOME/.local/venv/clawctl
            if [ ! -d \"\$CLAWCTL_VENV\" ]; then
                echo '    Creating virtual environment...'
                uv venv \"\$CLAWCTL_VENV\"
            fi
            uv pip install -e '.' --python \"\$CLAWCTL_VENV/bin/python\"
        " || {
            echo "  ⚠ uv pip install failed, may need to install Python dependencies manually"
            echo "  Try: sudo -u openclaw bash -c 'cd $REMOTE_REPO_PATH && uv venv ~/.local/venv/clawctl && uv pip install -e \".\" --python ~/.local/venv/clawctl/bin/python'"
        }
        echo "  ✓ Python dependencies installed"
        echo "  Note: clawctl is installed at ~/.local/venv/clawctl/bin/clawctl"
    else
        echo "  ⚠ Python 3 not found, skipping Python install"
    fi
else
    echo "  ⚠ pyproject.toml not found, skipping Python install"
fi

echo ""
echo "Step 4: Building Docker image..."
cd $REMOTE_REPO_PATH
if [ -d "docker" ]; then
    echo "  Building OpenClaw Docker image..."
    # Build as openclaw user (who should be in docker group)
    sudo -u openclaw docker build -t openclaw-instance:latest --build-arg OPENCLAW_VERSION=latest docker/ || {
        echo "  ⚠ Docker build failed"
        echo "  You may need to build manually: docker build -t openclaw-instance:latest docker/"
    }
else
    echo "  ⚠ docker/ directory not found, skipping build"
fi

echo ""
echo "Step 5: Setting up knowledge directory permissions..."
sudo chown -R openclaw:openclaw $REMOTE_HOME/data/knowledge
chmod -R 755 $REMOTE_HOME/data/knowledge
echo "  Knowledge directory permissions set"

echo ""
echo "Step 6: Creating initial clawctl.toml (if needed)..."
if [ ! -f "$REMOTE_REPO_PATH/clawctl.toml" ]; then
    echo "  Creating template clawctl.toml..."
    # Create as openclaw user
    sudo -u openclaw bash -c "cat > $REMOTE_REPO_PATH/clawctl.toml << 'TOML'
[clawctl]
data_root = "$REMOTE_HOME/data"
build_root = "$REMOTE_HOME/build"
openclaw_version = "latest"
image_name = "openclaw-instance"
log_level = "info"
knowledge_dir = "$REMOTE_HOME/data/knowledge"

[clawctl.backup]
enabled = true
interval_minutes = 15
include_patterns = [
    "workspace/**/*.md",
    "workspace/**/*.json",
    "openclaw.json",
]

[clawctl.defaults]
model = "openrouter/z-ai/glm-4.5-air:free"
TOML"
    sudo chown openclaw:openclaw $REMOTE_REPO_PATH/clawctl.toml
    echo "  Template created - you'll need to add users in next step"
else
    echo "  clawctl.toml already exists"
fi

echo ""
echo "=========================================="
echo "OpenClaw deployment complete!"
echo "=========================================="
echo ""
echo "Directory structure:"
echo "  Data: $REMOTE_HOME/data/"
echo "  Repo: $REMOTE_REPO_PATH"
echo "  Knowledge: $REMOTE_HOME/data/knowledge/"
echo ""
echo "NEXT STEPS:"
echo "  1. Run: 04-configure-users.sh"
echo "     (This will create users and configure secrets)"
REMOTE_SCRIPT

echo ""
echo "=========================================="
echo "Deployment script completed"
echo "=========================================="
echo ""
echo "Next: Run 04-configure-users.sh to set up users"
