"""clawctl status — show status of all containers."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from clawlib.core.config import load_config_or_exit
from clawlib.core.docker_manager import DockerManager
from clawlib.core.paths import Paths
from clawlib.core.secrets import SecretsManager
from clawlib.core.user_manager import GATEWAY_TOKEN_SECRET_NAME
import json

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


def _get_tailscale_hostname() -> str | None:
    """Get Tailscale MagicDNS hostname if available."""
    try:
        result = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        )
        status_data = json.loads(result.stdout)
        self_info = status_data.get("Self", {})
        dns_name = self_info.get("DNSName", "")
        return dns_name.rstrip(".") if dns_name else None
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return None


def _is_tailscale_serve_enabled(username: str, paths: Paths) -> bool:
    """Check if Tailscale Serve is enabled for a user by reading their openclaw.json."""
    try:
        config_path = paths.user_openclaw_config(username)
        if not config_path.exists():
            return False
        config_data = json.loads(config_path.read_text())
        gateway = config_data.get("gateway", {})
        tailscale_config = gateway.get("tailscale", {})
        return tailscale_config.get("mode") == "serve"
    except Exception:
        return False


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
            
            # Check if Tailscale Serve is enabled
            paths = Paths(cfg.clawctl.data_root, cfg.clawctl.build_root)
            tailscale_serve_enabled = _is_tailscale_serve_enabled(user.name, paths)
            tailscale_hostname = _get_tailscale_hostname() if tailscale_serve_enabled else None
            
            urls = []
            if token:
                token_param = f"?token={token}"
                if tailscale_serve_enabled and tailscale_hostname:
                    # Tailscale Serve uses HTTPS and MagicDNS
                    urls.append(f"https://{tailscale_hostname}:443{token_param}")
                if tailscale_ip:
                    # Fallback to Tailscale IP (HTTP for Docker port mapping, HTTPS for Serve)
                    protocol = "https" if tailscale_serve_enabled else "http"
                    port_for_url = 443 if tailscale_serve_enabled else port
                    urls.append(f"{protocol}://{tailscale_ip}:{port_for_url}{token_param}")
                # Localhost URL (for local access)
                urls.append(f"http://localhost:{port}{token_param}")
            else:
                if tailscale_serve_enabled and tailscale_hostname:
                    urls.append(f"https://{tailscale_hostname}:443")
                if tailscale_ip:
                    protocol = "https" if tailscale_serve_enabled else "http"
                    port_for_url = 443 if tailscale_serve_enabled else port
                    urls.append(f"{protocol}://{tailscale_ip}:{port_for_url}")
                urls.append(f"http://localhost:{port}")
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
