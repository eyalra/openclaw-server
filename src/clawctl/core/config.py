"""Config loading and validation for clawctl."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

from pydantic import ValidationError

from clawctl.models.config import Config

DEFAULT_CONFIG_PATHS = [
    Path("clawctl.toml"),
    Path.home() / ".config" / "clawctl" / "clawctl.toml",
]


def find_config_path(explicit_path: Path | None = None) -> Path | None:
    """Find the config file, checking explicit path, then defaults."""
    if explicit_path is not None:
        if explicit_path.is_file():
            return explicit_path
        return None

    for path in DEFAULT_CONFIG_PATHS:
        if path.is_file():
            return path

    return None


def load_config(path: Path) -> Config:
    """Load and validate config from a TOML file.

    Raises:
        FileNotFoundError: If the config file doesn't exist.
        ValueError: If the TOML is invalid or fails validation.
    """
    if not path.is_file():
        msg = f"Config file not found: {path}"
        raise FileNotFoundError(msg)

    text = path.read_text()

    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        msg = f"Invalid TOML in {path}: {e}"
        raise ValueError(msg) from e

    try:
        return Config.model_validate(raw)
    except ValidationError as e:
        msg = f"Config validation failed:\n{e}"
        raise ValueError(msg) from e


def load_config_or_exit(path: Path | None = None) -> Config:
    """Load config, printing errors and exiting on failure."""
    from rich.console import Console

    console = Console(stderr=True)

    resolved = find_config_path(path)
    if resolved is None:
        where = str(path) if path else ", ".join(str(p) for p in DEFAULT_CONFIG_PATHS)
        console.print(f"[red]Config file not found.[/red] Looked at: {where}")
        console.print("Run [bold]clawctl init[/bold] to create one.")
        sys.exit(1)

    try:
        return load_config(resolved)
    except ValueError as e:
        console.print(f"[red]Config error:[/red] {e}")
        sys.exit(1)
