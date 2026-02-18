"""clawctl init — initialize a deployment."""

from __future__ import annotations

import shutil
from pathlib import Path

import typer
from rich.console import Console

from clawctl.core.paths import Paths

console = Console()

# Resolve the project-level config/ directory from this source file
_PACKAGE_ROOT = Path(__file__).resolve().parents[2]  # src/clawctl/commands -> src/clawctl -> src
_PROJECT_ROOT = _PACKAGE_ROOT.parent  # src -> project root


def _find_example_config() -> Path | None:
    """Find the example config template relative to the project."""
    candidates = [
        _PROJECT_ROOT / "config" / "clawctl.example.toml",
        _PACKAGE_ROOT / "config" / "clawctl.example.toml",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def init() -> None:
    """Initialize a new clawctl deployment in the current directory.

    Creates build/ (infrastructure) and data/ (persistent user state)
    directories, plus a template config file.
    """
    build_dir = Path("build").resolve()
    data_dir = Path("data").resolve()
    paths = Paths(data_dir, build_dir)
    paths.ensure_base_dirs()

    # Copy example config to working directory if none exists
    config_dest = Path("clawctl.toml")
    if not config_dest.exists():
        example = _find_example_config()
        if example is not None:
            shutil.copy2(example, config_dest)
            console.print("Created [bold]clawctl.toml[/bold]")
        else:
            console.print(
                "[yellow]Warning:[/yellow] Could not find example config template. "
                "Create clawctl.toml manually."
            )
    else:
        console.print("[dim]clawctl.toml already exists, skipping.[/dim]")

    console.print(f"Build directory at [bold]{build_dir}[/bold] (infrastructure, disposable)")
    console.print(f"Data directory at  [bold]{data_dir}[/bold] (user state, persistent)")
    console.print()
    console.print("Next steps:")
    console.print("  1. Edit [bold]clawctl.toml[/bold] to add users and configure channels")
    console.print("  2. Run [bold]clawctl user add <name>[/bold] to provision a user")
