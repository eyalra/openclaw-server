#!/bin/bash
# 04-configure-users.sh
# Interactive user setup using existing clawctl CLI

set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/scripts/load-config.sh"

echo "=========================================="
echo "Configure OpenClaw Users"
echo "=========================================="
echo ""
echo "This script will:"
echo "  1. Create clawctl.toml with user definitions"
echo "  2. Use 'clawctl user add' to provision users"
echo "  3. Prompt for API keys and Discord tokens"
echo ""
echo "Target server: $SSH_USER@$LIGHTSAIL_IP:$SSH_PORT"
echo ""

# Check if we should use local or remote clawctl
USE_REMOTE=true
if command -v clawctl >/dev/null 2>&1; then
    read -p "Use local clawctl or remote? (local/remote) [remote]: " choice
    if [ "$choice" = "local" ]; then
        USE_REMOTE=false
    fi
fi

if [ "$USE_REMOTE" = true ]; then
    echo ""
    echo "Configuring users on remote server..."
    echo ""
    
    # Prompt for model provider
    echo "Select model provider:"
    echo "  1) Anthropic (Claude Sonnet/Opus) - Production quality"
    echo "  2) OpenRouter (cheap models) - Testing/Development"
    echo "  3) Both (use OpenRouter for testing, Anthropic for production)"
    read -p "Choice [2]: " provider_choice
    provider_choice=${provider_choice:-2}
    
    # Prompt for user details
    echo ""
    read -p "User 1 name [user1]: " user1_name
    user1_name=${user1_name:-user1}
    
    read -p "User 2 name [user2]: " user2_name
    user2_name=${user2_name:-user2}
    
    # Create TOML config on remote server
    ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" << REMOTE_SCRIPT
set -e

# Ensure PATH includes user's local bin (where uv installs binaries)
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:\$HOME/.local/bin:\$PATH"

cd $REMOTE_REPO_PATH

# Ensure uv is installed first
if ! command -v uv >/dev/null 2>&1; then
    echo "  Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh || {
        echo "  ⚠ Failed to install uv"
        exit 1
    }
    # Add uv to PATH (it installs to ~/.local/bin)
    export PATH="\$HOME/.local/bin:\$PATH"
fi

# Ensure clawctl is installed and available
CLAWCTL_VENV="\$HOME/.local/venv/clawctl"
if ! command -v clawctl >/dev/null 2>&1; then
    echo "  clawctl not found in PATH, checking installation..."
    if [ -f "$REMOTE_REPO_PATH/pyproject.toml" ]; then
        echo "  Installing clawctl..."
        cd $REMOTE_REPO_PATH
        
        # Create venv if it doesn't exist
        if [ ! -d "\$CLAWCTL_VENV" ]; then
            echo "    Creating virtual environment..."
            uv venv "\$CLAWCTL_VENV" || {
                echo "  ⚠ Failed to create virtual environment"
                exit 1
            }
        fi
        
        # Install clawctl into the venv
        uv pip install -e "." --python "\$CLAWCTL_VENV/bin/python" || {
            echo "  ⚠ uv pip install failed, trying to diagnose..."
            uv --version || echo "    uv not available"
            ls -la $REMOTE_REPO_PATH/pyproject.toml || echo "    pyproject.toml not found"
            exit 1
        }
        
        # Add venv's bin directory to PATH
        export PATH="\$CLAWCTL_VENV/bin:\$PATH"
        echo "  ✓ clawctl installed successfully"
    else
        echo "  ⚠ pyproject.toml not found at $REMOTE_REPO_PATH"
        exit 1
    fi
fi

# Ensure venv bin is in PATH for subsequent commands
if [ -d "\$CLAWCTL_VENV" ]; then
    export PATH="\$CLAWCTL_VENV/bin:\$PATH"
fi

# Verify clawctl is available
if ! command -v clawctl >/dev/null 2>&1; then
    echo "  ⚠ ERROR: clawctl still not found after installation attempt"
    echo "  Try running manually:"
    echo "    cd $REMOTE_REPO_PATH"
    echo "    uv venv ~/.local/venv/clawctl"
    echo "    uv pip install -e '.' --python ~/.local/venv/clawctl/bin/python"
    echo "    export PATH=~/.local/venv/clawctl/bin:\$PATH"
    echo "    clawctl --help"
    exit 1
fi

# Determine model based on provider choice
case "$provider_choice" in
    1)
        DEFAULT_MODEL="anthropic/claude-sonnet-4-20250514"
        SECRET1="anthropic_api_key"
        SECRET2="anthropic_api_key"
        ;;
    2)
        DEFAULT_MODEL="openrouter/z-ai/glm-4.5-air:free"
        SECRET1="openrouter_api_key"
        SECRET2="openrouter_api_key"
        ;;
    3)
        DEFAULT_MODEL="openrouter/z-ai/glm-4.5-air:free"
        SECRET1="anthropic_api_key openrouter_api_key"
        SECRET2="anthropic_api_key openrouter_api_key"
        ;;
