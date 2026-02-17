"""Shared test fixtures for clawctl."""

from __future__ import annotations

from pathlib import Path

import pytest

from clawctl.models.config import (
    BackupConfig,
    ChannelDiscordConfig,
    ChannelSlackConfig,
    ChannelsConfig,
    ClawctlSettings,
    Config,
    DefaultsConfig,
    UserAgentConfig,
    UserConfig,
    UserSecretsConfig,
)


@pytest.fixture
def tmp_data_root(tmp_path: Path) -> Path:
    """A temporary data root directory."""
    root = tmp_path / "openclaw-data"
    root.mkdir()
    return root


@pytest.fixture
def sample_user() -> UserConfig:
    """A sample user configuration."""
    return UserConfig(
        name="testuser",
        channels=ChannelsConfig(
            slack=ChannelSlackConfig(
                enabled=True,
                bot_token_secret="slack_bot_token",
                app_token_secret="slack_app_token",
            ),
            discord=ChannelDiscordConfig(
                enabled=True,
                token_secret="discord_token",
            ),
        ),
        agent=UserAgentConfig(model="openrouter/z-ai/glm-4.5-air:free"),
        secrets=UserSecretsConfig(openrouter_api_key="openrouter_api_key"),
    )


@pytest.fixture
def sample_config(tmp_data_root: Path, sample_user: UserConfig) -> Config:
    """A sample full configuration."""
    return Config(
        clawctl=ClawctlSettings(
            data_root=tmp_data_root,
            openclaw_version="latest",
            image_name="openclaw-instance",
            backup=BackupConfig(
                enabled=True,
                interval_minutes=15,
            ),
            defaults=DefaultsConfig(),
        ),
        users=[sample_user],
    )


@pytest.fixture
def sample_config_toml(tmp_data_root: Path) -> str:
    """Sample config as TOML string."""
    return f"""\
[clawctl]
data_root = "{tmp_data_root}"
openclaw_version = "latest"
image_name = "openclaw-instance"

[clawctl.backup]
enabled = true
interval_minutes = 15

[[users]]
name = "testuser"

[users.secrets]
openrouter_api_key = "openrouter_api_key"

[users.channels.slack]
enabled = true
bot_token_secret = "slack_bot_token"
app_token_secret = "slack_app_token"

[users.channels.discord]
enabled = true
token_secret = "discord_token"
"""
