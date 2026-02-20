"""Authentication for clawctl-web."""

from __future__ import annotations

import os
from pathlib import Path

import bcrypt
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from clawlib.core.config import find_config_path, load_config
from clawlib.core.paths import Paths

security = HTTPBasic()


def _get_password_file_path() -> Path:
    """Get the path to the password file."""
    config_path_resolved = find_config_path()
    if not config_path_resolved:
        raise ValueError("Configuration file not found")
    config = load_config(config_path_resolved)
    paths = Paths(config.clawctl.data_root, config.clawctl.build_root)
    return paths.data_root / "secrets" / "web_admin" / "password"


def _ensure_password_file(password: str) -> None:
    """Ensure password file exists, creating it if needed."""
    password_file = _get_password_file_path()
    password_file.parent.mkdir(parents=True, exist_ok=True)

    if not password_file.exists():
        # Hash the password and store it
        hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
        password_file.write_bytes(hashed)
        password_file.chmod(0o600)


def verify_password(credentials: HTTPBasicCredentials) -> bool:
    """Verify HTTP Basic Auth credentials against stored password."""
    try:
        password_file = _get_password_file_path()
    except ValueError:
        return False

    if not password_file.exists():
        # Check if password is provided via environment variable
        env_password = os.environ.get("WEB_ADMIN_PASSWORD")
        if env_password:
            _ensure_password_file(env_password)
        else:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Web admin password not configured. Set WEB_ADMIN_PASSWORD environment variable.",
            )

    stored_hash = password_file.read_bytes()

    try:
        return bcrypt.checkpw(credentials.password.encode("utf-8"), stored_hash)
    except Exception:
        return False


def get_current_user(
    credentials: HTTPBasicCredentials = Security(security),
    config_path: Path | None = None,
) -> str:
    """Get the current authenticated user."""
    config_path_resolved = find_config_path(config_path)
    if not config_path_resolved:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configuration file not found",
        )
    config = load_config(config_path_resolved)
    from clawlib.models.config import WebConfig
    
    web_config = getattr(config, 'web', None) or WebConfig()
    expected_username = web_config.admin_username

    if credentials.username != expected_username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )

    if not verify_password(credentials):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )

    return credentials.username
