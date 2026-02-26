"""Per-user file push endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status

from clawctl_web.auth import get_current_user
from clawlib.core.config import find_config_path, load_config
from clawlib.core.file_manager import FileManager
from clawlib.core.paths import Paths

router = APIRouter()


def _get_file_manager(config_path: Path | None = None) -> FileManager:
    config_path_resolved = find_config_path(config_path)
    if not config_path_resolved:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configuration file not found",
        )
    config = load_config(config_path_resolved)
    paths = Paths(config.clawctl.data_root, config.clawctl.build_root)
    return FileManager(paths)


@router.get("/{username}/files")
async def list_files(
    username: str,
    _user: str = Depends(get_current_user),
):
    """List files pushed to a user's instance."""
    fm = _get_file_manager()
    files = fm.list_files(username)
    return {"username": username, "files": files}


@router.post("/{username}/files")
async def push_file(
    username: str,
    file: UploadFile,
    dest: str | None = None,
    executable: bool = False,
    _user: str = Depends(get_current_user),
):
    """Upload a file to a user's instance.

    The file is written to a temporary location first, then pushed via
    FileManager for validation, checksumming, and manifest tracking.
    """
    import tempfile

    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is required",
        )

    fm = _get_file_manager()

    # Write upload to a temp file, then push through FileManager
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{file.filename}") as tmp:
            contents = await file.read()
            tmp.write(contents)
            tmp_path = Path(tmp.name)

        entry = fm.push_file(
            username,
            tmp_path,
            dest or file.filename,
            executable=executable,
        )
        return {
            "username": username,
            "path": dest or file.filename,
            "entry": entry,
        }
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


@router.delete("/{username}/files/{path:path}")
async def remove_file(
    username: str,
    path: str,
    _user: str = Depends(get_current_user),
):
    """Remove a pushed file from a user's instance."""
    fm = _get_file_manager()

    try:
        removed = fm.remove_file(username, path)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found: {path}",
        )

    return {"username": username, "path": path, "removed": True}
