"""Pydantic models for clawctl configuration."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class ChannelSlackConfig(BaseModel):
    enabled: bool = False
    bot_token_secret: str | None = None
    app_token_secret: str | None = None


class ChannelDiscordConfig(BaseModel):
    enabled: bool = False
    token_secret: str | None = None


class ChannelsConfig(BaseModel):
    slack: ChannelSlackConfig = ChannelSlackConfig()
    discord: ChannelDiscordConfig = ChannelDiscordConfig()


class UserAgentConfig(BaseModel):
    model: str = "openrouter/z-ai/glm-4.5-air:free"


class GogSkillConfig(BaseModel):
    """Configuration for the gog (Google) skill.

    The email identifies which Google account the skill will access.
    It is written into openclaw.json (not a secret).
    The API key is still stored as a secret file.
    """

    enabled: bool = True
    email: str | None = None


class SkillsConfig(BaseModel):
    """OpenClaw skills configuration.

    Each skill can be enabled/disabled. When enabled, certain skills require
    specific API keys that will be prompted for during user provisioning.
    """

    gog: GogSkillConfig = GogSkillConfig()
    gemini: bool = True
    coding_agent: bool = True
    github: bool = True


# Mapping of skill name to required secret filenames
SKILL_REQUIRED_SECRETS = {
    "gog": ["gog_api_key", "gog_keyring_password"],
    "gemini": [],  # uses interactive OAuth login via `gemini` binary, no API key needed
    "coding_agent": [],  # coding-agent doesn't require external API keys
    "github": [],  # uses `gh auth login` interactive flow, no secret needed at provision time
}


class UserSecretsConfig(BaseModel):
    """Flexible secret mapping: logical name → secret filename.

    Each key becomes the env var name (uppercased) inside the container.
    Example: openrouter_api_key = "openrouter_api_key" results in
    OPENROUTER_API_KEY being set from /run/secrets/openrouter_api_key.
    """

    model_config = {"extra": "allow"}

    # No required fields — what you need depends on your provider.
    # Common examples:
    #   openrouter_api_key = "openrouter_api_key"
    #   anthropic_api_key = "anthropic_api_key"


class UserConfig(BaseModel):
    name: str
    channels: ChannelsConfig = ChannelsConfig()
    agent: UserAgentConfig = UserAgentConfig()
    skills: SkillsConfig = SkillsConfig()
    secrets: UserSecretsConfig
    workspace_template: Path | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not re.match(r"^[a-z0-9][a-z0-9-]{0,31}$", v):
            msg = "Username must be 1-32 lowercase alphanumeric characters or hyphens, starting with alphanumeric"
            raise ValueError(msg)
        return v


class BackupConfig(BaseModel):
    enabled: bool = True
    interval_minutes: int = Field(default=15, ge=5, le=60)
    include_patterns: list[str] = Field(
        default=[
            "workspace/**/*.md",
            "workspace/**/*.json",
            "openclaw.json",
        ]
    )


class DefaultsConfig(BaseModel):
    model: str = "openrouter/z-ai/glm-4.5-air:free"
    skills: SkillsConfig = SkillsConfig()
    workspace_template: Path | None = None


class ClawctlSettings(BaseModel):
    data_root: Path = Path("data")
    build_root: Path = Path("build")
    openclaw_version: str = "latest"
    image_name: str = "openclaw-instance"
    log_level: str = Field(default="info", pattern=r"^(debug|info|warning|error)$")
    backup: BackupConfig = BackupConfig()
    defaults: DefaultsConfig = DefaultsConfig()


class Config(BaseModel):
    clawctl: ClawctlSettings
    users: list[UserConfig] = []

    def get_user(self, name: str) -> UserConfig | None:
        """Get a user config by name."""
        for user in self.users:
            if user.name == name:
                return user
        return None

    def get_usernames(self) -> list[str]:
        """Get all configured usernames."""
        return [u.name for u in self.users]
