"""clawctl web command - Start the web management interface."""

from __future__ import annotations

import getpass
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Optional

import bcrypt
import typer
from rich.console import Console

from clawlib.core.config import find_config_path, load_config_or_exit
from clawlib.core.paths import Paths

console = Console()


def web_start(
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
    port: Annotated[
        Optional[int],
        typer.Option("--port", "-p", help="Port to run web interface on"),
    ] = None,
    host: Annotated[
        Optional[str],
        typer.Option("--host", help="Host to bind to"),
    ] = None,
    background: Annotated[
        bool,
        typer.Option("--background", "-d", help="Run in background (daemon mode)"),
    ] = False,
) -> None:
    """Start the web management interface (dashboard for instances, models, Discord pairing)."""
    # Find config path
    config_path = find_config_path(config)
    if config_path:
        cfg = load_config_or_exit(config)
        # Use port from config if not specified
        if port is None and hasattr(cfg, 'web') and cfg.web:
            port = cfg.web.port
        if host is None and hasattr(cfg, 'web') and cfg.web:
            host = cfg.web.host
    else:
        cfg = None
    
    # Defaults
    port = port or int(os.environ.get("WEB_PORT", "9000"))
    host = host or os.environ.get("WEB_HOST", "0.0.0.0")
    
    # Build command - run the server module directly
    cmd = [sys.executable, "-m", "clawctl_web.server"]
    if config_path:
        cmd.append(str(config_path))
    
    env = os.environ.copy()
    env["WEB_PORT"] = str(port)
    env["WEB_HOST"] = host
    
    if background:
        # Run in background
        console.print(f"[yellow]Starting web interface in background on {host}:{port}...[/yellow]")
        with open(os.devnull, 'w') as devnull:
            process = subprocess.Popen(
                cmd,
                env=env,
                stdout=devnull,
                stderr=devnull,
                start_new_session=True,
            )
        console.print(f"[green]Web interface started (PID: {process.pid})[/green]")
        console.print(f"[green]Access at: http://{host}:{port}[/green]")
    else:
        # Run in foreground
        console.print(f"[yellow]Starting web interface on {host}:{port}...[/yellow]")
        console.print(f"[green]Access at: http://{host}:{port}[/green]")
        console.print("[dim]Press Ctrl+C to stop[/dim]")
        try:
            subprocess.run(cmd, env=env)
        except KeyboardInterrupt:
            console.print("\n[yellow]Stopping web interface...[/yellow]")
            sys.exit(0)


def web_set_password(
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
    password: Annotated[
        Optional[str],
        typer.Option("--password", "-p", help="Password to set (prompts if not provided)"),
    ] = None,
) -> None:
    """Set or change the web admin password (stored as bcrypt hash in data/secrets/)."""
    cfg = load_config_or_exit(config)
    paths = Paths(cfg.clawctl.data_root, cfg.clawctl.build_root)
    
    # Get password
    if password:
        password_value = password
    else:
        password_value = getpass.getpass("Enter admin password: ")
        password_confirm = getpass.getpass("Confirm password: ")
        if password_value != password_confirm:
            console.print("[red]Passwords do not match![/red]")
            raise typer.Abort()
    
    if not password_value:
        console.print("[red]Password cannot be empty![/red]")
        raise typer.Abort()
    
    # Create password file directory
    password_dir = paths.data_root / "secrets" / "web_admin"
    password_dir.mkdir(parents=True, exist_ok=True)
    
    # Hash and write password
    hashed = bcrypt.hashpw(password_value.encode("utf-8"), bcrypt.gensalt())
    password_file = password_dir / "password"
    password_file.write_bytes(hashed)
    password_file.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
    
    console.print(f"[green]✓ Password set successfully[/green]")
    console.print(f"[dim]Password file: {password_file}[/dim]")
    console.print(f"[dim]Username: admin[/dim]")
    
    # If service is running, suggest restart
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "--quiet", "clawctl-web"],
            capture_output=True,
        )
        if result.returncode == 0:
            console.print("\n[yellow]Note: Web service is running. Restart to apply changes:[/yellow]")
            console.print("[dim]  sudo systemctl restart clawctl-web[/dim]")
    except FileNotFoundError:
        pass  # systemctl not available, probably not running as service
