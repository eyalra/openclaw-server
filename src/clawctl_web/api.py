"""FastAPI application for clawctl-web."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.staticfiles import StaticFiles

from clawctl_web.endpoints import instances, logs, models, stats, system, users

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
    app.include_router(models.router, prefix="/api/models", tags=["models"])
    app.include_router(stats.router, prefix="/api/stats", tags=["stats"])
    app.include_router(system.router, prefix="/api/system", tags=["system"])
    app.include_router(users.router, prefix="/api/users", tags=["users"])

    # Serve static files with no-cache headers to prevent browser caching issues
    if _STATIC_DIR.exists():
        # Use a custom StaticFiles class that adds no-cache headers
        class NoCacheStaticFiles(StaticFiles):
            """StaticFiles with no-cache headers to prevent stale content."""
            async def __call__(self, scope, receive, send):
                async def send_wrapper(message):
                    if message["type"] == "http.response.start":
                        headers = dict(message.get("headers", []))
                        headers[b"cache-control"] = b"no-cache, no-store, must-revalidate"
                        headers[b"pragma"] = b"no-cache"
                        headers[b"expires"] = b"0"
                        message["headers"] = list(headers.items())
                    await send(message)
                
                await super().__call__(scope, receive, send_wrapper)
        
        app.mount("/static", NoCacheStaticFiles(directory=str(_STATIC_DIR)), name="static")

        @app.get("/", response_class=FileResponse)
        async def index():
            """Serve the main dashboard page."""
            response = FileResponse(_STATIC_DIR / "index.html")
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            return response

        @app.get("/login", response_class=FileResponse)
        async def login():
            """Serve the login page."""
            response = FileResponse(_STATIC_DIR / "login.html")
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            return response

    return app
