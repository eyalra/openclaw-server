"""clawctl clean — tear down all resources and remove build artifacts."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

from clawctl.core.config import load_config_or_exit
from clawctl.core.docker_manager import DockerManager

console = Console()


def clean(
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompt"),
    ] = False,
) -> None:
    """Remove all containers, networks, build data, and config.

    Restores the project to a fresh pre-init state.
    """
    cfg = load_config_or_exit(config)

    if not yes:
        console.print("[bold red]This will:[/bold red]")
        console.print("  • Stop and remove all OpenClaw containers")
        console.print("  • Remove all Docker networks")
        console.print("  • Delete the build/ directory (all user data, secrets, backups)")
        console.print("  • Delete clawctl.toml")
        console.print()
        if not typer.confirm("Are you sure?", default=False):
            raise typer.Abort()

    docker = DockerManager(cfg)

    # 1. Remove all user containers and networks
    removed = []
    for user in cfg.users:
        if docker.container_exists(user.name):
            docker.remove_container(user.name)
        docker.remove_network(user.name)
        removed.append(user.name)

    if removed:
        console.print(
            f"[yellow]Removed containers/networks:[/yellow] {', '.join(removed)}"
        )

    # 2. Remove build directory
    data_root = cfg.clawctl.data_root
    if data_root.is_dir():
        shutil.rmtree(data_root)
        console.print(f"[yellow]Removed[/yellow] {data_root}")

    # 3. Remove config file
    config_file = Path("clawctl.toml")
    if config_file.is_file():
        config_file.unlink()
        console.print("[yellow]Removed[/yellow] clawctl.toml")

    console.print("[green]Clean complete — back to a fresh state.[/green]")
