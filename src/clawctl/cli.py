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
maintenance_app = typer.Typer(help="Manage nightly maintenance (backup + restart)", no_args_is_help=True)
maintenance_schedule_app = typer.Typer(help="Manage maintenance scheduling", no_args_is_help=True)
shared_collections_app = typer.Typer(help="Manage shared document collections", no_args_is_help=True)
shared_collections_schedule_app = typer.Typer(help="Manage shared collections sync scheduling", no_args_is_help=True)
config_app = typer.Typer(help="Configuration utilities", no_args_is_help=True)
gog_app = typer.Typer(help="Manage gog Google Workspace integration", no_args_is_help=True)
web_app = typer.Typer(help="Web management interface", no_args_is_help=True)

app.add_typer(user_app, name="user")
app.add_typer(backup_app, name="backup")
backup_app.add_typer(backup_schedule_app, name="schedule")
app.add_typer(maintenance_app, name="maintenance")
maintenance_app.add_typer(maintenance_schedule_app, name="schedule")
app.add_typer(shared_collections_app, name="shared-collections")
shared_collections_app.add_typer(shared_collections_schedule_app, name="schedule")
app.add_typer(config_app, name="config")
app.add_typer(gog_app, name="gog")
app.add_typer(web_app, name="web")

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
from clawctl.commands.user import user_add, user_list, user_remove, user_set_slack, user_set_discord  # noqa: E402
from clawctl.commands.lifecycle import start, stop, restart, start_all, stop_all  # noqa: E402
from clawctl.commands.status import status  # noqa: E402
from clawctl.commands.logs import logs  # noqa: E402
from clawctl.commands.backup import backup_run, schedule_start, schedule_stop, schedule_status  # noqa: E402
from clawctl.commands.shared_collections import (  # noqa: E402
    list_collections,
    schedule_start as sc_schedule_start,
    schedule_status as sc_schedule_status,
    schedule_stop as sc_schedule_stop,
    sync,
)
from clawctl.commands.maintenance import maintenance_run, schedule_start as maintenance_schedule_start, schedule_stop as maintenance_schedule_stop, schedule_status as maintenance_schedule_status  # noqa: E402
from clawctl.commands.config_cmd import validate, regenerate  # noqa: E402
from clawctl.commands.update import update  # noqa: E402
from clawctl.commands.clean import clean  # noqa: E402
from clawctl.commands.gog import gog_setup, gog_test  # noqa: E402
from clawctl.commands.web import web_start, web_set_password  # noqa: E402

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

# Web commands
web_app.command(name="start")(web_start)
web_app.command(name="set-password")(web_set_password)

# Register sub-commands
user_app.command(name="add")(user_add)
user_app.command(name="remove")(user_remove)
user_app.command(name="list")(user_list)
user_app.command(name="set-slack")(user_set_slack)
user_app.command(name="set-discord")(user_set_discord)

backup_app.command(name="run")(backup_run)
backup_schedule_app.command(name="start")(schedule_start)
backup_schedule_app.command(name="stop")(schedule_stop)
backup_schedule_app.command(name="status")(schedule_status)

maintenance_app.command(name="run")(maintenance_run)
maintenance_schedule_app.command(name="start")(maintenance_schedule_start)
maintenance_schedule_app.command(name="stop")(maintenance_schedule_stop)
maintenance_schedule_app.command(name="status")(maintenance_schedule_status)

shared_collections_app.command(name="sync")(sync)
shared_collections_app.command(name="list")(list_collections)
shared_collections_schedule_app.command(name="start")(sc_schedule_start)
shared_collections_schedule_app.command(name="stop")(sc_schedule_stop)
shared_collections_schedule_app.command(name="status")(sc_schedule_status)

config_app.command(name="validate")(validate)
config_app.command(name="regenerate")(regenerate)

gog_app.command(name="setup")(gog_setup)
gog_app.command(name="test")(gog_test)
