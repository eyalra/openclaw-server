#!/bin/bash
# verify-web-https.sh - Verify HTTPS web interface is working correctly

set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/load-config.sh"

echo "=========================================="
echo "Verify Web Interface HTTPS"
echo "=========================================="
echo ""

ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" bash << 'SSH_EOF'
set -e

echo "1. Checking Tailscale Serve status..."
SERVE_STATUS=$(sudo tailscale serve status 2>&1 || echo "")
if [ -n "$SERVE_STATUS" ]; then
    echo "$SERVE_STATUS"
else
    echo "   ✗ Tailscale Serve not configured"
    exit 1
fi

echo ""
echo "2. Getting Tailscale hostname and IP..."
TAILSCALE_HOSTNAME=$(tailscale status --json 2>/dev/null | grep -oE '"DNSName":"[^"]+"' | head -1 | cut -d'"' -f4 || echo "")
TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "")

if [ -z "$TAILSCALE_HOSTNAME" ]; then
    echo "   ⚠ MagicDNS hostname not available"
    echo "   Enable MagicDNS in Tailscale admin console"
else
    echo "   ✓ Hostname: $TAILSCALE_HOSTNAME"
fi

if [ -z "$TAILSCALE_IP" ]; then
    echo "   ✗ Tailscale IP not available"
    exit 1
else
    echo "   ✓ IP: $TAILSCALE_IP"
fi

echo ""
echo "3. Testing HTTPS access via hostname..."
if [ -n "$TAILSCALE_HOSTNAME" ]; then
    HTTP_CODE=$(curl -k -s -o /dev/null -w "%{http_code}" "https://$TAILSCALE_HOSTNAME/login" 2>&1 || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
        echo "   ✓ Login page accessible via HTTPS (hostname)"
    else
        echo "   ✗ Login page not accessible (HTTP $HTTP_CODE)"
    fi
else
    echo "   ⚠ Skipping hostname test (not available)"
fi

echo ""
echo "4. Testing direct IP (should fail - expected)..."
HTTP_CODE=$(curl -k -s -o /dev/null -w "%{http_code}" "https://$TAILSCALE_IP/" 2>&1 || echo "000")
if [ "$HTTP_CODE" = "000" ] || [ "$HTTP_CODE" = "000000" ]; then
    echo "   ✓ Direct IP correctly fails (Tailscale Serve tailnet-only mode)"
    echo "   This is expected - use the hostname instead"
else
    echo "   ⚠ Direct IP returned HTTP $HTTP_CODE (unexpected)"
fi

echo ""
echo "5. Checking web service binding..."
WEB_HOST=$(systemctl show clawctl-web --property=Environment --value | grep -oE 'WEB_HOST=[^ ]+' | cut -d= -f2 || echo "0.0.0.0")
if [ "$WEB_HOST" = "127.0.0.1" ]; then
    echo "   ✓ Web service bound to localhost (correct for Tailscale Serve)"
else
    echo "   ⚠ Web service bound to $WEB_HOST (should be 127.0.0.1)"
fi

echo ""
echo "=========================================="
echo "Summary"
echo "=========================================="
echo ""
echo "HTTPS Web Interface URLs:"
if [ -n "$TAILSCALE_HOSTNAME" ]; then
    echo "  ✓ https://$TAILSCALE_HOSTNAME/"
    echo "  ✓ https://$TAILSCALE_HOSTNAME/login"
fi
echo ""
echo "  ✗ https://$TAILSCALE_IP/ (does not work - use hostname)"
echo ""
echo "Note: Tailscale Serve 'tailnet only' mode only works via MagicDNS hostname."
echo "      Direct IP access is not supported in this mode."
echo ""
echo "If you see browser authentication prompts:"
echo "  1. Clear browser cache and cookies for the site"
echo "  2. Access /login directly first: https://$TAILSCALE_HOSTNAME/login"
echo "  3. Use the application login form, not browser prompts"

SSH_EOF

echo ""
echo "=========================================="
echo "Verification Complete"
echo "=========================================="
