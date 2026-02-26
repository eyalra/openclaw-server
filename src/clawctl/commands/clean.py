"""clawctl clean — tear down infrastructure and optionally user data."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

from clawlib.core.config import find_config_path, load_config_or_exit
from clawlib.core.docker_manager import DockerManager

console = Console()


def clean(
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
    all_data: Annotated[
        bool,
        typer.Option("--all", help="Also remove persistent user data (secrets, backups, workspaces)"),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompt"),
    ] = False,
) -> None:
    """Remove containers, networks, and build artifacts.

    By default only removes disposable infrastructure (build/, containers,
    networks, clawctl.toml).  Pass --all to also delete the persistent data/
    directory (user secrets, workspaces, backups).
    """
    cfg = load_config_or_exit(config)
    resolved_config = find_config_path(config)
    config_name = resolved_config.name if resolved_config else "clawctl.toml"

    if not yes:
        console.print("[bold red]This will:[/bold red]")
        console.print("  • Stop and remove all OpenClaw containers")
        console.print("  • Remove all Docker networks")
        console.print(f"  • Delete build directory ({cfg.clawctl.build_root})")
        console.print(f"  • Delete {config_name}")
        if all_data:
            console.print(
                f"  • [bold red]Delete ALL user data[/bold red] ({cfg.clawctl.data_root}) "
                "— secrets, workspaces, backups"
            )
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

    # 2. Remove build directory (disposable infrastructure)
    build_root = cfg.clawctl.build_root
    if build_root.is_dir():
        shutil.rmtree(build_root)
        console.print(f"[yellow]Removed[/yellow] {build_root}")

    # 3. Optionally remove data directory (persistent user state)
    if all_data:
        data_root = cfg.clawctl.data_root
        if data_root.is_dir():
            shutil.rmtree(data_root)
            console.print(f"[red]Removed[/red] {data_root}")

    # 4. Remove config file
    config_file = find_config_path(config)
    if config_file and config_file.is_file():
        config_file.unlink()
        console.print(f"[yellow]Removed[/yellow] {config_file.name}")

    if all_data:
        console.print("[green]Full clean complete — everything removed.[/green]")
    else:
        console.print("[green]Clean complete — infrastructure removed, user data preserved.[/green]")
        console.print("[dim]Run with --all to also remove user data.[/dim]")
