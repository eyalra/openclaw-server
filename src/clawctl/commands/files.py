"""clawctl files — push, list, and manage per-user files."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from clawlib.core.config import load_config_or_exit
from clawlib.core.file_manager import FileManager
from clawlib.core.paths import Paths

console = Console()


def _get_file_manager(config_path: Path | None) -> FileManager:
    cfg = load_config_or_exit(config_path)
    paths = Paths(cfg.clawctl.data_root, cfg.clawctl.build_root)
    return FileManager(paths)


def files_push(
    username: Annotated[str, typer.Argument(help="Target username")],
    source: Annotated[Path, typer.Argument(help="Local file or directory to push")],
    dest: Annotated[
        Optional[str],
        typer.Option("--dest", "-d", help="Destination path inside /mnt/files"),
    ] = None,
    executable: Annotated[
        bool,
        typer.Option("--executable", "-x", help="Mark file as executable (755)"),
    ] = False,
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Push a file or directory to a user's instance."""
    fm = _get_file_manager(config)
    source = Path(source).resolve()

    try:
        if source.is_dir():
            pushed = fm.push_directory(username, source, dest)
            console.print(f"[green]Pushed {len(pushed)} files to {username}[/green]")
            for p in pushed:
                console.print(f"  {p}")
        else:
            entry = fm.push_file(username, source, dest, executable=executable)
            rel = dest or source.name
            console.print(
                f"[green]Pushed[/green] {rel} → {username} "
                f"({entry['size']} bytes, sha256:{entry['sha256'][:12]}…)"
            )
    except (ValueError, FileNotFoundError, NotADirectoryError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    console.print(
        "\n[dim]Note: If the container was created before file push support was added, "
        "run `clawctl instance restart {username}` to pick up the /mnt/files mount.[/dim]"
    )


def files_list(
    username: Annotated[str, typer.Argument(help="Username")],
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """List files pushed to a user's instance."""
    fm = _get_file_manager(config)
    files = fm.list_files(username)

    if not files:
        console.print(f"[dim]No files pushed for {username}.[/dim]")
        return

    table = Table(title=f"Files for {username}")
    table.add_column("Path", style="cyan")
    table.add_column("Size", justify="right")
    table.add_column("SHA256", style="dim")
    table.add_column("Exec", justify="center")
    table.add_column("Pushed", style="dim")

    for rel_path, entry in sorted(files.items()):
        size_str = _fmt_size(entry.get("size", 0))
        sha = entry.get("sha256", "?")[:12] + "…"
        exe = "x" if entry.get("executable") else ""
        pushed = entry.get("pushed_at", "?")
        table.add_row(rel_path, size_str, sha, exe, pushed)

    console.print(table)


def files_remove(
    username: Annotated[str, typer.Argument(help="Username")],
    path: Annotated[str, typer.Argument(help="Relative path of the file to remove")],
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Remove a single pushed file from a user's instance."""
    fm = _get_file_manager(config)

    try:
        if fm.remove_file(username, path):
            console.print(f"[green]Removed[/green] {path} from {username}")
        else:
            console.print(f"[yellow]File not found:[/yellow] {path}")
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


def files_remove_all(
    username: Annotated[str, typer.Argument(help="Username")],
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation"),
    ] = False,
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Remove all pushed files for a user."""
    if not yes:
        confirm = typer.confirm(f"Remove ALL pushed files for {username}?")
        if not confirm:
            raise typer.Abort()

    fm = _get_file_manager(config)
    count = fm.remove_all(username)
    console.print(f"[green]Removed {count} entries for {username}[/green]")


def files_verify(
    username: Annotated[str, typer.Argument(help="Username")],
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Verify integrity of pushed files against their manifest checksums."""
    fm = _get_file_manager(config)
    results = fm.verify_integrity(username)

    if not results:
        console.print(f"[dim]No files to verify for {username}.[/dim]")
        return

    all_ok = True
    for rel_path, status in sorted(results.items()):
        if status == "ok":
            console.print(f"  [green]OK[/green]       {rel_path}")
        elif status == "missing":
            console.print(f"  [red]MISSING[/red]  {rel_path}")
            all_ok = False
        else:
            console.print(f"  [red]MISMATCH[/red] {rel_path}")
            all_ok = False

    if all_ok:
        console.print(f"\n[green]All {len(results)} files verified OK.[/green]")
    else:
        console.print("\n[red]Integrity check failed.[/red]")
        raise typer.Exit(1)


def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"
