"""FastAPI application for clawctl-web."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from clawctl_web.endpoints import instances, logs, stats, system, users

# Get the static directory path
_STATIC_DIR = Path(__file__).parent / "static"


def create_app(config_path: Path | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="OpenClaw Management Interface",
        description="Web-based management interface for OpenClaw instances",
        version="0.1.0",
    )

    # CORS middleware - allow all origins since we're behind Tailscale
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(instances.router, prefix="/api/instances", tags=["instances"])
    app.include_router(logs.router, prefix="/api/logs", tags=["logs"])
    app.include_router(stats.router, prefix="/api/stats", tags=["stats"])
    app.include_router(system.router, prefix="/api/system", tags=["system"])
    app.include_router(users.router, prefix="/api/users", tags=["users"])

    # Serve static files
    if _STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

        @app.get("/", response_class=FileResponse)
        async def index():
            """Serve the main dashboard page."""
            return FileResponse(_STATIC_DIR / "index.html")

    return app
