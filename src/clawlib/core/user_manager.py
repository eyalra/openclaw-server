"""User provisioning orchestration."""

from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)

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
        # Determine base_path for reverse proxy setups
        from clawlib.core.openclaw_config import _is_tailscale_available
        use_tailscale_serve = _is_tailscale_available()
        base_path = None if use_tailscale_serve else f"/gateway/{user.name}"
        
        write_openclaw_config(
            user,
            self.config.clawctl.defaults,
            self.paths.user_openclaw_config(user.name),
            gateway_token=gateway_token,
            base_path=base_path,
        )

        # 6. Create and start container
        if not self.docker.image_exists():
            self.docker.build_image()
        self.docker.create_container(user)
        self.docker.start_container(user.name)
        
        # 7. Run openclaw doctor --fix to ensure full authentication
        # This ensures gateway URL is properly authenticated and Discord/plugins are enabled
        logger.info(f"Running openclaw doctor --fix for newly provisioned user {user.name}")
        doctor_success = self.docker.run_doctor_fix(user.name)
        if not doctor_success:
            logger.warning(
                f"openclaw doctor --fix failed for {user.name}. "
                "Gateway authentication may not be fully configured. "
                "Check container logs for details."
            )

    def restart_user(self, username: str) -> None:
        """Restart a user's container.
        
        Regenerates openclaw.json with gateway token authentication before restarting
        to ensure full authentication is set up for gateway URLs and Discord integration.
        """
        user = self.config.get_user(username)
        if user is None:
            raise ValueError(f"User '{username}' not found in config")

        # Ensure gateway token exists (generate if missing)
        if not self.secrets.secret_exists(username, GATEWAY_TOKEN_SECRET_NAME):
            token = secrets.token_urlsafe(32)
            self.secrets.write_secret(username, GATEWAY_TOKEN_SECRET_NAME, token)

        # Read gateway token
        gateway_token = self.secrets.read_secret(username, GATEWAY_TOKEN_SECRET_NAME)

        # Regenerate openclaw.json with gateway token (ensures auth is configured)
        # Determine base_path for reverse proxy setups
        from clawlib.core.openclaw_config import _is_tailscale_available
        use_tailscale_serve = _is_tailscale_available()
        base_path = None if use_tailscale_serve else f"/gateway/{username}"
        
        write_openclaw_config(
            user,
            self.config.clawctl.defaults,
            self.paths.user_openclaw_config(username),
            gateway_token=gateway_token,
            base_path=base_path,
        )

        # Restart container
        self.docker.restart_container(username)
        
        # Run openclaw doctor --fix to ensure full authentication
        # This ensures gateway URL is properly authenticated and Discord/plugins are enabled
        self.docker.run_doctor_fix(username)

    def restart_all(self) -> list[str]:
        """Restart all user containers.

        Regenerates openclaw.json with gateway token authentication for each user
        before restarting to ensure full authentication is set up.

        Returns list of restarted usernames.
        """
        restarted = []
        for user in self.config.users:
            if self.docker.container_exists(user.name):
                try:
                    # Ensure gateway token exists (generate if missing)
                    if not self.secrets.secret_exists(user.name, GATEWAY_TOKEN_SECRET_NAME):
                        token = secrets.token_urlsafe(32)
                        self.secrets.write_secret(user.name, GATEWAY_TOKEN_SECRET_NAME, token)

                    # Read gateway token
                    gateway_token = self.secrets.read_secret(user.name, GATEWAY_TOKEN_SECRET_NAME)

                    # Regenerate openclaw.json with gateway token (ensures auth is configured)
                    # Determine base_path for reverse proxy setups
                    from clawlib.core.openclaw_config import _is_tailscale_available
                    use_tailscale_serve = _is_tailscale_available()
                    base_path = None if use_tailscale_serve else f"/gateway/{user.name}"
                    
                    write_openclaw_config(
                        user,
                        self.config.clawctl.defaults,
                        self.paths.user_openclaw_config(user.name),
                        gateway_token=gateway_token,
                        base_path=base_path,
                    )

                    # Restart container
                    self.docker.restart_container(user.name)
                    
                    # Run openclaw doctor --fix to ensure full authentication
                    # This ensures gateway URL is properly authenticated and Discord/plugins are enabled
                    logger.info(f"Running openclaw doctor --fix for restarted user {user.name}")
                    doctor_success = self.docker.run_doctor_fix(user.name)
                    if not doctor_success:
                        logger.warning(
                            f"openclaw doctor --fix failed for {user.name}. "
                            "Gateway authentication may not be fully configured. "
                            "Check container logs for details."
                        )
                    
                    restarted.append(user.name)
                except Exception:
                    pass
        return restarted

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
