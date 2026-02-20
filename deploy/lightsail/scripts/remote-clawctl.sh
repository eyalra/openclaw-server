#!/bin/bash
# remote-clawctl.sh - Run clawctl commands on the remote server

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../scripts/load-config.sh"

# Pass all arguments to remote clawctl
ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" << REMOTE_SCRIPT
set -e

cd $REMOTE_REPO_PATH

# Ensure PATH includes venv bin
CLAWCTL_VENV="\$HOME/.local/venv/clawctl"
if [ -d "\$CLAWCTL_VENV" ]; then
    export PATH="\$CLAWCTL_VENV/bin:\$PATH"
fi

# Run clawctl with all passed arguments
clawctl "$@" --config $REMOTE_REPO_PATH/clawctl.toml
REMOTE_SCRIPT
