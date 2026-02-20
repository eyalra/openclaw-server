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
        
        # Ensure the directory is writable by the current user
        # If the directory exists but isn't writable, try to fix permissions
        if secret_dir.exists() and not os.access(secret_dir, os.W_OK):
            try:
                os.chmod(secret_dir, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)  # 0755
            except (PermissionError, OSError):
                pass

        secret_file = secret_dir / name
        
        # If file exists and we can't write to it, try to remove it first
        # (might be owned by a different user)
        if secret_file.exists() and not os.access(secret_file, os.W_OK):
            try:
                secret_file.unlink()
            except (PermissionError, OSError):
                # If we can't remove it, try to overwrite anyway
                # This will raise PermissionError if it fails
                pass
        
        secret_file.write_text(value)
        # Use 0644 so the container user (UID 1000) can read it
        # The directory is mounted read-only, so we need readable permissions
        os.chmod(secret_file, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)  # 0644
        
        # Try to chown to 1000:1000 (container user) if we have permissions
        # This ensures the container can read the secret file
        try:
            import subprocess
            subprocess.run(
                ["chown", "1000:1000", str(secret_file)],
                check=False,
                capture_output=True,
            )
        except (FileNotFoundError, PermissionError):
            # chown not available or no permission - that's okay,
            # the deployment script should handle permissions
            pass
        
        return secret_file

    def read_secret(self, username: str, name: str) -> str | None:
        """Read a secret value. Returns None if the file doesn't exist."""
        secret_file = self.paths.user_secrets_dir(username) / name
        if secret_file.is_file():
            content = secret_file.read_text()
            # Strip whitespace (including newlines) from secret values
            return content.strip() if content else None
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

    def get_required_secrets(self, user_config, defaults=None) -> list[tuple[str, str]]:
        """Get list of (secret_name, description) required for a user config.

        Examines the user's secrets mapping, enabled channels, and enabled skills
        to determine what's needed. Each entry in user_config.secrets (extra fields)
        maps a logical name to a secret filename.

        Args:
            user_config: The user's configuration.
            defaults: Optional DefaultsConfig for skill inheritance.
        """
        from clawlib.models.config import SKILL_REQUIRED_SECRETS

        required: list[tuple[str, str]] = []
        seen: set[str] = set()  # Track to avoid duplicates

        # Skill-specific secret descriptions for better UX
        SKILL_SECRET_DESCRIPTIONS = {
            "gog_client_id": "Google OAuth Client ID",
            "gog_client_secret": "Google OAuth Client Secret",
            "gog_keyring_password": "Gog keyring encryption password",
        }

        # Collect all explicitly declared secrets from the [users.secrets] block.
        # Pydantic's extra="allow" stores them in model_extra.
        extras = user_config.secrets.model_extra or {}
        for logical_name, secret_filename in extras.items():
            if secret_filename not in seen:
                # Use specific description if available, otherwise generate from name
                description = SKILL_SECRET_DESCRIPTIONS.get(
                    secret_filename,
                    logical_name.replace("_", " ").title()
                )
                required.append((secret_filename, description))
                seen.add(secret_filename)
        
        # Collect skill-required secrets
        skills = user_config.skills
        if defaults:
            # Merge defaults with user-specific overrides
            for skill_name in ["gog", "gemini", "coding_agent"]:
                user_val = getattr(skills, skill_name, None)
                default_val = getattr(defaults.skills, skill_name, False)
                # A skill value may be a bool or an object with an .enabled attribute
                user_enabled = user_val.enabled if hasattr(user_val, "enabled") else user_val
                default_enabled = default_val.enabled if hasattr(default_val, "enabled") else default_val
                # User setting takes precedence; if not set, use default
                is_enabled = user_enabled if user_enabled is not None else default_enabled
                if is_enabled and skill_name in SKILL_REQUIRED_SECRETS:
                    for secret_name in SKILL_REQUIRED_SECRETS[skill_name]:
                        if secret_name not in seen:
                            # Use specific description if available, otherwise fallback to generic
                            description = SKILL_SECRET_DESCRIPTIONS.get(
                                secret_name,
                                f"{skill_name.replace('_', ' ').title()} API key"
                            )
                            required.append((secret_name, description))
                            seen.add(secret_name)
        else:
            # No defaults, just use user skills
            for skill_name in ["gog", "gemini", "coding_agent"]:
                val = getattr(skills, skill_name, False)
                is_enabled = val.enabled if hasattr(val, "enabled") else bool(val)
                if is_enabled and skill_name in SKILL_REQUIRED_SECRETS:
                    for secret_name in SKILL_REQUIRED_SECRETS[skill_name]:
                        if secret_name not in seen:
                            # Use specific description if available, otherwise fallback to generic
                            description = SKILL_SECRET_DESCRIPTIONS.get(
                                secret_name,
                                f"{skill_name.replace('_', ' ').title()} API key"
                            )
                            required.append((secret_name, description))
                            seen.add(secret_name)

        # Slack secrets
        if user_config.channels.slack.enabled:
            if user_config.channels.slack.bot_token_secret:
                if user_config.channels.slack.bot_token_secret not in seen:
                    required.append(
                        (user_config.channels.slack.bot_token_secret, "Slack bot token")
                    )
                    seen.add(user_config.channels.slack.bot_token_secret)
            if user_config.channels.slack.app_token_secret:
                if user_config.channels.slack.app_token_secret not in seen:
                    required.append(
                        (user_config.channels.slack.app_token_secret, "Slack app token")
                    )
                    seen.add(user_config.channels.slack.app_token_secret)

        # Discord secrets
        if user_config.channels.discord.enabled:
            if user_config.channels.discord.token_secret:
                if user_config.channels.discord.token_secret not in seen:
                    required.append(
                        (user_config.channels.discord.token_secret, "Discord bot token")
                    )
                    seen.add(user_config.channels.discord.token_secret)

        return required
