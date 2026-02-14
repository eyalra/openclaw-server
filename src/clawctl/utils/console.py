"""Shared Rich console for consistent output."""

from rich.console import Console

console = Console()
err_console = Console(stderr=True)
