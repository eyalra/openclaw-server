"""clawctl maintenance — manage nightly maintenance (backup + restart)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

from clawlib.core.config import find_config_path, load_config_or_exit
from clawlib.core.maintenance_manager import MaintenanceManager

console = Console()


def maintenance_run(
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Run an immediate maintenance cycle (backup all users, then restart all containers)."""
    cfg = load_config_or_exit(config)
    manager = MaintenanceManager(cfg)

    with console.status("Running maintenance cycle (backup → restart)..."):
        results = manager.run_cycle()

    console.print()
    if results["backed_up"]:
        console.print(f"[green]✓[/green] Backed up: {', '.join(results['backed_up'])}")
    else:
        console.print("[dim]  No backup changes[/dim]")

    if results["restarted"]:
        console.print(f"[green]✓[/green] Restarted: {', '.join(results['restarted'])}")
    else:
        console.print("[dim]  No containers restarted[/dim]")

    if results["errors"]:
        console.print(f"[red]Errors:[/red] {', '.join(results['errors'])}")


def schedule_start(
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Start the nightly maintenance daemon."""
    config_path = find_config_path(config)
    cfg = load_config_or_exit(config)
    manager = MaintenanceManager(cfg)

    if manager.is_daemon_running():
        console.print("[yellow]Maintenance daemon is already running.[/yellow]")
        raise typer.Exit()

    pid = manager.start_daemon(config_path)
    restart_time = cfg.clawctl.maintenance.restart_time
    console.print(
        f"[green]Maintenance daemon started[/green] (PID {pid}, daily at {restart_time} UTC)"
    )


def schedule_stop(
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Stop the nightly maintenance daemon."""
    cfg = load_config_or_exit(config)
    manager = MaintenanceManager(cfg)

    if manager.stop_daemon():
        console.print("[green]Maintenance daemon stopped.[/green]")
    else:
        console.print("[dim]Maintenance daemon was not running.[/dim]")


def schedule_status(
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Check maintenance daemon status and show next/last run times."""
    cfg = load_config_or_exit(config)
    manager = MaintenanceManager(cfg)

    if manager.is_daemon_running():
        pid = int(manager.paths.maintenance_pid_file.read_text().strip())
        restart_time = cfg.clawctl.maintenance.restart_time
        console.print(
            f"[green]Maintenance daemon is running[/green] (PID {pid}, "
            f"scheduled daily at {restart_time} UTC)"
        )
    else:
        console.print("[dim]Maintenance daemon is not running.[/dim]")

    last_run = manager.get_last_run()
    if last_run:
        console.print(f"  Last run: {last_run}")
    else:
        console.print("  Last run: [dim]never[/dim]")
