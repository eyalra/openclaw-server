"""clawctl backup — manage backups."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

from clawlib.core.backup_manager import BackupManager
from clawlib.core.config import find_config_path, load_config_or_exit

console = Console()


def backup_run(
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Run an immediate backup of all users."""
    cfg = load_config_or_exit(config)
    manager = BackupManager(cfg)

    with console.status("Running backup..."):
        results = manager.backup_all()

    for username, committed in results.items():
        if committed:
            console.print(f"  [green]{username}[/green]: backed up")
        else:
            console.print(f"  [dim]{username}[/dim]: no changes")


def schedule_start(
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Start the periodic backup daemon."""
    config_path = find_config_path(config)
    cfg = load_config_or_exit(config)
    manager = BackupManager(cfg)

    if manager.is_daemon_running():
        console.print("[yellow]Backup daemon is already running.[/yellow]")
        raise typer.Exit()

    pid = manager.start_daemon(config_path)
    interval = cfg.clawctl.backup.interval_minutes
    console.print(
        f"[green]Backup daemon started[/green] (PID {pid}, every {interval} min)"
    )


def schedule_stop(
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Stop the periodic backup daemon."""
    cfg = load_config_or_exit(config)
    manager = BackupManager(cfg)

    if manager.stop_daemon():
        console.print("[green]Backup daemon stopped.[/green]")
    else:
        console.print("[dim]Backup daemon was not running.[/dim]")


def schedule_status(
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Check if the backup daemon is running."""
    cfg = load_config_or_exit(config)
    manager = BackupManager(cfg)

    if manager.is_daemon_running():
        pid = int(manager.paths.backup_pid_file.read_text().strip())
        console.print(f"[green]Backup daemon is running[/green] (PID {pid})")
    else:
        console.print("[dim]Backup daemon is not running.[/dim]")
