"""Generate per-user openclaw.json configuration files."""

from __future__ import annotations

import json
from pathlib import Path

from clawctl.models.config import DefaultsConfig, UserConfig


def generate_openclaw_config(user: UserConfig, defaults: DefaultsConfig) -> dict:
    """Generate the openclaw.json content for a user.

    The config tells OpenClaw how to run inside its container.
    Channel tokens come from environment variables (injected by entrypoint.sh),
    not from this config file.
    """
    model = user.agent.model or defaults.model
    config: dict = {
        "agents": {
            "defaults": {
                "model": {
                    "primary": model,
                },
            },
        },
        "gateway": {
            "mode": "local",
            "port": 18789,
            "bind": "lan",  # 0.0.0.0 inside container for Docker networking
            "auth": {"mode": "token"},  # token-only auth — avoids Docker NAT pairing issues
        },
        "channels": {},
    }

    if user.channels.slack.enabled:
        config["channels"]["slack"] = {
            "enabled": True,
            "mode": "socket",
            # Tokens read from SLACK_BOT_TOKEN / SLACK_APP_TOKEN env vars
        }

    if user.channels.discord.enabled:
        config["channels"]["discord"] = {
            "enabled": True,
            # Token read from DISCORD_TOKEN env var
        }

    return config


def write_openclaw_config(
    user: UserConfig, defaults: DefaultsConfig, path: Path
) -> None:
    """Write the openclaw.json file for a user."""
    config = generate_openclaw_config(user, defaults)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n")
