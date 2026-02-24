#!/bin/bash
# debug-web-interface.sh - Debug web interface issues

set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/load-config.sh"

echo "=========================================="
echo "Debugging Web Interface"
echo "=========================================="
echo ""

ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" << 'REMOTE_SCRIPT'
set -e

echo "Step 1: Checking systemd service status..."
if systemctl list-unit-files | grep -q clawctl-web; then
    echo "  Service file exists"
    sudo systemctl status clawctl-web --no-pager -l || true
else
    echo "  ⚠ Service file not found!"
fi

echo ""
echo "Step 2: Checking service logs (last 50 lines)..."
if systemctl list-unit-files | grep -q clawctl-web; then
    sudo journalctl -u clawctl-web -n 50 --no-pager || true
else
    echo "  ⚠ Cannot check logs - service not found"
fi

echo ""
echo "Step 3: Checking if process is running..."
if pgrep -f "clawctl_web.server" > /dev/null; then
    echo "  ✓ Process found:"
    ps aux | grep -E "clawctl_web|python.*server" | grep -v grep || true
else
    echo "  ⚠ No process found running clawctl_web.server"
fi

echo ""
echo "Step 4: Checking port 9000..."
if command -v ss >/dev/null 2>&1; then
    echo "  Checking with ss:"
    sudo ss -tlnp | grep 9000 || echo "  ⚠ Port 9000 not listening"
elif command -v netstat >/dev/null 2>&1; then
    echo "  Checking with netstat:"
    sudo netstat -tlnp | grep 9000 || echo "  ⚠ Port 9000 not listening"
else
    echo "  ⚠ Cannot check ports - ss/netstat not available"
fi

echo ""
echo "Step 5: Testing localhost connection..."
if curl -sf http://localhost:9000/ >/dev/null 2>&1; then
    echo "  ✓ Web interface responding on localhost:9000"
else
    echo "  ⚠ Web interface NOT responding on localhost:9000"
    echo "  Testing with verbose curl:"
    curl -v http://localhost:9000/ 2>&1 | head -20 || true
fi

echo ""
echo "Step 6: Checking clawctl installation..."
CLAWCTL_VENV="$HOME/.local/venv/clawctl"
if [ -d "$CLAWCTL_VENV" ]; then
    echo "  ✓ Virtual environment exists: $CLAWCTL_VENV"
    export PATH="$CLAWCTL_VENV/bin:$PATH"
    
    if [ -f "$CLAWCTL_VENV/bin/clawctl" ]; then
        echo "  ✓ clawctl binary exists"
        echo "  Version:"
        "$CLAWCTL_VENV/bin/clawctl" --version 2>&1 || echo "    (version check failed)"
        
        echo "  Checking if web command exists:"
        if "$CLAWCTL_VENV/bin/clawctl" web --help >/dev/null 2>&1; then
            echo "    ✓ web command available"
        else
            echo "    ⚠ web command NOT available"
        fi
    else
        echo "  ⚠ clawctl binary not found"
    fi
    
    echo "  Checking Python module:"
    if "$CLAWCTL_VENV/bin/python" -c "import clawctl_web" 2>/dev/null; then
        echo "    ✓ clawctl_web module importable"
    else
        echo "    ⚠ clawctl_web module NOT importable"
        echo "    Error:"
        "$CLAWCTL_VENV/bin/python" -c "import clawctl_web" 2>&1 | head -5 || true
    fi
else
    echo "  ⚠ Virtual environment not found: $CLAWCTL_VENV"
fi

echo ""
echo "Step 7: Checking service file contents..."
if [ -f /etc/systemd/system/clawctl-web.service ]; then
    echo "  Service file exists, showing contents:"
    cat /etc/systemd/system/clawctl-web.service
else
    echo "  ⚠ Service file not found: /etc/systemd/system/clawctl-web.service"
fi

echo ""
echo "Step 8: Checking if config file exists..."
if [ -f "$REMOTE_REPO_PATH/clawctl.toml" ]; then
    echo "  ✓ Config file exists: $REMOTE_REPO_PATH/clawctl.toml"
    echo "  Checking web config section:"
    grep -A 5 "\[web\]" "$REMOTE_REPO_PATH/clawctl.toml" || echo "    (no [web] section found)"
else
    echo "  ⚠ Config file not found: $REMOTE_REPO_PATH/clawctl.toml"
fi

echo ""
echo "Step 9: Testing manual start (dry run)..."
export PATH="$HOME/.local/venv/clawctl/bin:$PATH"
if [ -f "$CLAWCTL_VENV/bin/python" ] && [ -f "$REMOTE_REPO_PATH/clawctl.toml" ]; then
    echo "  Command that would be run:"
    echo "    $CLAWCTL_VENV/bin/python -m clawctl_web.server $REMOTE_REPO_PATH/clawctl.toml"
    echo "  Testing import:"
    if "$CLAWCTL_VENV/bin/python" -c "from clawctl_web.server import *" 2>&1; then
        echo "    ✓ Module imports successfully"
    else
        echo "    ⚠ Module import failed:"
        "$CLAWCTL_VENV/bin/python" -c "from clawctl_web.server import *" 2>&1 | head -10 || true
    fi
else
    echo "  ⚠ Cannot test - missing dependencies"
fi

echo ""
echo "Step 10: Checking firewall..."
if command -v ufw >/dev/null 2>&1; then
    echo "  UFW status:"
    sudo ufw status | head -5 || true
    if sudo ufw status | grep -q "9000"; then
        echo "  ✓ Port 9000 is allowed"
    else
        echo "  ⚠ Port 9000 may not be allowed"
    fi
else
    echo "  UFW not installed or not active"
fi

echo ""
echo "=========================================="
echo "Debugging Complete"
echo "=========================================="
REMOTE_SCRIPT
