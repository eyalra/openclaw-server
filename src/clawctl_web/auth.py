"""Authentication for clawctl-web."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import bcrypt
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from clawlib.core.config import find_config_path, load_config
from clawlib.core.paths import Paths

logger = logging.getLogger(__name__)
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
        logger.debug(f"Password file path: {password_file}")
    except ValueError as e:
        logger.error(f"Failed to get password file path: {e}")
        return False

    if not password_file.exists():
        logger.warning(f"Password file does not exist: {password_file}")
        # Check if password is provided via environment variable
        env_password = os.environ.get("WEB_ADMIN_PASSWORD")
        if env_password:
            logger.info("Creating password file from WEB_ADMIN_PASSWORD environment variable")
            _ensure_password_file(env_password)
        else:
            logger.error("Password file not found and WEB_ADMIN_PASSWORD not set")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Web admin password not configured. Set WEB_ADMIN_PASSWORD environment variable or use 'clawctl web set-password'.",
            )

    try:
        stored_hash = password_file.read_bytes()
        logger.debug(f"Read password hash, length: {len(stored_hash)} bytes")
        
        # Verify it's a valid bcrypt hash format (starts with $2a$, $2b$, or $2y$)
        if len(stored_hash) < 4 or not stored_hash.startswith(b"$2"):
            logger.error(f"Invalid bcrypt hash format. First 20 bytes: {stored_hash[:20]}")
            return False
        
        # Check password
        password_bytes = credentials.password.encode("utf-8")
        result = bcrypt.checkpw(password_bytes, stored_hash)
        logger.debug(f"Password verification result: {result}")
        return result
    except ValueError as e:
        logger.error(f"bcrypt ValueError: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error during password verification: {type(e).__name__}: {e}")
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

    logger.debug(f"Authentication attempt for username: {credentials.username}, expected: {expected_username}")

    if credentials.username != expected_username:
        logger.warning(f"Username mismatch: got '{credentials.username}', expected '{expected_username}'")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )

    if not verify_password(credentials):
        logger.warning(f"Password verification failed for user: {credentials.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )

    logger.info(f"Successfully authenticated user: {credentials.username}")
    return credentials.username
