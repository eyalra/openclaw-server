"""clawctl status — show status of all containers."""

from __future__ import annotations

import subprocess
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


def _get_tailscale_ip() -> str | None:
    """Get Tailscale IPv4 address if available."""
    try:
        result = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        )
        ip = result.stdout.strip()
        return ip if ip else None
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None


def status(
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Show the status of all user containers."""
    cfg = load_config_or_exit(config)
    docker = DockerManager(cfg)
    secrets_mgr = SecretsManager(Paths(cfg.clawctl.data_root, cfg.clawctl.build_root))
    statuses = docker.get_all_statuses()
    tailscale_ip = _get_tailscale_ip()

    # Collect URLs for full display
    full_urls = {}

    # Create compact table
    table = Table(title="Container Status")
    table.add_column("User", style="bold")
    table.add_column("Status")
    table.add_column("Port")

    for user in cfg.users:
        info = statuses.get(user.name, {"status": "unknown", "port": "-"})
        st = info["status"]
        style = "green" if st == "running" else "red" if st == "exited" else "dim"
        port = info["port"] if info["port"] != "-" else "-"

        # Collect full URLs for printing below
        if st == "running" and port != "-":
            token = secrets_mgr.read_secret(user.name, GATEWAY_TOKEN_SECRET_NAME)
            if not token:
                token = secrets_mgr.read_secret(user.name, "gateway_token")
            
            urls = []
            if token:
                urls.append(f"http://localhost:{port}?token={token}")
                if tailscale_ip:
                    urls.append(f"http://{tailscale_ip}:{port}?token={token}")
            else:
                urls.append(f"http://localhost:{port}")
                if tailscale_ip:
                    urls.append(f"http://{tailscale_ip}:{port}")
            full_urls[user.name] = urls

        table.add_row(
            user.name,
            f"[{style}]{st}[/{style}]",
            str(port),
        )

    console.print(table)
    
    # Print full URLs without truncation
    if full_urls:
        console.print()
        console.print("[bold]Dashboard URLs:[/bold]")
        for username, urls in full_urls.items():
            console.print(f"  [bold]{username}:[/bold]")
            for url in urls:
                console.print(f"    {url}")
