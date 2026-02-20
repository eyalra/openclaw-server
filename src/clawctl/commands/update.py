"""clawctl update — update OpenClaw version across containers."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

from clawlib.core.config import load_config_or_exit
from clawlib.core.docker_manager import DockerManager

console = Console()


def update(
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Rebuild the Docker image and recreate all containers.

    Uses the openclaw_version from the config file. Update the version
    in clawctl.toml before running this command.
    """
    cfg = load_config_or_exit(config)
    docker = DockerManager(cfg)

    console.print(
        f"Updating to OpenClaw [bold]{cfg.clawctl.openclaw_version}[/bold]..."
    )

    if not typer.confirm("This will rebuild the image and restart all containers. Continue?"):
        raise typer.Abort()

    with console.status("Rebuilding image and restarting containers..."):
        updated = docker.rebuild_all()

    if updated:
        console.print(
            f"[green]Updated {len(updated)} containers:[/green] {', '.join(updated)}"
        )
    else:
        console.print("[dim]No containers to update.[/dim]")
