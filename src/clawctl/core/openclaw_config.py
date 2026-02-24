"""Generate per-user openclaw.json configuration files."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from clawlib.models.config import DefaultsConfig, UserConfig


def _is_tailscale_available() -> bool:
    """Check if Tailscale is available for use.
    
    Note: This function is called during config generation, which happens on the HOST.
    For gateway containers, Tailscale Serve mode requires Tailscale to be installed
    INSIDE the container (not just the socket mounted). Since Tailscale isn't installed
    in containers, we disable Tailscale Serve mode for gateways and use Docker port mapping instead.
    
    Tailscale Serve is only used for the web management interface (which runs on the host).
    
    Can be disabled by setting TAILSCALE_ENABLED=false.
    """
    # Allow explicit opt-out via environment variable
    if os.getenv("TAILSCALE_ENABLED", "").lower() in ("false", "0", "no"):
        return False
    
    # Disable Tailscale Serve for gateway containers
    # Gateways run in Docker containers where Tailscale isn't installed.
    # Only the socket is mounted, but Tailscale Serve needs the binary to configure itself.
    # Use Docker port mapping instead for gateways.
    return False
    
    # Note: The code below is kept for reference but disabled.
    # If we install Tailscale in containers in the future, we can re-enable this:
    # tailscale_socket = Path("/var/run/tailscale/tailscaled.sock")
    # if tailscale_socket.exists() and tailscale_socket.is_socket():
    #     return True
    # return False


def generate_openclaw_config(
    user: UserConfig, defaults: DefaultsConfig, *, gateway_token: str | None = None, base_path: str | None = None
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
        base_path: Optional base path for reverse proxy setups. If None and using
            reverse proxy (not Tailscale Serve), auto-generates as "/gateway/{username}".
    """
    model = user.agent.model or defaults.model

    # Check if Tailscale is available for Serve mode
    use_tailscale_serve = _is_tailscale_available()
    
    # Determine basePath for reverse proxy
    # If not provided and using reverse proxy (not Tailscale Serve), auto-generate
    if base_path is None and not use_tailscale_serve:
        base_path = f"/gateway/{user.name}"

    gateway: dict = {
        "mode": "local",
        "port": 18789,
    }

    if use_tailscale_serve:
        # Tailscale Serve mode: bind to loopback, let Tailscale handle exposure
        gateway["bind"] = "loopback"  # 127.0.0.1 - only accessible via Tailscale Serve
        gateway["tailscale"] = {"mode": "serve"}
    else:
        # Docker port mapping mode: bind to lan for Docker NAT
        gateway["bind"] = "lan"  # 0.0.0.0 inside container for Docker networking
        # Trust Docker network ranges to allow WebSocket connections through NAT
        # Docker default bridge: 172.17.0.0/16, custom networks often use 172.18-30.0.0/16
        gateway["trustedProxies"] = [
            "127.0.0.1",
            "::1",
            "172.17.0.0/16",  # Docker default bridge network
            "172.18.0.0/16",  # Docker custom networks
            "172.19.0.0/16",
            "172.20.0.0/16",
            "172.21.0.0/16",
            "172.22.0.0/16",
            "172.23.0.0/16",
            "172.24.0.0/16",
            "172.25.0.0/16",
            "172.26.0.0/16",
            "172.27.0.0/16",
            "172.28.0.0/16",
            "172.29.0.0/16",
            "172.30.0.0/16",
        ]

    if gateway_token:
        gateway["auth"] = {"mode": "token", "token": gateway_token}
        if use_tailscale_serve:
            # Enable Tailscale identity authentication (more secure)
            gateway["auth"]["allowTailscale"] = True
        control_ui_config: dict = {
            "enabled": True,
            "allowInsecureAuth": True,
            "dangerouslyDisableDeviceAuth": True,
            "allowedOrigins": ["*"],
        }
        if base_path:
            control_ui_config["basePath"] = base_path
        gateway["controlUi"] = control_ui_config

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
    # Don't include Slack in config if disabled - OpenClaw doctor will auto-enable it if present

    if user.channels.discord.enabled:
        config["channels"]["discord"] = {
            "enabled": True,
            "groupPolicy": "open",  # Allow all channels/DMs by default
            # Token read from DISCORD_TOKEN env var
        }

    if user.skills.gog.enabled and user.skills.gog.email:
        config.setdefault("hooks", {})["gmail"] = {"account": user.skills.gog.email}

    # Add meta field to prevent gateway from treating this as an external write
    # The gateway checks for meta before overwriting config
    config["meta"] = {
        "lastTouchedVersion": "2026.2.21-2",  # Current OpenClaw version
        "lastTouchedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    }

    return config


def write_openclaw_config(
    user: UserConfig,
    defaults: DefaultsConfig,
    path: Path,
    *,
    gateway_token: str | None = None,
    base_path: str | None = None,
) -> None:
    """Write the openclaw.json file for a user."""
    config = generate_openclaw_config(user, defaults, gateway_token=gateway_token, base_path=base_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n")
    try:
        os.chmod(path, 0o644)
        os.chmod(path.parent, 0o755)
    except OSError:
        pass
