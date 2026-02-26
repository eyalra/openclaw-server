"""Re-export from clawlib — single source of truth for openclaw.json generation."""

from clawlib.core.openclaw_config import (  # noqa: F401
    generate_openclaw_config,
    write_openclaw_config,
    _get_tailscale_hostname,
    _is_tailscale_available,
)
