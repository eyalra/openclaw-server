#!/bin/bash
# Validate .lightsail-config file
# Checks that configuration is valid and SSH connection works

set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/load-config.sh"

echo "Validating Lightsail deployment configuration..."
echo ""

# Check SSH key exists
if [ ! -f "$SSH_KEY" ]; then
    echo "✗ Error: SSH key not found at $SSH_KEY" >&2
    exit 1
fi
echo "✓ SSH key found: $SSH_KEY"

# Check SSH key permissions
PERMS=$(stat -c %a "$SSH_KEY" 2>/dev/null || stat -f %A "$SSH_KEY")
if [ "$PERMS" != "600" ]; then
    echo "⚠ Warning: SSH key should have 600 permissions (currently: $PERMS)"
    echo "  Run: chmod 600 $SSH_KEY"
else
    echo "✓ SSH key permissions correct (600)"
fi

# Validate IP address format (basic check)
if [[ ! "$LIGHTSAIL_IP" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
    echo "⚠ Warning: LIGHTSAIL_IP format may be invalid: $LIGHTSAIL_IP"
else
    echo "✓ Lightsail IP format valid: $LIGHTSAIL_IP"
fi

# Validate SSH port
if ! [[ "$SSH_PORT" =~ ^[0-9]+$ ]] || [ "$SSH_PORT" -lt 1 ] || [ "$SSH_PORT" -gt 65535 ]; then
    echo "✗ Error: Invalid SSH_PORT: $SSH_PORT" >&2
    exit 1
fi
echo "✓ SSH port valid: $SSH_PORT"

# Test SSH connection
echo ""
echo "Testing SSH connection..."
if ssh -p "$SSH_PORT" -i "$SSH_KEY" -o ConnectTimeout=5 -o BatchMode=yes -o StrictHostKeyChecking=no "$SSH_USER@$LIGHTSAIL_IP" exit 2>/dev/null; then
    echo "✓ SSH connection successful"
else
    echo "✗ SSH connection failed" >&2
    echo "" >&2
    echo "Troubleshooting:" >&2
    echo "  1. Verify instance is running in Lightsail console" >&2
    echo "  2. Check IP address: $LIGHTSAIL_IP" >&2
    echo "  3. Verify SSH key path: $SSH_KEY" >&2
    echo "  4. Check SSH port: $SSH_PORT" >&2
    echo "  5. Verify firewall allows port $SSH_PORT" >&2
    echo "  6. Test manually: ssh -p $SSH_PORT -i $SSH_KEY $SSH_USER@$LIGHTSAIL_IP" >&2
    exit 1
fi

# Check Tailscale IP if set
if [ -n "$TAILSCALE_IP" ]; then
    if [[ "$TAILSCALE_IP" =~ ^100\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
        echo "✓ Tailscale IP format valid: $TAILSCALE_IP"
    else
        echo "⚠ Warning: Tailscale IP format may be invalid: $TAILSCALE_IP"
        echo "  Expected format: 100.x.x.x"
    fi
else
    echo "⚠ Tailscale IP not set (optional, but recommended)"
fi

# Check remote paths
echo ""
echo "Remote paths:"
echo "  Home: $REMOTE_HOME"
echo "  Repo: $REMOTE_REPO_PATH"
echo "  Config: $REMOTE_CONFIG_PATH"

# Check local paths
if [ -n "$LOCAL_REPO_PATH" ]; then
    if [ -d "$LOCAL_REPO_PATH" ]; then
        echo "✓ Local repo path exists: $LOCAL_REPO_PATH"
    else
        echo "⚠ Warning: Local repo path does not exist: $LOCAL_REPO_PATH"
    fi
fi

echo ""
echo "✓ Configuration validation complete!"
echo ""
echo "Next steps:"
echo "  1. Follow SOP-01 to create Lightsail instance (if not done)"
echo "  2. Follow SOP-02 to create Discord bot (if not done)"
echo "  3. Follow SOP-03 to set up Tailscale (if not done)"
echo "  4. Run deployment scripts: 01-harden-server.sh, 02-install-dependencies.sh, etc."
