"""User provisioning orchestration."""

from __future__ import annotations

import secrets
import shutil

from clawctl.core.docker_manager import DockerManager
from clawctl.core.openclaw_config import write_openclaw_config
from clawctl.core.paths import Paths
from clawctl.core.secrets import SecretsManager
from clawctl.models.config import Config, UserConfig

GATEWAY_TOKEN_SECRET_NAME = "openclaw_gateway_token"


class UserManager:
    """Orchestrates user provisioning: directories, secrets, config, and containers."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.paths = Paths(config.clawctl.data_root)
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

        # 2. Write secret files
        for name, value in secret_values.items():
            self.secrets.write_secret(user.name, name, value)

        # 3. Auto-generate a gateway token if not already present
        if not self.secrets.secret_exists(user.name, GATEWAY_TOKEN_SECRET_NAME):
            token = secrets.token_urlsafe(32)
            self.secrets.write_secret(user.name, GATEWAY_TOKEN_SECRET_NAME, token)

        gateway_token = self.secrets.read_secret(user.name, GATEWAY_TOKEN_SECRET_NAME)

        # 4. Generate openclaw.json (includes gateway token for Docker NAT auth)
        write_openclaw_config(
            user,
            self.config.clawctl.defaults,
            self.paths.user_openclaw_config(user.name),
            gateway_token=gateway_token,
        )

        # 5. Create and start container
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
