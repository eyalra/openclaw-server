"""clawctl user — manage users."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from clawctl.core.config import load_config_or_exit
from clawctl.core.docker_manager import DockerManager
from clawctl.core.secrets import SecretsManager
from clawctl.core.paths import Paths
from clawctl.core.user_manager import UserManager

console = Console()


def user_add(
    name: Annotated[str, typer.Argument(help="Username to provision")],
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Provision a new user: create directories, write secrets, start container."""
    cfg = load_config_or_exit(config)
    user = cfg.get_user(name)

    if user is None:
        console.print(
            f"[red]User '{name}' not found in config.[/red] "
            f"Add a [[users]] block with name = \"{name}\" to clawctl.toml first."
        )
        raise typer.Exit(1)

    manager = UserManager(cfg)
    secrets_mgr = SecretsManager(Paths(cfg.clawctl.data_root))

    # Collect required secrets interactively
    required = secrets_mgr.get_required_secrets(user)
    secret_values: dict[str, str] = {}

    console.print(f"Provisioning user [bold]{name}[/bold]...")
    console.print()

    for secret_name, description in required:
        # Check if secret already exists
        if secrets_mgr.secret_exists(name, secret_name):
            if not typer.confirm(
                f"  Secret '{secret_name}' ({description}) already exists. Overwrite?",
                default=False,
            ):
                continue

        value = typer.prompt(
            f"  Enter {description} ({secret_name})",
            hide_input=True,
        )
        secret_values[secret_name] = value

    console.print()

    with console.status("Building image and starting container..."):
        manager.provision_user(user, secret_values)

    docker = DockerManager(cfg)
    port = docker.get_container_port(name)
    console.print(f"[green]User '{name}' provisioned successfully.[/green]")
    if port:
        console.print(f"  Gateway available at http://localhost:{port}")


def user_remove(
    name: Annotated[str, typer.Argument(help="Username to remove")],
    keep_data: Annotated[
        bool, typer.Option("--keep-data/--delete-data", help="Keep user data on disk")
    ] = True,
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Remove a user's container and network."""
    cfg = load_config_or_exit(config)
    manager = UserManager(cfg)

    if not keep_data:
        if not typer.confirm(
            f"This will permanently delete all data for '{name}'. Continue?",
            default=False,
        ):
            raise typer.Abort()

    with console.status(f"Removing user '{name}'..."):
        manager.remove_user(name, keep_data=keep_data)

    action = "removed (data kept)" if keep_data else "removed with all data"
    console.print(f"[green]User '{name}' {action}.[/green]")


def user_list(
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """List all configured users and their container status."""
    cfg = load_config_or_exit(config)
    docker = DockerManager(cfg)
    statuses = docker.get_all_statuses()

    table = Table(title="Users")
    table.add_column("Name", style="bold")
    table.add_column("Status")
    table.add_column("Port")
    table.add_column("Channels")

    for user in cfg.users:
        info = statuses.get(user.name, {"status": "unknown", "port": "-"})
        status = info["status"]
        style = "green" if status == "running" else "red" if status == "exited" else "dim"

        channels = []
        if user.channels.slack.enabled:
            channels.append("slack")
        if user.channels.discord.enabled:
            channels.append("discord")

        table.add_row(
            user.name,
            f"[{style}]{status}[/{style}]",
            info["port"],
            ", ".join(channels) or "-",
        )

    console.print(table)
