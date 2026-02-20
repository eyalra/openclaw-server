#!/bin/bash
# Load .lightsail-config file
# Usage: source scripts/load-config.sh
#
# This script loads configuration variables from .lightsail-config
# and validates that required variables are set.
#
# Note: We don't use 'set -e' because this script is meant to be sourced,
# and 'set -e' would cause the parent shell to exit on any error.

# Track if we encounter errors
ERROR_OCCURRED=0

# Get the directory where this script is located
# When sourced, BASH_SOURCE[0] contains the path as invoked (may be relative)
# Use the most reliable method: resolve relative to the directory where script actually is
# Save current directory
ORIGINAL_PWD="$(pwd)"

# Get script path
# BASH_SOURCE works in bash, but may be empty in zsh when sourcing
# Try multiple methods to get the script path
SCRIPT_PATH=""
if [ -n "${BASH_SOURCE[0]:-}" ]; then
    # Bash: BASH_SOURCE array contains source file paths
    SCRIPT_PATH="${BASH_SOURCE[0]}"
elif [ -n "${ZSH_VERSION:-}" ]; then
    # Zsh: use $0 or try to get from function context
    # When sourced, $0 contains the script path in zsh
    if [ -n "$0" ] && [ "$0" != "-zsh" ] && [ -f "$0" ]; then
        SCRIPT_PATH="$0"
    else
        # Try to get from the calling context
        # In zsh, we can use ${funcfiletrace[1]} but it's complex
        # For now, require the path to be passed or use a workaround
        echo "Error: Could not auto-detect script path in zsh. Please use absolute path:" >&2
        echo "  source /Users/er/src/openclaw/deploy/lightsail/scripts/load-config.sh" >&2
        ERROR_OCCURRED=1
        return 1 2>/dev/null || exit 1
    fi
elif [ -n "$0" ] && [ "$0" != "-bash" ] && [ -f "$0" ]; then
    # Fallback: use $0 if it's a file path
    SCRIPT_PATH="$0"
fi

# If we still don't have a path, error out
if [ -z "$SCRIPT_PATH" ]; then
    echo "Error: Could not determine script path. Are you sourcing this script?" >&2
    echo "Try using an absolute path:" >&2
    echo "  source /full/path/to/deploy/lightsail/scripts/load-config.sh" >&2
    ERROR_OCCURRED=1
    return 1 2>/dev/null || exit 1
fi