esac

# Create/update clawctl.toml
cat > clawctl.toml << TOML
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
model = "$DEFAULT_MODEL"

[[users]]
name = "$user1_name"
[users.secrets]
$(for s in $SECRET1; do echo "$s = \"$s\""; done)
discord_token = "discord_token"
[users.agent]
model = "$DEFAULT_MODEL"
[users.channels.discord]
enabled = true
token_secret = "discord_token"

[[users]]
name = "$user2_name"
[users.secrets]
$(for s in $SECRET2; do echo "$s = \"$s\""; done)
discord_token = "discord_token"
[users.agent]
model = "$DEFAULT_MODEL"
[users.channels.discord]
enabled = true
token_secret = "discord_token"
TOML

echo "✓ clawctl.toml created with 2 users"
echo ""
echo "Now provisioning users interactively..."
echo ""

# Provision user1
echo "=========================================="
echo "Provisioning $user1_name"
echo "=========================================="
# Use full path or ensure PATH is set
CLAWCTL_CMD="\$(command -v clawctl || echo '\$HOME/.local/venv/clawctl/bin/clawctl')"
if command -v clawctl >/dev/null 2>&1 || [ -f "\$HOME/.local/venv/clawctl/bin/clawctl" ]; then
    # Check if container already exists
    if docker ps -a --format '{{.Names}}' | grep -q "^openclaw-$user1_name$"; then
        echo "  ✓ Container 'openclaw-$user1_name' already exists, skipping provisioning"
        echo "  To re-provision, remove the container first: docker rm -f openclaw-$user1_name"
    else
        "\$CLAWCTL_CMD" user add $user1_name --config $REMOTE_REPO_PATH/clawctl.toml || {
            echo "⚠ User provisioning failed for $user1_name"
            echo "  You may need to run manually: clawctl user add $user1_name"
        }
    fi
else
    echo "⚠ ERROR: clawctl not found"
    echo "  Install it first:"
    echo "    uv venv ~/.local/venv/clawctl"
    echo "    uv pip install -e '.' --python ~/.local/venv/clawctl/bin/python"
fi

echo ""
echo "=========================================="
echo "Provisioning $user2_name"
echo "=========================================="
CLAWCTL_CMD="\$(command -v clawctl || echo '\$HOME/.local/venv/clawctl/bin/clawctl')"
if command -v clawctl >/dev/null 2>&1 || [ -f "\$HOME/.local/venv/clawctl/bin/clawctl" ]; then
    # Check if container already exists
    if docker ps -a --format '{{.Names}}' | grep -q "^openclaw-$user2_name$"; then
        echo "  ✓ Container 'openclaw-$user2_name' already exists, skipping provisioning"
        echo "  To re-provision, remove the container first: docker rm -f openclaw-$user2_name"
    else
        "\$CLAWCTL_CMD" user add $user2_name --config $REMOTE_REPO_PATH/clawctl.toml || {
            echo "⚠ User provisioning failed for $user2_name"
            echo "  You may need to run manually: clawctl user add $user2_name"
        }
    fi
else
    echo "⚠ ERROR: clawctl not found"
    echo "  Install it first:"
    echo "    uv venv ~/.local/venv/clawctl"
    echo "    uv pip install -e '.' --python ~/.local/venv/clawctl/bin/python"
fi

echo ""
echo "=========================================="
echo "Fixing workspace permissions..."
echo "=========================================="
# Fix permissions for container access (containers run as UID 1000)
sudo chown -R 1000:1000 $REMOTE_HOME/data/users/*/openclaw 2>/dev/null || true
sudo chmod -R 775 $REMOTE_HOME/data/users/*/openclaw 2>/dev/null || true
echo "  ✓ Permissions fixed"

echo ""
echo "=========================================="
echo "User configuration complete!"
echo "=========================================="
echo ""
echo "Check status:"
CLAWCTL_CMD="\$(command -v clawctl || echo '\$HOME/.local/venv/clawctl/bin/clawctl')"
if command -v clawctl >/dev/null 2>&1 || [ -f "\$HOME/.local/venv/clawctl/bin/clawctl" ]; then
    "\$CLAWCTL_CMD" status --config $REMOTE_REPO_PATH/clawctl.toml || true
else
    echo "  ⚠ clawctl not available, skipping status check"
fi
REMOTE_SCRIPT

else
    echo ""
    echo "Using local clawctl..."
    echo "Make sure you have:"
    echo "  1. Cloned repository locally"
    echo "  2. Created clawctl.toml with user definitions"
    echo "  3. Run: clawctl user add <username>"
    echo ""
    echo "See DEVELOPMENT.md for local development workflow"
fi

echo ""
echo "=========================================="
echo "Configuration script completed"
echo "=========================================="
echo ""
echo "Next: Run 05-verify-deployment.sh to verify everything works"
