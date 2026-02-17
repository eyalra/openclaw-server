"""clawctl status — show status of all containers."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from clawctl.core.config import load_config_or_exit
from clawctl.core.docker_manager import DockerManager
from clawctl.core.paths import Paths
from clawctl.core.secrets import SecretsManager
from clawctl.core.user_manager import GATEWAY_TOKEN_SECRET_NAME

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
    secrets_mgr = SecretsManager(Paths(cfg.clawctl.data_root))
    statuses = docker.get_all_statuses()

    table = Table(title="Container Status")
    table.add_column("User", style="bold")
    table.add_column("Status")
    table.add_column("URL")

    for user in cfg.users:
        info = statuses.get(user.name, {"status": "unknown", "port": "-"})
        st = info["status"]
        style = "green" if st == "running" else "red" if st == "exited" else "dim"

        url = "-"
        if st == "running" and info["port"] != "-":
            token = secrets_mgr.read_secret(user.name, GATEWAY_TOKEN_SECRET_NAME)
            url = f"http://localhost:{info['port']}"
            if token:
                url += f"?token={token}"

        table.add_row(
            user.name,
            f"[{style}]{st}[/{style}]",
            url,
        )

    console.print(table)
