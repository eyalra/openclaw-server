"""Log streaming endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status

from clawctl_web.auth import get_current_user
from clawlib.core.config import find_config_path, load_config
from clawlib.core.docker_manager import DockerManager

router = APIRouter()


def _get_docker_manager() -> DockerManager:
    """Get DockerManager instance."""
    config_path_resolved = find_config_path()
    if not config_path_resolved:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configuration file not found",
        )
    config = load_config(config_path_resolved)
    return DockerManager(config)


@router.get("/{username}")
async def get_logs(
    username: str,
    tail: int = Query(default=100, ge=1, le=10000),
    _user: str = Depends(get_current_user),
    config_path: Path | None = None,
):
    """Get logs for an instance (non-streaming)."""
    docker_mgr = _get_docker_manager(config_path)

    if not docker_mgr.container_exists(username):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Container for '{username}' does not exist",
        )

    try:
        logs_list = list(docker_mgr.stream_logs(username, follow=False, tail=tail))
        return {"username": username, "logs": logs_list}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get logs: {str(e)}",
        )


@router.websocket("/{username}/stream")
async def stream_logs(
    websocket: WebSocket,
    username: str,
):
    """Stream logs for an instance via WebSocket."""
    await websocket.accept()

    try:
        config_path_resolved = find_config_path()
        if not config_path_resolved:
            await websocket.send_json({"error": "Configuration file not found"})
            await websocket.close()
            return

        config = load_config(config_path_resolved)
        docker_mgr = DockerManager(config)

        if not docker_mgr.container_exists(username):
            await websocket.send_json({"error": f"Container for '{username}' does not exist"})
            await websocket.close()
            return

        # Stream logs
        for line in docker_mgr.stream_logs(username, follow=True, tail=100):
            await websocket.send_text(line)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"error": str(e)})
        except Exception:
            pass
        await websocket.close()
