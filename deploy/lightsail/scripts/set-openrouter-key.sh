#!/bin/bash
# set-openrouter-key.sh - Set OpenRouter API key for a user
#
# Stores the key as a local secret file and deploys it to the server,
# injecting it into the container's auth-profiles.json via paste-token.
#
# Usage:
#   ./scripts/set-openrouter-key.sh [username]
#
# Key source (in priority order):
#   1. OPENROUTER_API_KEY env var (for automation)
#   2. Local secret file at secrets/<username>/openrouter_api_key
#   3. Interactive prompt

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/load-config.sh"

USERNAME="${1:-}"

echo "=========================================="
echo "Set OpenRouter API Key"
echo "=========================================="
echo ""
echo "Target server: $SSH_USER@$LIGHTSAIL_IP:$SSH_PORT"
echo ""

if [ -z "$USERNAME" ]; then
    read -p "Username [alice]: " USERNAME
    USERNAME="${USERNAME:-alice}"
fi

echo "User: $USERNAME"
echo ""

LOCAL_SECRETS_DIR="$DEPLOY_DIR/secrets/$USERNAME"
LOCAL_KEY_FILE="$LOCAL_SECRETS_DIR/openrouter_api_key"
KEY=""

if [ -n "${OPENROUTER_API_KEY:-}" ]; then
    echo "Using OPENROUTER_API_KEY from environment."
    KEY="$OPENROUTER_API_KEY"
elif [ -f "$LOCAL_KEY_FILE" ]; then
    echo "Found local secret file: $LOCAL_KEY_FILE"
    KEY="$(cat "$LOCAL_KEY_FILE")"
    echo "Using stored key."
else
    read -sp "Enter OpenRouter API key (sk-or-v1-...): " KEY
    echo ""
    if [ -z "$KEY" ]; then
        echo "✗ Key cannot be empty!"
        exit 1
    fi

    mkdir -p "$LOCAL_SECRETS_DIR"
    chmod 700 "$LOCAL_SECRETS_DIR"
    printf '%s' "$KEY" > "$LOCAL_KEY_FILE"
    chmod 600 "$LOCAL_KEY_FILE"
    echo "✓ Key saved locally at: $LOCAL_KEY_FILE"
    echo "  (gitignored - safe to keep)"
fi

echo ""
echo "Deploying OpenRouter API key to server..."

ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" bash << EOF
set -e
CONTAINER="openclaw-$USERNAME"
SECRET_DIR="/home/openclaw/openclaw/data/secrets/$USERNAME"

# Write the secret file (used by new container creations via UserSecretsConfig)
mkdir -p "\$SECRET_DIR"
printf '%s' '$KEY' > "\$SECRET_DIR/openrouter_api_key"
chmod 600 "\$SECRET_DIR/openrouter_api_key"
echo "✓ Secret file written to server"

# Inject into running container's auth-profiles.json directly
# This takes effect immediately without recreating the container
if docker ps -q -f name="\$CONTAINER" | grep -q .; then
    echo "Injecting key into running container's auth-profiles.json..."
    docker exec -i "\$CONTAINER" python3 - '$KEY' << 'PYEOF'
import json, pathlib, sys
key = sys.argv[1].strip()
path = pathlib.Path("/home/node/.openclaw/agents/main/agent/auth-profiles.json")
path.parent.mkdir(parents=True, exist_ok=True)
# Merge with existing profiles if any
try:
    data = json.loads(path.read_text())
except Exception:
    data = {}
data.setdefault("profiles", {})["openrouter:manual"] = {
    "type": "token",
    "provider": "openrouter",
    "token": key
}
path.write_text(json.dumps(data, indent=2) + "\n")
print("✓ Key injected into auth-profiles.json")
PYEOF
    
    echo "Restarting container..."
    docker restart "\$CONTAINER"
    echo "✓ Container restarted"
else
    echo "Container \$CONTAINER is not running — key will be applied on next start."
fi
EOF

echo ""
echo "=========================================="
echo "OpenRouter API key set for $USERNAME"
echo "=========================================="
echo ""
echo "The agent should now be able to use OpenRouter models."
echo "Check gateway logs with: ssh -p $SSH_PORT -i $SSH_KEY $SSH_USER@$LIGHTSAIL_IP 'docker logs openclaw-$USERNAME --follow'"
