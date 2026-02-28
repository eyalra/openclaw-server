"""Pydantic models for clawctl configuration."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ChannelSlackConfig(BaseModel):
    enabled: bool = False
    bot_token_secret: str | None = None
    app_token_secret: str | None = None


class ChannelDiscordConfig(BaseModel):
    enabled: bool = False
    token_secret: str | None = None
    owner_id: str | None = Field(default=None, description="Discord user ID to pre-approve for DM access on provisioning")


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


# Mapping of skill name to required secret filenames.
# gog uses Google Cloud OAuth 2.0:
#   gog_client_id / gog_client_secret  — from Google Cloud Console (Desktop app OAuth client)
#   gog_keyring_password               — encrypts stored refresh tokens on disk
# The entrypoint seeds gog credentials from GOG_CLIENT_ID / GOG_CLIENT_SECRET on first start.
# After provisioning, run `clawctl gog setup <username>` to complete the OAuth token exchange.
SKILL_REQUIRED_SECRETS = {
    "gog": ["gog_client_id", "gog_client_secret", "gog_keyring_password"],
    "gemini": [],  # uses interactive OAuth login via `gemini` binary, no API key needed
    "coding_agent": [],  # coding-agent doesn't require external API keys
    "github": ["gh_token"],  # classic PAT for push access; also used by `gh` CLI via GH_TOKEN env var
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


class GitRepoConfig(BaseModel):
    """A git repository to clone into the agent's workspace."""

    url: str = Field(description="HTTPS clone URL (e.g. https://github.com/org/repo.git)")
    branch: str = "main"
    path: str = Field(description="Clone destination relative to workspace root")

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        normalized = Path(v).as_posix()
        if normalized.startswith("/") or ".." in normalized.split("/"):
            raise ValueError(f"Invalid repo path: {v} (must be relative, no ..)")
        return v


class UserGitConfig(BaseModel):
    """Git identity and repository configuration for the coding agent."""

    user_name: str = ""
    email: str = ""
    token_secret: str = Field(default="gh_token", description="Secret filename containing the GitHub PAT")
    repos: list[GitRepoConfig] = Field(default_factory=list)


class UserConfig(BaseModel):
    name: str
    port: int | None = Field(default=None, ge=1024, le=65535, description="Fixed host port for the gateway (optional; random if unset)")
    channels: ChannelsConfig = ChannelsConfig()
    agent: UserAgentConfig = UserAgentConfig()
    skills: SkillsConfig = SkillsConfig()
    secrets: UserSecretsConfig
    git: UserGitConfig | None = None
    workspace_template: Path | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not re.match(r"^[a-z0-9][a-z0-9-]{0,31}$", v):
            msg = "Username must be 1-32 lowercase alphanumeric characters or hyphens, starting with alphanumeric"
            raise ValueError(msg)
        return v


class MaintenanceConfig(BaseModel):
    """Configuration for the nightly maintenance cycle (backup → restart)."""

    enabled: bool = True
    restart_time: str = Field(
        default="02:00",
        description="Daily maintenance time in HH:MM format (UTC)",
        pattern=r"^\d{2}:\d{2}$",
    )
    backup_before_restart: bool = True


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


def _validate_drive_name(name: str) -> str:
    """Validate a drive/collection name to prevent directory traversal."""
    normalized = Path(name).as_posix()
    if normalized.startswith("/") or normalized.startswith(".."):
        raise ValueError(f"Invalid drive name: {name} (cannot start with / or ..)")
    if "//" in normalized:
        raise ValueError(f"Invalid drive name: {name} (cannot contain //)")
    return name


