"""User provisioning orchestration."""

from __future__ import annotations

import os
import secrets
import shutil
import subprocess

from pathlib import Path

from clawctl.core.docker_manager import DockerManager
from clawctl.core.openclaw_config import write_openclaw_config
from clawctl.core.paths import Paths
from clawctl.core.secrets import SecretsManager
from clawctl.models.config import Config, DefaultsConfig, UserConfig

GATEWAY_TOKEN_SECRET_NAME = "openclaw_gateway_token"


def _resolve_template_dir(
    user: UserConfig, defaults: DefaultsConfig
) -> Path | None:
    """Return the effective workspace template directory for a user, or None."""
    return user.workspace_template or defaults.workspace_template


def copy_template(template_dir: Path, dest_dir: Path) -> list[Path]:
    """Copy template files into dest_dir, skipping files that already exist.

    Args:
        template_dir: Source directory of seed files.
        dest_dir: Target directory (user's openclaw dir).

    Returns:
        List of relative paths that were copied.

    Raises:
        FileNotFoundError: If template_dir does not exist.
        NotADirectoryError: If template_dir is not a directory.
    """
    if not template_dir.exists():
        msg = f"Template directory not found: {template_dir}"
        raise FileNotFoundError(msg)
    if not template_dir.is_dir():
        msg = f"Template path is not a directory: {template_dir}"
        raise NotADirectoryError(msg)

    copied: list[Path] = []
    for src_path in template_dir.rglob("*"):
        if src_path.is_dir():
            continue
        rel = src_path.relative_to(template_dir)
        dst_path = dest_dir / rel
        if dst_path.exists():
            continue
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dst_path)
        copied.append(rel)
    return copied


class UserManager:
    """Orchestrates user provisioning: directories, secrets, config, and containers."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.paths = Paths(config.clawctl.data_root, config.clawctl.build_root)
        self.secrets = SecretsManager(self.paths)
        self.docker = DockerManager(config)

    def provision_user(
        self, user: UserConfig, secret_values: dict[str, str]
    ) -> None:
        """Fully provision a new user.

        Args:
            user: The user configuration.
            secret_values: Mapping of secret_name -> value for all required secrets.
        """
        # 1. Create directory structure
        self.paths.ensure_user_dirs(user.name)
        
        # Fix permissions for container access (container runs as UID 1000)
        # Try to chown to 1000:1000 if we have permissions, otherwise log a warning
        openclaw_dir = self.paths.user_openclaw_dir(user.name)
        try:
            # Try to change ownership to UID 1000 (container user)
            # This may require sudo, so we try and fail gracefully
            subprocess.run(
                ["chown", "-R", "1000:1000", str(openclaw_dir)],
                check=False,
                capture_output=True,
            )
            # Set permissions to allow container user to read/write
            os.chmod(openclaw_dir, 0o775)
            workspace_dir = self.paths.user_workspace_dir(user.name)
            if workspace_dir.exists():
                os.chmod(workspace_dir, 0o775)
        except (PermissionError, FileNotFoundError):
            # If chown fails (needs sudo) or chmod fails, that's okay
            # The deployment script should handle permissions
            pass

        # 2. Copy workspace template (if configured)
        template_dir = _resolve_template_dir(user, self.config.clawctl.defaults)
        if template_dir is not None:
            copy_template(template_dir, self.paths.user_openclaw_dir(user.name))

        # 3. Write secret files
        for name, value in secret_values.items():
            self.secrets.write_secret(user.name, name, value)

        # 4. Auto-generate a gateway token if not already present
        if not self.secrets.secret_exists(user.name, GATEWAY_TOKEN_SECRET_NAME):
            token = secrets.token_urlsafe(32)
            self.secrets.write_secret(user.name, GATEWAY_TOKEN_SECRET_NAME, token)

        gateway_token = self.secrets.read_secret(user.name, GATEWAY_TOKEN_SECRET_NAME)

        # 5. Generate openclaw.json (includes gateway token for Docker NAT auth)
        write_openclaw_config(
            user,
            self.config.clawctl.defaults,
            self.paths.user_openclaw_config(user.name),
            gateway_token=gateway_token,
        )

        # 6. Create and start container
        if not self.docker.image_exists():
            self.docker.build_image()
        self.docker.create_container(user)
        self.docker.start_container(user.name)

    def remove_user(self, username: str, *, keep_data: bool = True) -> None:
        """Remove a user's container and network, optionally removing data.

        Args:
            username: The username to remove.
            keep_data: If True, preserves user data and secrets on disk.
        """
        self.docker.remove_container(username)
        self.docker.remove_network(username)

        if not keep_data:
            # Remove user data directory
            user_dir = self.paths.user_dir(username)
            if user_dir.is_dir():
                shutil.rmtree(user_dir)
            # Remove secrets
            self.secrets.remove_user_secrets(username)
