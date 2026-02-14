"""clawctl status — show status of all containers."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from clawctl.core.config import load_config_or_exit
from clawctl.core.docker_manager import DockerManager

console = Console()


def status(
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Show the status of all user containers."""
    cfg = load_config_or_exit(config)
    docker = DockerManager(cfg)
    statuses = docker.get_all_statuses()

    table = Table(title="Container Status")
    table.add_column("User", style="bold")
    table.add_column("Container")
    table.add_column("Status")
    table.add_column("Port")

    for user in cfg.users:
        info = statuses.get(user.name, {"status": "unknown", "port": "-"})
        st = info["status"]
        style = "green" if st == "running" else "red" if st == "exited" else "dim"

        table.add_row(
            user.name,
            f"openclaw-{user.name}",
            f"[{style}]{st}[/{style}]",
            info["port"],
        )

    console.print(table)
