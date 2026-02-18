"""Config loading and validation for clawctl."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

from pydantic import ValidationError

from clawctl.models.config import Config

# Config is searched relative to the current directory (project root).
DEFAULT_CONFIG_PATHS = [
    Path("clawctl.toml"),
]


def find_config_path(explicit_path: Path | None = None) -> Path | None:
    """Find the config file, checking explicit path, then defaults."""
    if explicit_path is not None:
        if explicit_path.is_file():
            return explicit_path.resolve()
        return None

    for path in DEFAULT_CONFIG_PATHS:
        if path.is_file():
            return path.resolve()

    return None


def load_config(path: Path) -> Config:
    """Load and validate config from a TOML file.

    The data_root is resolved relative to the config file's directory,
    so that ``data_root = "build"`` points to ``<project>/build/``.

    Raises:
        FileNotFoundError: If the config file doesn't exist.
        ValueError: If the TOML is invalid or fails validation.
    """
    if not path.is_file():
        msg = f"Config file not found: {path}"
        raise FileNotFoundError(msg)

    config_dir = path.resolve().parent
    text = path.read_text()

    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        msg = f"Invalid TOML in {path}: {e}"
        raise ValueError(msg) from e

    try:
        config = Config.model_validate(raw)
    except ValidationError as e:
        msg = f"Config validation failed:\n{e}"
        raise ValueError(msg) from e

    # Resolve data_root and build_root relative to the config file's directory
    for attr in ("data_root", "build_root"):
        value = getattr(config.clawctl, attr)
        if not value.is_absolute():
            setattr(config.clawctl, attr, (config_dir / value).resolve())
        else:
            setattr(config.clawctl, attr, value.expanduser().resolve())

    # Resolve workspace_template paths (global default and per-user)
    if config.clawctl.defaults.workspace_template is not None:
        wt = config.clawctl.defaults.workspace_template
        if not wt.is_absolute():
            config.clawctl.defaults.workspace_template = (config_dir / wt).resolve()
        else:
            config.clawctl.defaults.workspace_template = wt.expanduser().resolve()

    for user in config.users:
        if user.workspace_template is not None:
            wt = user.workspace_template
            if not wt.is_absolute():
                user.workspace_template = (config_dir / wt).resolve()
            else:
                user.workspace_template = wt.expanduser().resolve()

    return config


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
