"""clawctl config — configuration utilities."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

from clawctl.core.config import find_config_path, load_config
from clawctl.core.openclaw_config import write_openclaw_config
from clawctl.core.paths import Paths
from clawctl.core.secrets import SecretsManager
from clawctl.core.user_manager import GATEWAY_TOKEN_SECRET_NAME

console = Console()


def validate(
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Validate the config file."""
    path = find_config_path(config)

    if path is None:
        console.print("[red]Config file not found.[/red]")
        raise typer.Exit(1)

    console.print(f"Validating [bold]{path}[/bold]...")

    try:
        cfg = load_config(path)
    except (ValueError, FileNotFoundError) as e:
        console.print(f"[red]Validation failed:[/red] {e}")
        raise typer.Exit(1) from None

    console.print(f"[green]Config is valid.[/green]")
    console.print(f"  Data root: {cfg.clawctl.data_root}")
    console.print(f"  OpenClaw version: {cfg.clawctl.openclaw_version}")
    console.print(f"  Users: {len(cfg.users)}")
    for user in cfg.users:
        channels = []
        if user.channels.slack.enabled:
            channels.append("slack")
        if user.channels.discord.enabled:
            channels.append("discord")
        console.print(f"    - {user.name} ({', '.join(channels) or 'no channels'})")


def regenerate(
    name: Annotated[str, typer.Argument(help="Username to regenerate config for")],
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Regenerate openclaw.json for a user from current clawctl.toml configuration.
    
    Useful when enabling/disabling channels or changing settings without recreating the user.
    The container will need to be restarted to pick up the new configuration.
    """
    from clawctl.core.config import load_config_or_exit
    
    cfg = load_config_or_exit(config)
    user = cfg.get_user(name)
    
    if user is None:
        console.print(
            f"[red]User '{name}' not found in config.[/red] "
            f"Add a [[users]] block with name = \"{name}\" to clawctl.toml first."
        )
        raise typer.Exit(1)
    
    paths = Paths(cfg.clawctl.data_root, cfg.clawctl.build_root)
    secrets_mgr = SecretsManager(paths)
    
    # Read gateway token (must exist)
    gateway_token = secrets_mgr.read_secret(name, GATEWAY_TOKEN_SECRET_NAME)
    if not gateway_token:
        console.print(
            f"[yellow]Warning: No gateway token found for '{name}'.[/yellow] "
            "Generating a new one..."
        )
        import secrets as secrets_module
        gateway_token = secrets_module.token_urlsafe(32)
        secrets_mgr.write_secret(name, GATEWAY_TOKEN_SECRET_NAME, gateway_token)
    
    # Regenerate openclaw.json
    config_path = paths.user_openclaw_config(name)
    write_openclaw_config(
        user,
        cfg.clawctl.defaults,
        config_path,
        gateway_token=gateway_token,
    )
    
    console.print(f"[green]✓[/green] Regenerated openclaw.json for '{name}'")
    console.print(f"  Config file: {config_path}")
    console.print()
    console.print("[yellow]Note:[/yellow] Restart the container to apply changes:")
    console.print(f"  [bold]clawctl restart {name}[/bold]")
