"""clawctl init — initialize a deployment."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from clawctl.core.paths import Paths

console = Console()


def init(
    data_root: Annotated[
        Path,
        typer.Option("--data-root", "-d", help="Root directory for all user data"),
    ] = Path("/opt/openclaw"),
) -> None:
    """Initialize a new clawctl deployment.

    Creates the data directory structure and a template config file.
    """
    paths = Paths(data_root)
    paths.ensure_base_dirs()

    # Copy example config to working directory if none exists
    config_dest = Path("clawctl.toml")
    if not config_dest.exists():
        example = Path(__file__).resolve().parents[2] / "config" / "clawctl.example.toml"

        # Fall back to package-adjacent path
        if not example.exists():
            example = Path(__file__).resolve().parents[3] / "config" / "clawctl.example.toml"

        if example.exists():
            shutil.copy2(example, config_dest)
            # Update data_root in the generated config
            text = config_dest.read_text()
            text = text.replace(
                'data_root = "/opt/openclaw"',
                f'data_root = "{data_root}"',
            )
            config_dest.write_text(text)
            console.print(f"Created [bold]clawctl.toml[/bold] with data_root={data_root}")
        else:
            console.print(
                "[yellow]Warning:[/yellow] Could not find example config template. "
                "Create clawctl.toml manually."
            )
    else:
        console.print("[dim]clawctl.toml already exists, skipping.[/dim]")

    console.print(f"Data directory initialized at [bold]{data_root}[/bold]")
    console.print()
    console.print("Next steps:")
    console.print("  1. Edit [bold]clawctl.toml[/bold] to add users and configure channels")
    console.print("  2. Run [bold]clawctl user add <name>[/bold] to provision a user")
