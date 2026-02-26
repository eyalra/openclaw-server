"""clawctl shared-collections — manage shared document collections."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from clawlib.core.shared_collections_manager import SharedCollectionsManager
from clawlib.core.config import find_config_path, load_config_or_exit

console = Console()


def sync(
    collection_name: Annotated[
        Optional[str],
        typer.Argument(help="Collection name to sync (optional, syncs all if not specified)"),
    ] = None,
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Sync shared document collections from S3 or local source to all user containers."""
    cfg = load_config_or_exit(config)

    if not cfg.clawctl.shared_collections:
        console.print("[red]Shared collections not configured.[/red]")
        console.print("Add [clawctl.shared_collections] section to your config file.")
        raise typer.Exit(1)

    manager = SharedCollectionsManager(cfg)

    if collection_name:
        # Sync single collection
        with console.status(f"Syncing collection '{collection_name}'..."):
            success = manager.sync_collection(collection_name)
        if success:
            console.print(f"[green]Successfully synced collection '{collection_name}'[/green]")
        else:
            console.print(f"[red]Failed to sync collection '{collection_name}'[/red]")
            raise typer.Exit(1)
    else:
        # Sync all collections
        with console.status("Syncing all collections..."):
            results = manager.sync_all()

        if not results:
            console.print("[yellow]No collections configured.[/yellow]")
            return

        for name, success in results.items():
            if success:
                console.print(f"  [green]{name}[/green]: synced")
            else:
                console.print(f"  [red]{name}[/red]: failed")


def list_collections(
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """List configured shared collections and their status."""
    cfg = load_config_or_exit(config)

    if not cfg.clawctl.shared_collections:
        console.print("[yellow]Shared collections not configured.[/yellow]")
        return

    shared_config = cfg.clawctl.shared_collections
    manager = SharedCollectionsManager(cfg)

    # Build a lookup from drive name → users restriction
    drive_users: dict[str, list[str] | None] = {}
    for name in shared_config.collections:
        drive_users[name] = None  # all users
    for d in shared_config.drives:
        drive_users[d.name] = d.users

    table = Table(title="Shared Drives")
    table.add_column("Drive", style="cyan")
    table.add_column("Access", style="dim")
    table.add_column("Source", style="dim")
    table.add_column("Status", justify="right")

    for drive_name in shared_config.all_drive_names:
        if shared_config.source_type == "s3":
            source = f"s3://{shared_config.s3_bucket}/{shared_config.s3_prefix.rstrip('/')}/{drive_name}/"
        else:
            source = str(shared_config.local_source_base / drive_name) if shared_config.local_source_base else "-"

        local_path = manager.paths.shared_collection_dir(drive_name)
        exists = local_path.exists() and local_path.is_dir()
        status = "[green]synced[/green]" if exists else "[dim]not synced[/dim]"

        users = drive_users.get(drive_name)
        access_str = "[green]all users[/green]" if users is None else ", ".join(users)

        table.add_row(drive_name, access_str, source, status)

    console.print(table)
    if shared_config.source_type == "s3":
        console.print(f"\n[dim]S3 Bucket:[/dim] {shared_config.s3_bucket}")
    console.print(f"[dim]Sync Schedule:[/dim] {shared_config.sync_schedule}")


def schedule_start(
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Start the periodic sync daemon."""
    config_path = find_config_path(config)
    cfg = load_config_or_exit(config)

    if not cfg.clawctl.shared_collections:
        console.print("[red]Shared collections not configured.[/red]")
        raise typer.Exit(1)

    manager = SharedCollectionsManager(cfg)

    if manager.is_daemon_running():
        console.print("[yellow]Sync daemon is already running.[/yellow]")
        raise typer.Exit()

    pid = manager.start_daemon(config_path)
    schedule_str = cfg.clawctl.shared_collections.sync_schedule
    console.print(
        f"[green]Sync daemon started[/green] (PID {pid}, schedule: {schedule_str})"
    )


def schedule_stop(
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Stop the periodic sync daemon."""
    cfg = load_config_or_exit(config)

    if not cfg.clawctl.shared_collections:
        console.print("[yellow]Shared collections not configured.[/yellow]")
        return

    manager = SharedCollectionsManager(cfg)

    if manager.stop_daemon():
        console.print("[green]Sync daemon stopped.[/green]")
    else:
        console.print("[dim]Sync daemon was not running.[/dim]")


def schedule_status(
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Check if the sync daemon is running."""
    cfg = load_config_or_exit(config)

    if not cfg.clawctl.shared_collections:
        console.print("[yellow]Shared collections not configured.[/yellow]")
        return

    manager = SharedCollectionsManager(cfg)

    if manager.is_daemon_running():
        pid_file = manager.paths.build_root / ".shared-collections-sync.pid"
        pid = int(pid_file.read_text().strip())
        console.print(f"[green]Sync daemon is running[/green] (PID {pid})")
    else:
        console.print("[dim]Sync daemon is not running.[/dim]")
