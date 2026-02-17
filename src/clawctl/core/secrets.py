"""Secret file management for clawctl."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from clawctl.core.paths import Paths


class SecretsManager:
    """Manages per-user secret files on the host.

    Secrets are stored as individual files at <data_root>/secrets/<username>/<name>
    with 0600 permissions. They are bind-mounted read-only into containers at
    /run/secrets/ and converted to env vars by the entrypoint script.
    """

    def __init__(self, paths: Paths) -> None:
        self.paths = paths

    def write_secret(self, username: str, name: str, value: str) -> Path:
        """Write a secret value to a file with restricted permissions.

        Args:
            username: The user this secret belongs to.
            name: Secret filename (e.g., 'anthropic_api_key').
            value: The secret value.

        Returns:
            Path to the written secret file.
        """
        secret_dir = self.paths.user_secrets_dir(username)
        secret_dir.mkdir(parents=True, exist_ok=True)

        secret_file = secret_dir / name
        secret_file.write_text(value)
        os.chmod(secret_file, stat.S_IRUSR | stat.S_IWUSR)  # 0600
        return secret_file

    def read_secret(self, username: str, name: str) -> str | None:
        """Read a secret value. Returns None if the file doesn't exist."""
        secret_file = self.paths.user_secrets_dir(username) / name
        if secret_file.is_file():
            return secret_file.read_text()
        return None

    def secret_exists(self, username: str, name: str) -> bool:
        """Check if a secret file exists."""
        return (self.paths.user_secrets_dir(username) / name).is_file()

    def list_secrets(self, username: str) -> list[str]:
        """List secret filenames for a user."""
        secret_dir = self.paths.user_secrets_dir(username)
        if not secret_dir.is_dir():
            return []
        return sorted(f.name for f in secret_dir.iterdir() if f.is_file())

    def remove_user_secrets(self, username: str) -> None:
        """Remove all secrets for a user."""
        import shutil

        secret_dir = self.paths.user_secrets_dir(username)
        if secret_dir.is_dir():
            shutil.rmtree(secret_dir)

    def get_required_secrets(self, user_config) -> list[tuple[str, str]]:
        """Get list of (secret_name, description) required for a user config.

        Examines the user's secrets mapping and enabled channels to determine
        what's needed.  Each entry in user_config.secrets (extra fields) maps
        a logical name to a secret filename.
        """
        required: list[tuple[str, str]] = []

        # Collect all explicitly declared secrets from the [users.secrets] block.
        # Pydantic's extra="allow" stores them in model_extra.
        extras = user_config.secrets.model_extra or {}
        for logical_name, secret_filename in extras.items():
            description = logical_name.replace("_", " ").title()
            required.append((secret_filename, description))

        # Slack secrets
        if user_config.channels.slack.enabled:
            if user_config.channels.slack.bot_token_secret:
                required.append(
                    (user_config.channels.slack.bot_token_secret, "Slack bot token")
                )
            if user_config.channels.slack.app_token_secret:
                required.append(
                    (user_config.channels.slack.app_token_secret, "Slack app token")
                )

        # Discord secrets
        if user_config.channels.discord.enabled:
            if user_config.channels.discord.token_secret:
                required.append(
                    (user_config.channels.discord.token_secret, "Discord bot token")
                )

        return required
