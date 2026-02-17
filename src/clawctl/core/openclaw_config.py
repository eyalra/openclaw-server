"""Generate per-user openclaw.json configuration files."""

from __future__ import annotations

import json
from pathlib import Path

from clawctl.models.config import DefaultsConfig, UserConfig


def generate_openclaw_config(
    user: UserConfig, defaults: DefaultsConfig, *, gateway_token: str | None = None
) -> dict:
    """Generate the openclaw.json content for a user.

    The config tells OpenClaw how to run inside its container.
    Channel tokens come from environment variables (injected by entrypoint.sh),
    not from this config file.

    Args:
        user: User configuration.
        defaults: Global default settings.
        gateway_token: The gateway auth token.  When provided the config
            uses token-based auth with ``controlUi.allowInsecureAuth`` so
            the browser dashboard works through Docker NAT without pairing.
    """
    model = user.agent.model or defaults.model

    gateway: dict = {
        "mode": "local",
        "port": 18789,
        "bind": "lan",  # 0.0.0.0 inside container for Docker networking
    }

    if gateway_token:
        gateway["auth"] = {"mode": "token", "token": gateway_token}
        gateway["controlUi"] = {"allowInsecureAuth": True}

    config: dict = {
        "agents": {
            "defaults": {
                "model": {
                    "primary": model,
                },
            },
        },
        "gateway": gateway,
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
    user: UserConfig,
    defaults: DefaultsConfig,
    path: Path,
    *,
    gateway_token: str | None = None,
) -> None:
    """Write the openclaw.json file for a user."""
    config = generate_openclaw_config(user, defaults, gateway_token=gateway_token)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n")
