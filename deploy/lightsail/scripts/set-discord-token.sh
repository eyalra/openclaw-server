#!/bin/bash
# set-discord-token.sh - Set Discord bot token for a user
#
# Stores the token as a local secret file and deploys it to the server
# using clawctl user set-discord, then restarts the container.
#
# Usage:
#   ./scripts/set-discord-token.sh [username]
#
# Token source (in priority order):
#   1. DISCORD_TOKEN env var (for automation)
#   2. Local secret file at secrets/<username>/discord_token
#   3. Interactive prompt

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/load-config.sh"

USERNAME="${1:-}"

echo "=========================================="
echo "Set Discord Bot Token"
echo "=========================================="
echo ""
echo "Target server: $SSH_USER@$LIGHTSAIL_IP:$SSH_PORT"
echo ""

# Get username
if [ -z "$USERNAME" ]; then
    read -p "Username [alice]: " USERNAME
    USERNAME="${USERNAME:-alice}"
fi

echo "User: $USERNAME"
echo ""

# Determine token source
LOCAL_SECRETS_DIR="$DEPLOY_DIR/secrets/$USERNAME"
LOCAL_TOKEN_FILE="$LOCAL_SECRETS_DIR/discord_token"
TOKEN=""

if [ -n "${DISCORD_TOKEN:-}" ]; then
    echo "Using DISCORD_TOKEN from environment."
    TOKEN="$DISCORD_TOKEN"
elif [ -f "$LOCAL_TOKEN_FILE" ]; then
    echo "Found local secret file: $LOCAL_TOKEN_FILE"
    TOKEN="$(cat "$LOCAL_TOKEN_FILE")"
    echo "Using stored token."
else
    read -sp "Enter Discord bot token: " TOKEN
    echo ""
    if [ -z "$TOKEN" ]; then
        echo "✗ Token cannot be empty!"
        exit 1
    fi

    # Save locally for future deployments
    mkdir -p "$LOCAL_SECRETS_DIR"
    chmod 700 "$LOCAL_SECRETS_DIR"
    printf '%s' "$TOKEN" > "$LOCAL_TOKEN_FILE"
    chmod 600 "$LOCAL_TOKEN_FILE"
    echo "✓ Token saved locally at: $LOCAL_TOKEN_FILE"
    echo "  (gitignored - safe to keep)"
fi

echo ""
echo "Deploying Discord token to server..."

ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" bash << EOF
set -e
export PATH="\$HOME/.local/venv/clawctl/bin:\$PATH"
cd "$REMOTE_REPO_PATH"

# Fix ownership of openclaw.json so clawctl can write it
# (container runs as uid 1000 which may have taken ownership)
DATA_ROOT="\$(grep -E 'data_root\s*=' "$REMOTE_REPO_PATH/clawctl.toml" | head -1 | grep -oP '\".*?\"' | tr -d '\"')"
CONFIG_FILE="\${DATA_ROOT}/users/$USERNAME/openclaw/openclaw.json"
if [ -f "\$CONFIG_FILE" ]; then
    sudo chown openclaw:openclaw "\$CONFIG_FILE"
    sudo chmod 644 "\$CONFIG_FILE"
fi
OPENCLAW_DIR="\${DATA_ROOT}/users/$USERNAME/openclaw"
if [ -d "\$OPENCLAW_DIR" ]; then
    sudo chown openclaw:openclaw "\$OPENCLAW_DIR"
    sudo chmod 755 "\$OPENCLAW_DIR"
fi

echo "Setting Discord token for $USERNAME..."
clawctl user set-discord \
    --token "$TOKEN" \
    --config "$REMOTE_REPO_PATH/clawctl.toml" \
    "$USERNAME"
EOF

echo ""
echo "=========================================="
echo "Discord token set successfully for $USERNAME"
echo "=========================================="
echo ""
echo "The container was restarted with the new token."
echo "Check gateway logs with: clawctl logs $USERNAME"
