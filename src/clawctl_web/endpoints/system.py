"""System information endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from clawctl_web.auth import get_current_user
from clawlib.core.config import find_config_path, load_config
from clawlib.core.docker_manager import DockerManager

router = APIRouter()


@router.get("/config")
async def get_config(
    _user: str = Depends(get_current_user),
    config_path: Path | None = None,
):
    """Get system configuration (sanitized - no secrets)."""
    config_path_resolved = find_config_path(config_path)
    if not config_path_resolved:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configuration file not found",
        )
    config = load_config(config_path_resolved)

    # Return sanitized config (no secrets)
    from clawlib.models.config import WebConfig
    
    web_config = config.web if config.web else WebConfig()
    
    return {
        "clawctl": {
            "data_root": str(config.clawctl.data_root),
            "build_root": str(config.clawctl.build_root),
            "openclaw_version": config.clawctl.openclaw_version,
            "image_name": config.clawctl.image_name,
            "log_level": config.clawctl.log_level,
            "knowledge_dir": str(config.clawctl.knowledge_dir) if config.clawctl.knowledge_dir else None,
        },
        "web": {
            "enabled": web_config.enabled,
            "port": web_config.port,
            "host": web_config.host,
        },
        "user_count": len(config.users),
    }


@router.post("/update")
async def trigger_update(
    _user: str = Depends(get_current_user),
):
    """Trigger OpenClaw version update (rebuilds image and restarts containers)."""
    config_path_resolved = find_config_path()
    if not config_path_resolved:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configuration file not found",
        )
    config = load_config(config_path_resolved)
    docker_mgr = DockerManager(config)

    try:
        updated = docker_mgr.rebuild_all()
        return {
            "message": f"Updated {len(updated)} containers",
            "updated": updated,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update: {str(e)}",
        )
