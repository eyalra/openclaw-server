#!/bin/bash
# debug-status.sh - Debug container status and tokens

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../scripts/load-config.sh"

ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" << REMOTE_SCRIPT
set -e

REMOTE_HOME="$REMOTE_HOME"
REMOTE_REPO_PATH="$REMOTE_REPO_PATH"

cd "\$REMOTE_REPO_PATH"

# Ensure PATH includes venv bin
CLAWCTL_VENV="\$HOME/.local/venv/clawctl"
if [ -d "\$CLAWCTL_VENV" ]; then
    export PATH="\$CLAWCTL_VENV/bin:\$PATH"
fi

echo "=== Container Status ==="
docker ps -a --filter "name=openclaw-" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

echo ""
echo "=== Secrets Directory Check ==="
echo "REMOTE_HOME: \$REMOTE_HOME"
echo "Checking secrets directory: \$REMOTE_HOME/data/secrets/"
if [ -d "\$REMOTE_HOME/data/secrets" ]; then
    echo "  Directory exists"
    ls -la "\$REMOTE_HOME/data/secrets/" || echo "  Cannot list directory"
    echo ""
    echo "=== Token Files ==="
    SECRETS_DIR="\$REMOTE_HOME/data/secrets"
    if [ -d "\$SECRETS_DIR" ]; then
        for user_dir in "\$SECRETS_DIR"/*/; do
            if [ -d "\$user_dir" ]; then
                username=\$(basename "\$user_dir")
                echo "User: \$username"
                echo "  All files in secrets dir:"
                ls -la "\$user_dir" 2>/dev/null || echo "    Cannot list files"
                echo "  Token files:"
                if [ -f "\$user_dir/openclaw_gateway_token" ]; then
                    TOKEN_CONTENT=\$(cat "\$user_dir/openclaw_gateway_token" 2>/dev/null | head -c 30)
                    echo "    ✓ openclaw_gateway_token exists"
                    echo "    Content preview: \${TOKEN_CONTENT}..."
                fi
                if [ -f "\$user_dir/gateway_token" ]; then
                    TOKEN_CONTENT=\$(cat "\$user_dir/gateway_token" 2>/dev/null | head -c 30)
                    echo "    ✓ gateway_token exists"
                    echo "    Content preview: \${TOKEN_CONTENT}..."
                fi
                if [ ! -f "\$user_dir/openclaw_gateway_token" ] && [ ! -f "\$user_dir/gateway_token" ]; then
                    echo "    ✗ No token files found"
                fi
                echo ""
            fi
        done
    else
        echo "  ✗ Secrets directory does not exist: \$SECRETS_DIR"
    fi
else
    echo "  ✗ Secrets directory does not exist!"
    echo "  Expected: \$REMOTE_HOME/data/secrets/"
fi

echo "=== Config File Check ==="
if [ -f "clawctl.toml" ]; then
    echo "  Config file exists"
    echo "  Users in config:"
    grep -E "^\[\[users\]\]|^name = " clawctl.toml | grep -A1 "\[\[users\]\]" | grep "name = " | sed 's/name = /    - /' || echo "    Could not parse users"
else
    echo "  ✗ clawctl.toml not found"
fi

echo ""
echo "=== clawctl status ==="
CLAWCTL_VENV_PATH="\$HOME/.local/venv/clawctl"
if command -v clawctl >/dev/null 2>&1 && [ -f "clawctl.toml" ]; then
    clawctl status --config clawctl.toml || echo "  ⚠ Status command failed"
elif [ -d "\$CLAWCTL_VENV_PATH" ] && [ -f "\$CLAWCTL_VENV_PATH/bin/clawctl" ]; then
    echo "  Using venv clawctl:"
    "\$CLAWCTL_VENV_PATH/bin/clawctl" status --config clawctl.toml || echo "  ⚠ Status command failed"
else
    echo "  ⚠ clawctl not available"
    echo "  Venv path checked: \$CLAWCTL_VENV_PATH"
    if [ -d "\$CLAWCTL_VENV_PATH" ]; then
        echo "  Venv exists: YES"
    else
        echo "  Venv exists: NO"
    fi
fi
REMOTE_SCRIPT
