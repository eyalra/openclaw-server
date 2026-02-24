"""Maintenance management endpoints."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from clawctl_web.auth import get_current_user
from clawlib.core.config import find_config_path, load_config
from clawlib.core.maintenance_manager import MaintenanceManager

router = APIRouter()
logger = logging.getLogger(__name__)

# Track in-progress background run to avoid double-triggering
_cycle_lock = threading.Lock()
_cycle_running = False


def _run_cycle_background(config_path: Path) -> None:
    """Run maintenance cycle in background thread."""
    global _cycle_running
    try:
        config = load_config(config_path)
        manager = MaintenanceManager(config)
        manager.run_cycle()
    except Exception:
        logger.exception("Background maintenance cycle failed")
    finally:
        with _cycle_lock:
            _cycle_running = False


@router.get("/status")
async def get_maintenance_status(
    _user: str = Depends(get_current_user),
    config_path: Path | None = None,
):
    """Get maintenance daemon status, last run, and next scheduled run."""
    config_path_resolved = find_config_path(config_path)
    if not config_path_resolved:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configuration file not found",
        )
    config = load_config(config_path_resolved)
    manager = MaintenanceManager(config)

    running = manager.is_daemon_running()
    pid = None
    if running:
        try:
            pid = int(manager.paths.maintenance_pid_file.read_text().strip())
        except Exception:
            pass

    return {
        "running": running,
        "pid": pid,
        "last_run": manager.get_last_run(),
        "next_run": manager.get_next_run(),
        "scheduled_time": config.clawctl.maintenance.restart_time,
        "backup_before_restart": config.clawctl.maintenance.backup_before_restart,
        "cycle_running": _cycle_running,
    }


@router.post("/run")
async def run_maintenance_now(
    background_tasks: BackgroundTasks,
    _user: str = Depends(get_current_user),
    config_path: Path | None = None,
):
    """Trigger an immediate maintenance cycle (backup + restart) in the background."""
    global _cycle_running

    config_path_resolved = find_config_path(config_path)
    if not config_path_resolved:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configuration file not found",
        )

    with _cycle_lock:
        if _cycle_running:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Maintenance cycle is already running",
            )
        _cycle_running = True

    background_tasks.add_task(_run_cycle_background, config_path_resolved)
    return {"message": "Maintenance cycle started in background"}


@router.post("/schedule/start")
async def start_maintenance_schedule(
    _user: str = Depends(get_current_user),
    config_path: Path | None = None,
):
    """Start the nightly maintenance daemon."""
    config_path_resolved = find_config_path(config_path)
    if not config_path_resolved:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configuration file not found",
        )
    config = load_config(config_path_resolved)
    manager = MaintenanceManager(config)

    if manager.is_daemon_running():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Maintenance daemon is already running",
        )

    try:
        pid = manager.start_daemon(config_path_resolved)
        return {
            "message": f"Maintenance daemon started (PID {pid})",
            "pid": pid,
            "scheduled_time": config.clawctl.maintenance.restart_time,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start maintenance daemon: {str(e)}",
        )


@router.post("/schedule/stop")
async def stop_maintenance_schedule(
    _user: str = Depends(get_current_user),
    config_path: Path | None = None,
):
    """Stop the nightly maintenance daemon."""
    config_path_resolved = find_config_path(config_path)
    if not config_path_resolved:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configuration file not found",
        )
    config = load_config(config_path_resolved)
    manager = MaintenanceManager(config)

    stopped = manager.stop_daemon()
    return {
        "message": "Maintenance daemon stopped" if stopped else "Maintenance daemon was not running",
        "was_running": stopped,
    }
