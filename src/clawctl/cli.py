"""clawctl CLI — OpenClaw deployment manager."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer

from clawctl import __version__

app = typer.Typer(
    name="clawctl",
    help="OpenClaw deployment manager — provision and manage isolated OpenClaw instances for teams.",
    no_args_is_help=True,
)

# Sub-command groups
user_app = typer.Typer(help="Manage users", no_args_is_help=True)
backup_app = typer.Typer(help="Manage backups", no_args_is_help=True)
backup_schedule_app = typer.Typer(help="Manage backup scheduling", no_args_is_help=True)
config_app = typer.Typer(help="Configuration utilities", no_args_is_help=True)
gog_app = typer.Typer(help="Manage gog Google Workspace integration", no_args_is_help=True)

app.add_typer(user_app, name="user")
app.add_typer(backup_app, name="backup")
backup_app.add_typer(backup_schedule_app, name="schedule")
app.add_typer(config_app, name="config")
app.add_typer(gog_app, name="gog")

# Global option for config file path
ConfigOption = Annotated[
    Optional[Path],
    typer.Option("--config", "-c", help="Path to clawctl.toml config file"),
]


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"clawctl {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", "-v", callback=version_callback, is_eager=True),
    ] = False,
) -> None:
    """OpenClaw deployment manager."""


# Import and register commands
from clawctl.commands.init import init  # noqa: E402
from clawctl.commands.user import user_add, user_list, user_remove  # noqa: E402
from clawctl.commands.lifecycle import start, stop, restart, start_all, stop_all  # noqa: E402
from clawctl.commands.status import status  # noqa: E402
from clawctl.commands.logs import logs  # noqa: E402
from clawctl.commands.backup import backup_run, schedule_start, schedule_stop, schedule_status  # noqa: E402
from clawctl.commands.config_cmd import validate  # noqa: E402
from clawctl.commands.update import update  # noqa: E402
from clawctl.commands.clean import clean  # noqa: E402
from clawctl.commands.gog import gog_setup, gog_test  # noqa: E402

# Register top-level commands
app.command()(init)
app.command()(start)
app.command()(stop)
app.command()(restart)
app.command(name="start-all")(start_all)
app.command(name="stop-all")(stop_all)
app.command()(status)
app.command()(logs)
app.command()(update)
app.command()(clean)

# Register sub-commands
user_app.command(name="add")(user_add)
user_app.command(name="remove")(user_remove)
user_app.command(name="list")(user_list)

backup_app.command(name="run")(backup_run)
backup_schedule_app.command(name="start")(schedule_start)
backup_schedule_app.command(name="stop")(schedule_stop)
backup_schedule_app.command(name="status")(schedule_status)

config_app.command(name="validate")(validate)

gog_app.command(name="setup")(gog_setup)
gog_app.command(name="test")(gog_test)