class SharedDriveConfig(BaseModel):
    """A shared drive with optional per-user access control.

    If ``users`` is None (the default), all users can access the drive.
    Otherwise only the listed usernames may access it.
    """

    name: str
    users: list[str] | None = Field(
        default=None,
        description="Usernames that may access this drive. None = all users.",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _validate_drive_name(v)


class SharedCollectionsConfig(BaseModel):
    """Shared drives synced from S3 or a local directory.

    Two ways to declare drives:
      - ``collections``: simple list of names, accessible to all users.
      - ``drives``: list of SharedDriveConfig with optional per-user access.

    Both are synced and mounted. Container mount path: /mnt/shared/{drive_name}/.
    """

    source_type: Literal["s3", "local"] = "s3"

    # S3 configuration (required if source_type is "s3")
    s3_bucket: str | None = None
    s3_prefix: str = ""  # Base prefix in bucket (e.g., "shared-docs/")

    # Local configuration (required if source_type is "local")
    local_source_base: Path | None = None

    collections: list[str] = Field(default_factory=list)
    drives: list[SharedDriveConfig] = Field(default_factory=list)
    sync_schedule: str = Field(default="daily", description="Schedule: 'daily', 'hourly', or cron expression")

    @field_validator("collections")
    @classmethod
    def validate_collections(cls, v: list[str]) -> list[str]:
        for collection in v:
            _validate_drive_name(collection)
        return v

    @model_validator(mode="after")
    def validate_source_config(self) -> "SharedCollectionsConfig":
        if self.source_type == "s3":
            if not self.s3_bucket:
                raise ValueError("s3_bucket is required when source_type is 's3'")
        elif self.source_type == "local":
            if not self.local_source_base:
                raise ValueError("local_source_base is required when source_type is 'local'")
        return self

    @property
    def all_drive_names(self) -> list[str]:
        """Union of ``collections`` (all-user) and ``drives`` names, for sync."""
        names = list(self.collections)
        for d in self.drives:
            if d.name not in names:
                names.append(d.name)
        return names

    def drives_for_user(self, username: str) -> list[str]:
        """Return drive names accessible to *username*."""
        accessible: list[str] = list(self.collections)
        for d in self.drives:
            if d.name in accessible:
                continue
            if d.users is None or username in d.users:
                accessible.append(d.name)
        return accessible


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
    knowledge_dir: Path | None = None  # Optional shared knowledge directory (read-only mount) - deprecated, use shared_collections
    backup: BackupConfig = BackupConfig()
    maintenance: MaintenanceConfig = MaintenanceConfig()
    defaults: DefaultsConfig = DefaultsConfig()
    shared_collections: SharedCollectionsConfig | None = None  # S3-synced shared document collections


class ModelPriceLimits(BaseModel):
    """Price limits for filtering models."""
    max_prompt_price_per_million: float | None = Field(
        default=None,
        ge=0,
        description="Maximum price per million prompt tokens (USD). Models exceeding this will be filtered out."
    )
    max_completion_price_per_million: float | None = Field(
        default=None,
        ge=0,
        description="Maximum price per million completion tokens (USD). Models exceeding this will be filtered out."
    )
    max_request_price: float | None = Field(
        default=None,
        ge=0,
        description="Maximum price per request (USD). Models exceeding this will be filtered out."
    )


class WebConfig(BaseModel):
    """Web management interface configuration."""
    enabled: bool = True
    port: int = Field(default=9000, ge=1, le=65535)
    host: str = "127.0.0.1"
    admin_username: str = "admin"
    model_price_limits: ModelPriceLimits | None = Field(
        default=None,
        description="Price limits for filtering available models"
    )


class HostConfig(BaseModel):
    """Remote host configuration for deployment."""

    ip: str = ""
    ssh_user: str = "openclaw"
    ssh_port: int = Field(default=2222, ge=1, le=65535)
    ssh_key: Path = Path("~/.ssh/openclaw-lightsail.pem")
    tailscale_ip: str = ""
    remote_repo_path: str = "/home/openclaw/openclaw"
    remote_home: str = "/home/openclaw"
    initial_ssh_user: str = "ubuntu"
    initial_ssh_port: int = Field(default=22, ge=1, le=65535)
    secrets_dir: Path = Path("~/.config/openclaw/secrets")

    # AWS Lightsail provisioning
    aws_region: str = "us-east-2"
    instance_name: str = ""
    key_pair_name: str = ""
    blueprint_id: str = "ubuntu_24_04"
    bundle_id: str = "small_3_0"
    static_ip_name: str = ""

    @field_validator("ssh_key", "secrets_dir")
    @classmethod
    def expand_home(cls, v: Path) -> Path:
        return v.expanduser()


class Config(BaseModel):
    clawctl: ClawctlSettings
    users: list[UserConfig] = []
    web: WebConfig | None = None
    host: HostConfig | None = None

    model_config = {"extra": "allow"}

    def get_user(self, name: str) -> UserConfig | None:
        """Get a user config by name."""
        for user in self.users:
            if user.name == name:
                return user
        return None

    def get_usernames(self) -> list[str]:
        """Get all configured usernames."""
        return [u.name for u in self.users]
