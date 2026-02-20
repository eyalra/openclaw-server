"""Generate per-user openclaw.json configuration files."""

from __future__ import annotations

import json
from pathlib import Path

from clawlib.models.config import DefaultsConfig, UserConfig


def generate_openclaw_config(
    user: UserConfig, 
    defaults: DefaultsConfig, 
    *, 
    gateway_token: str | None = None,
    provider: str | None = None,  # Optional: "openrouter" or "anthropic" to determine routing
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

    # Convert model to OpenRouter format if provider is openrouter
    # OpenClaw requires models to use the format: openrouter/<author>/<slug>
    # Examples:
    #   - openai/gpt-5-nano -> openrouter/openai/gpt-5-nano (if provider is openrouter)
    #   - google/gemini-2.5-flash-lite -> openrouter/google/gemini-2.5-flash-lite (if provider is openrouter)
    #   - anthropic/claude-sonnet-4.5 -> openrouter/anthropic/claude-sonnet-4.5 (if provider is openrouter)
    # Models that already start with "openrouter/" are left as-is
    # If provider is not openrouter (e.g., "anthropic"), models are used as-is
    
    if model.startswith("openrouter/"):
        # Already in correct format
        openrouter_model = model
    elif provider == "openrouter" and "/" in model:
        # Provider is openrouter and model has provider/model format - add openrouter/ prefix
        # This covers: openai/*, google/*, anthropic/*, meta/*, etc. when using OpenRouter
        openrouter_model = f"openrouter/{model}"
    else:
        # Provider is not openrouter, or model doesn't need prefix - use as-is
        # This allows direct provider access (e.g., anthropic/claude-sonnet-4.5 for direct Anthropic)
        openrouter_model = model

    config: dict = {
        "agents": {
            "defaults": {
                "model": {
                    "primary": openrouter_model,
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

    if user.skills.gog.enabled and user.skills.gog.email:
        config.setdefault("hooks", {})["gmail"] = {"account": user.skills.gog.email}

    return config


def write_openclaw_config(
    user: UserConfig,
    defaults: DefaultsConfig,
    path: Path,
    *,
    gateway_token: str | None = None,
    provider: str | None = None,
) -> None:
    """Write the openclaw.json file for a user."""
    config = generate_openclaw_config(user, defaults, gateway_token=gateway_token, provider=provider)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n")
