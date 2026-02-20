"""clawctl user — manage users."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from clawlib.core.config import load_config_or_exit
from clawlib.core.docker_manager import DockerManager
from clawlib.core.secrets import SecretsManager
from clawlib.core.paths import Paths
from clawlib.core.user_manager import GATEWAY_TOKEN_SECRET_NAME, UserManager
from clawctl.commands.gog import _get_docker_client, run_gog_auth

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
    secrets_mgr = SecretsManager(Paths(cfg.clawctl.data_root, cfg.clawctl.build_root))

    # Collect required secrets interactively
    required = secrets_mgr.get_required_secrets(user, cfg.clawctl.defaults)
    secret_values: dict[str, str] = {}

    console.print(f"Provisioning user [bold]{name}[/bold]...")
    console.print()

    for secret_name, description in required:
        # Check if secret already exists
        if secrets_mgr.secret_exists(name, secret_name):
            console.print(
                f"  [yellow]Secret '{secret_name}' ({description}) already exists.[/yellow]"
            )
            try:
                overwrite = typer.confirm(
                    "  Do you want to overwrite it?",
                    default=False,
                )
            except (KeyboardInterrupt, EOFError):
                console.print("\n[yellow]Aborted by user[/yellow]")
                raise typer.Abort()
            except Exception as e:
                # Handle any unexpected input errors
                console.print(f"  [red]Error reading input: {e}[/red]")
                console.print("  [dim]Skipping this secret. Run the command again to retry.[/dim]")
                continue
            
            if not overwrite:
                console.print(f"  [dim]Skipping '{secret_name}'[/dim]")
                continue

        try:
            value = typer.prompt(
                f"  Enter {description} ({secret_name})",
                hide_input=True,
            )
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Aborted by user[/yellow]")
            raise typer.Abort()
        except Exception as e:
            console.print(f"  [red]Error reading input: {e}[/red]")
            console.print(f"  [dim]Skipping '{secret_name}'[/dim]")
            continue
            
        if not value or not value.strip():
            console.print(f"  [yellow]Empty value provided, skipping '{secret_name}'[/yellow]")
            continue
        secret_values[secret_name] = value.strip()

    console.print()

    with console.status("Building image and starting container..."):
        manager.provision_user(user, secret_values)

    docker = DockerManager(cfg)
    port = docker.get_container_port(name)
    token = secrets_mgr.read_secret(name, GATEWAY_TOKEN_SECRET_NAME)
    console.print(f"[green]User '{name}' provisioned successfully.[/green]")
    if port:
        url = f"http://localhost:{port}"
        if token:
            url += f"?token={token}"
        console.print(f"  Dashboard: [link={url}]{url}[/link]")

    # Offer inline gog OAuth flow if gog is enabled and email is configured
    if user.skills.gog.enabled and user.skills.gog.email:
        console.print()
        
        # Check container status before attempting gog auth
        docker_mgr = DockerManager(cfg)
        container_status = docker_mgr.get_container_status(name)
        
        if container_status != "running":
            console.print(
                f"  [yellow]Container is not running (status: {container_status}).[/yellow]"
            )
            console.print(
                f"  [dim]Start the container first, then run [bold]clawctl gog setup {name}[/bold] to authorize gog.[/dim]"
            )
        elif typer.confirm(
            f"  Run gog Gmail authorization for {user.skills.gog.email} now?",
            default=True,
        ):
            gog_client = _get_docker_client(cfg)
            try:
                run_gog_auth(name, user.skills.gog.email, gog_client, secrets_mgr=secrets_mgr)
            except Exception as e:
                console.print(f"  [red]Failed to run gog authorization: {e}[/red]")
                console.print(
                    f"  [dim]You can run [bold]clawctl gog setup {name}[/bold] later to authorize gog.[/dim]"
                )
        else:
            console.print(
                f"  [dim]Run [bold]clawctl gog setup {name}[/bold] later to authorize gog.[/dim]"
            )


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
    secrets_mgr = SecretsManager(Paths(cfg.clawctl.data_root, cfg.clawctl.build_root))
    statuses = docker.get_all_statuses()

    table = Table(title="Users")
    table.add_column("Name", style="bold")
    table.add_column("Status")
    table.add_column("Channels")
    table.add_column("URL")

    for user in cfg.users:
        info = statuses.get(user.name, {"status": "unknown", "port": "-"})
        st = info["status"]
        style = "green" if st == "running" else "red" if st == "exited" else "dim"

        channels = []
        if user.channels.slack.enabled:
            channels.append("slack")
        if user.channels.discord.enabled:
            channels.append("discord")

        url = "-"
        if st == "running" and info["port"] != "-":
            token = secrets_mgr.read_secret(user.name, GATEWAY_TOKEN_SECRET_NAME)
            url = f"http://localhost:{info['port']}"
            if token:
                url += f"?token={token}"

        table.add_row(
            user.name,
            f"[{style}]{st}[/{style}]",
            ", ".join(channels) or "-",
            url,
        )

    console.print(table)


def user_set_slack(
    name: Annotated[str, typer.Argument(help="Username")],
    bot_token: Annotated[
        Optional[str],
        typer.Option("--bot-token", help="Slack Bot User OAuth Token (xoxb-...)"),
    ] = None,
    app_token: Annotated[
        Optional[str],
        typer.Option("--app-token", help="Slack App-Level Token (xapp-...)"),
    ] = None,
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Set Slack tokens for a user.
    
    Prompts for tokens interactively if not provided via options.
    After setting tokens, regenerates openclaw.json and restarts the container.
    """
    cfg = load_config_or_exit(config)
    user = cfg.get_user(name)
    
    if user is None:
        console.print(
            f"[red]User '{name}' not found in config.[/red] "
            f"Add a [[users]] block with name = \"{name}\" to clawctl.toml first."
        )
        raise typer.Exit(1)
    
    if not user.channels.slack.enabled:
        console.print(
            f"[yellow]Slack is not enabled for '{name}'.[/yellow] "
            "Set [users.channels.slack] enabled = true in clawctl.toml first."
        )
        raise typer.Exit(1)
    
    # Get token values
    if not bot_token:
        bot_token = typer.prompt(
            "Enter Slack Bot User OAuth Token (xoxb-...)",
            hide_input=True,
        )
    
    if not app_token:
        app_token = typer.prompt(
            "Enter Slack App-Level Token (xapp-...)",
            hide_input=True,
        )
    
    if not bot_token.strip() or not app_token.strip():
        console.print("[red]Both tokens are required.[/red]")
        raise typer.Exit(1)
    
    # Write secrets
    paths = Paths(cfg.clawctl.data_root, cfg.clawctl.build_root)
    secrets_mgr = SecretsManager(paths)
    
    bot_token_secret_name = user.channels.slack.bot_token_secret or "slack_bot_token"
    app_token_secret_name = user.channels.slack.app_token_secret or "slack_app_token"
    
    secrets_mgr.write_secret(name, bot_token_secret_name, bot_token.strip())
    secrets_mgr.write_secret(name, app_token_secret_name, app_token.strip())
    
    console.print(f"[green]✓[/green] Slack tokens saved for '{name}'")
    
    # Regenerate config
    from clawlib.core.openclaw_config import write_openclaw_config
    from clawlib.core.user_manager import GATEWAY_TOKEN_SECRET_NAME
    
    gateway_token = secrets_mgr.read_secret(name, GATEWAY_TOKEN_SECRET_NAME)
    if not gateway_token:
        import secrets as secrets_module
        gateway_token = secrets_module.token_urlsafe(32)
        secrets_mgr.write_secret(name, GATEWAY_TOKEN_SECRET_NAME, gateway_token)
    
    write_openclaw_config(
        user,
        cfg.clawctl.defaults,
        paths.user_openclaw_config(name),
        gateway_token=gateway_token,
    )
    
    console.print(f"[green]✓[/green] Regenerated openclaw.json")
    
    # Restart container
    docker_mgr = DockerManager(cfg)
    if docker_mgr.container_exists(name):
        console.print("Restarting container...")
        docker_mgr.restart_container(name)
        console.print(f"[green]✓[/green] Container restarted")
    else:
        console.print(f"[yellow]Container not found. Run 'clawctl user add {name}' first.[/yellow]")
