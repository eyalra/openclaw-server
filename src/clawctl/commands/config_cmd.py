"""clawctl config — configuration utilities."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

from clawctl.core.config import find_config_path, load_config

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
