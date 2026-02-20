"""clawctl logs — tail container logs."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

from clawlib.core.config import load_config_or_exit
from clawlib.core.docker_manager import DockerManager

console = Console()


def logs(
    name: Annotated[str, typer.Argument(help="Username whose logs to view")],
    follow: Annotated[bool, typer.Option("--follow", "-f", help="Follow log output")] = False,
    tail: Annotated[int, typer.Option("--tail", "-n", help="Number of lines to show")] = 100,
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """View logs from a user's container."""
    cfg = load_config_or_exit(config)
    docker = DockerManager(cfg)

    try:
        for line in docker.stream_logs(name, follow=follow, tail=tail):
            typer.echo(line, nl=False)
    except KeyboardInterrupt:
        pass
