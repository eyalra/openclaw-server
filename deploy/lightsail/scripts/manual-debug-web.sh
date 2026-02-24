#!/bin/bash
# manual-debug-web.sh - Manual debugging steps to run ON THE SERVER

cat << 'EOF'
==========================================
Manual Web Interface Debugging
==========================================

Run these commands ON THE SERVER (SSH in first):

1. Check service status:
   sudo systemctl status clawctl-web

2. Check recent logs:
   sudo journalctl -u clawctl-web -n 50 --no-pager

3. Check if port is listening:
   sudo ss -tlnp | grep 9000
   # OR
   sudo netstat -tlnp | grep 9000

4. Test if Python can import modules:
   export PATH="$HOME/.local/venv/clawctl/bin:$PATH"
   python3 -c "import uvicorn; import fastapi; import bcrypt; print('All modules OK')"

5. Test running the server manually:
   export PATH="$HOME/.local/venv/clawctl/bin:$PATH"
   cd ~/openclaw
   python3 -m clawctl_web.server ~/openclaw/clawctl.toml
   # (Press Ctrl+C to stop)

6. Check service file:
   cat /etc/systemd/system/clawctl-web.service

7. Check if config file exists:
   ls -la ~/openclaw/clawctl.toml

8. Check environment variables in service:
   sudo systemctl show clawctl-web | grep -E "WEB_PORT|WEB_HOST|ExecStart"

9. Try restarting service:
   sudo systemctl restart clawctl-web
   sleep 3
   sudo systemctl status clawctl-web

10. Check firewall:
    sudo ufw status | grep 9000

==========================================
Quick Fix Commands
==========================================

If uvicorn/fastapi/bcrypt are missing:
  export PATH="$HOME/.local/bin:$PATH"
  uv pip install "fastapi>=0.115.0" "uvicorn[standard]>=0.32.0" "bcrypt>=4.0.0" \
    --python ~/.local/venv/clawctl/bin/python

If service file has wrong path:
  sudo systemctl stop clawctl-web
  # Edit the service file manually or re-run fix script

To manually start web server (for testing):
  export PATH="$HOME/.local/venv/clawctl/bin:$PATH"
  cd ~/openclaw
  WEB_PORT=9000 WEB_HOST=0.0.0.0 python3 -m clawctl_web.server ~/openclaw/clawctl.toml

EOF
