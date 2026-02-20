"""Resource statistics endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from clawctl_web.auth import get_current_user
from clawctl_web.docker_stats import get_container_stats
from clawlib.core.config import find_config_path, load_config
from clawlib.core.docker_manager import DockerManager

router = APIRouter()


def _get_docker_manager(config_path: Path | None = None) -> DockerManager:
    """Get DockerManager instance."""
    config_path_resolved = find_config_path(config_path)
    if not config_path_resolved:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configuration file not found",
        )
    config = load_config(config_path_resolved)
    return DockerManager(config)


@router.get("/{username}")
async def get_instance_stats(
    username: str,
    _user: str = Depends(get_current_user),
    config_path: Path | None = None,
):
    """Get resource usage stats for an instance."""
    docker_mgr = _get_docker_manager(config_path)

    if not docker_mgr.container_exists(username):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Container for '{username}' does not exist",
        )

    stats = get_container_stats(docker_mgr, username)
    if stats is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Could not get stats for '{username}'",
        )

    return {"username": username, **stats}
