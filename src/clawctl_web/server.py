"""Server entry point for clawctl-web."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn

from clawctl_web.api import create_app

if __name__ == "__main__":
    # Allow config path to be specified via environment variable
    config_path = None
    if len(sys.argv) > 1:
        config_path = Path(sys.argv[1])
    
    app = create_app(config_path)
    
    # Get port from environment or default to 9000
    port = int(os.environ.get("WEB_PORT", "9000"))
    host = os.environ.get("WEB_HOST", "0.0.0.0")
    
    # Enable auto-reload in development (when WEB_RELOAD env var is set)
    # In production, restart the systemd service instead
    reload = os.environ.get("WEB_RELOAD", "false").lower() == "true"
    
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
        reload=reload,  # Auto-reload on code changes (development only)
    )