# Try to resolve using realpath if available (most reliable)
# But we need to be careful - realpath resolves relative to current directory
RESOLVED_PATH=""
if command -v realpath >/dev/null 2>&1; then
    # Use realpath with explicit base directory to ensure correct resolution
    if [[ "$SCRIPT_PATH" == /* ]]; then
        RESOLVED_PATH="$(realpath "$SCRIPT_PATH" 2>/dev/null)"
    else
        # For relative paths, resolve relative to current directory explicitly
        RESOLVED_PATH="$(realpath "$ORIGINAL_PWD/$SCRIPT_PATH" 2>/dev/null)"
    fi
fi

# If realpath failed or not available, try readlink
if [ -z "$RESOLVED_PATH" ] && command -v readlink >/dev/null 2>&1; then
    # Try readlink -f (Linux) first
    if [[ "$SCRIPT_PATH" == /* ]]; then
        RESOLVED_PATH="$(readlink -f "$SCRIPT_PATH" 2>/dev/null)"
    else
        RESOLVED_PATH="$(readlink -f "$ORIGINAL_PWD/$SCRIPT_PATH" 2>/dev/null)"
    fi
    # If that failed, try plain readlink (macOS) - but this doesn't resolve, so skip
fi

# Fallback: manual resolution (most reliable for sourced scripts)
if [ -z "$RESOLVED_PATH" ] || [ ! -f "$RESOLVED_PATH" ]; then
    if [[ "$SCRIPT_PATH" == /* ]]; then
        # Absolute path - use as-is
        RESOLVED_PATH="$SCRIPT_PATH"
    else
        # Relative path - resolve relative to current directory
        RESOLVED_PATH="$ORIGINAL_PWD/$SCRIPT_PATH"
    fi
fi

# Verify the resolved path exists
if [ ! -f "$RESOLVED_PATH" ]; then
    echo "Error: Script not found at resolved path: $RESOLVED_PATH" >&2
    echo "  Original path: $SCRIPT_PATH" >&2
    echo "  Current directory: $ORIGINAL_PWD" >&2
    ERROR_OCCURRED=1
    return 1 2>/dev/null || exit 1
fi

# Now get the directory (always use cd+pwd to ensure absolute path)
SCRIPT_DIR="$(cd "$(dirname "$RESOLVED_PATH")" && pwd)"

# Ensure we got a valid directory
if [ ! -d "$SCRIPT_DIR" ]; then
    echo "Error: Could not determine script directory" >&2
    ERROR_OCCURRED=1
    return 1 2>/dev/null || exit 1
fi

# Get the deploy/lightsail directory (parent of scripts/)
DEPLOY_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG_FILE="$DEPLOY_DIR/.lightsail-config"

# Debug output (can be removed later)
# Check DEBUG from environment (works in both bash and zsh)
if [ "${DEBUG:-0}" = "1" ] || [ "${DEBUG:-}" = "true" ]; then
    echo "DEBUG: SCRIPT_DIR=$SCRIPT_DIR" >&2
    echo "DEBUG: DEPLOY_DIR=$DEPLOY_DIR" >&2
    echo "DEBUG: CONFIG_FILE=$CONFIG_FILE" >&2
    echo "DEBUG: PWD=$(pwd)" >&2
    echo "DEBUG: Config file exists: $([ -f "$CONFIG_FILE" ] && echo 'YES' || echo 'NO')" >&2
fi

# Check if config file exists
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: .lightsail-config not found at $CONFIG_FILE" >&2
    echo "Expected location: $CONFIG_FILE" >&2
    echo "Current directory: $(pwd)" >&2
    echo "Script directory: $SCRIPT_DIR" >&2
    echo "Deploy directory: $DEPLOY_DIR" >&2
    if [ -f "$DEPLOY_DIR/.lightsail-config.example" ]; then
        echo "Found .lightsail-config.example at: $DEPLOY_DIR/.lightsail-config.example" >&2
        echo "Copy it to .lightsail-config and fill in your values:" >&2
        echo "  cp $DEPLOY_DIR/.lightsail-config.example $CONFIG_FILE" >&2
    fi
    ERROR_OCCURRED=1
    return 1 2>/dev/null || exit 1
fi

# Check file permissions (should be 600)
PERMS=$(stat -c %a "$CONFIG_FILE" 2>/dev/null || stat -f %A "$CONFIG_FILE" 2>/dev/null)
if [ "$PERMS" != "600" ]; then
    echo "Warning: .lightsail-config should have 600 permissions (currently: $PERMS)" >&2
    echo "Run: chmod 600 $CONFIG_FILE" >&2
fi

# Source the config file
source "$CONFIG_FILE"

# Validate required variables
REQUIRED_VARS=("LIGHTSAIL_IP" "SSH_KEY" "SSH_USER")
MISSING_VARS=()

for var in "${REQUIRED_VARS[@]}"; do
    # Indirect variable expansion: bash uses ${!var}, zsh uses ${(P)var}
    if [ -n "${ZSH_VERSION:-}" ]; then
        # Zsh syntax
        var_value="${(P)var}"
    else
        # Bash syntax
        var_value="${!var}"
    fi
    if [ -z "$var_value" ]; then
        MISSING_VARS+=("$var")
    fi
done

if [ ${#MISSING_VARS[@]} -ne 0 ]; then
    echo "Error: Required variables not set in .lightsail-config:" >&2
    for var in "${MISSING_VARS[@]}"; do
        echo "  - $var" >&2
    done
    ERROR_OCCURRED=1
    return 1 2>/dev/null || exit 1
fi

# Expand paths (handle ~ and relative paths)
SSH_KEY="${SSH_KEY/#\~/$HOME}"
if [ ! "${SSH_KEY:0:1}" = "/" ]; then
    # Relative path - make it absolute relative to deploy dir
    SSH_KEY="$DEPLOY_DIR/$SSH_KEY"
fi

LOCAL_REPO_PATH="${LOCAL_REPO_PATH/#\~/$HOME}"
if [ -z "$LOCAL_REPO_PATH" ] || [ ! "${LOCAL_REPO_PATH:0:1}" = "/" ]; then
    # Auto-detect from git if not set or relative
    if command -v git >/dev/null 2>&1; then
        LOCAL_REPO_PATH="$(cd "$DEPLOY_DIR" && git rev-parse --show-toplevel 2>/dev/null || echo '')"
    fi
    if [ -z "$LOCAL_REPO_PATH" ]; then
        # Fallback: assume deploy/lightsail is in repo root
        LOCAL_REPO_PATH="$(cd "$DEPLOY_DIR/../.." && pwd)"
    fi
fi

# Export variables for use in calling scripts
export LIGHTSAIL_IP
export LIGHTSAIL_INSTANCE_NAME
export AWS_REGION
export SSH_KEY
export SSH_USER
export SSH_PORT
export TAILSCALE_IP
export TAILSCALE_AUTH_KEY
export REMOTE_HOME
export REMOTE_REPO_PATH
export REMOTE_CONFIG_PATH
export LOCAL_REPO_PATH
export LOCAL_DEPLOY_DIR
export S3_BUCKET
export S3_PREFIX
export S3_REGION
export SNAPSHOT_PREFIX
export KEEP_SNAPSHOTS
export ALLOWED_SSH_IPS
