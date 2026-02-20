"""clawctl start/stop/restart commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

from clawlib.core.config import load_config_or_exit
from clawlib.core.docker_manager import DockerManager

console = Console()


def start(
    name: Annotated[str, typer.Argument(help="Username whose container to start")],
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Start a user's container."""
    cfg = load_config_or_exit(config)
    docker = DockerManager(cfg)
    docker.start_container(name)
    console.print(f"[green]Started container for '{name}'.[/green]")


def stop(
    name: Annotated[str, typer.Argument(help="Username whose container to stop")],
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Stop a user's container."""
    cfg = load_config_or_exit(config)
    docker = DockerManager(cfg)
    docker.stop_container(name)
    console.print(f"[yellow]Stopped container for '{name}'.[/yellow]")


def restart(
    name: Annotated[str, typer.Argument(help="Username whose container to restart")],
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Restart a user's container."""
    cfg = load_config_or_exit(config)
    docker = DockerManager(cfg)
    docker.restart_container(name)
    console.print(f"[green]Restarted container for '{name}'.[/green]")


def start_all(
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Start all user containers."""
    cfg = load_config_or_exit(config)
    docker = DockerManager(cfg)
    started = docker.start_all()
    if started:
        console.print(f"[green]Started {len(started)} containers:[/green] {', '.join(started)}")
    else:
        console.print("[dim]No containers to start.[/dim]")


def stop_all(
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Stop all user containers."""
    cfg = load_config_or_exit(config)
    docker = DockerManager(cfg)
    stopped = docker.stop_all()
    if stopped:
        console.print(f"[yellow]Stopped {len(stopped)} containers:[/yellow] {', '.join(stopped)}")
    else:
        console.print("[dim]No containers to stop.[/dim]")
