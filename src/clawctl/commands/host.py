"""clawctl server — manage the remote deployment server."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from clawlib.core.config import find_config_path, load_config_or_exit
from clawlib.models.config import HostConfig

console = Console()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_host(config_path: Path | None) -> tuple:
    """Load config and return (Config, HostConfig, resolved_config_path).

    Exits if [host] is missing or the config file cannot be found.
    """
    cfg = load_config_or_exit(config_path)
    resolved = find_config_path(config_path)
    config_name = resolved.name if resolved else "clawctl.toml"
    if cfg.host is None:
        console.print(f"[red]No [host] section in {config_name}.[/red]")
        console.print("Add a [host] section with ip, ssh_key, etc.")
        raise typer.Exit(1)
    return cfg, cfg.host, resolved


def _ssh_cmd(host: HostConfig, *, initial: bool = False) -> list[str]:
    """Build the base ssh command list."""
    user = host.initial_ssh_user if initial else host.ssh_user
    port = host.initial_ssh_port if initial else host.ssh_port
    return [
        "ssh",
        "-p", str(port),
        "-i", str(host.ssh_key),
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        f"{user}@{host.ip}",
    ]


def _run_ssh(host: HostConfig, remote_cmd: str, *, initial: bool = False, check: bool = True) -> subprocess.CompletedProcess:
    """Run a command on the remote host via SSH."""
    cmd = _ssh_cmd(host, initial=initial) + [remote_cmd]
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def _run_local(cmd: list[str] | str, *, check: bool = True, **kwargs) -> subprocess.CompletedProcess:
    """Run a local command."""
    if isinstance(cmd, str):
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, check=check, **kwargs)
    return subprocess.run(cmd, capture_output=True, text=True, check=check, **kwargs)


def _repo_root() -> Path:
    """Find the repository root (parent of src/)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return Path.cwd()


def _secrets_dir(host: HostConfig) -> Path:
    """Resolve the secrets directory: expand ~, then absolutify relative paths against repo root."""
    sd = host.secrets_dir.expanduser()
    if sd.is_absolute():
        return sd
    return _repo_root() / sd


def _aws_credentials(host: HostConfig) -> dict[str, str]:
    """Load AWS credentials from secrets files, falling back to environment variables."""
    secrets = _secrets_dir(host)
    key_id_file = secrets / "aws_access_key_id"
    secret_file = secrets / "aws_secret_access_key"

    key_id = None
    secret_key = None

    if key_id_file.exists():
        key_id = key_id_file.read_text().strip()
    if secret_file.exists():
        secret_key = secret_file.read_text().strip()

    key_id = key_id or os.environ.get("AWS_ACCESS_KEY_ID", "")
    secret_key = secret_key or os.environ.get("AWS_SECRET_ACCESS_KEY", "")

    if not key_id or not secret_key:
        console.print("[red]AWS credentials not found.[/red]")
        console.print("Provide them as either:")
        console.print(f"  1. Files: {key_id_file} and {secret_file}")
        console.print("  2. Env vars: AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY")
        raise typer.Exit(1)

    return {
        "aws_access_key_id": key_id,
        "aws_secret_access_key": secret_key,
    }


def _get_boto3_client(host: HostConfig, service: str):
    """Create a boto3 client. Prefers project secrets, then env vars, then ~/.aws."""
    import boto3

    secrets = _secrets_dir(host)
    key_id_file = secrets / "aws_access_key_id"
    secret_file = secrets / "aws_secret_access_key"

    key_id = key_id_file.read_text().strip() if key_id_file.exists() else None
    secret_key = secret_file.read_text().strip() if secret_file.exists() else None

    if key_id and secret_key:
        return boto3.client(
            service,
            region_name=host.aws_region,
            aws_access_key_id=key_id,
            aws_secret_access_key=secret_key,
        )

    # Fall back to boto3 standard chain (env vars, ~/.aws/credentials, IAM role, etc.)
    return boto3.client(service, region_name=host.aws_region)


def _update_toml_field(toml_path: Path, field: str, value: str, *, section: str = "host") -> bool:
    """Update a field in the config file, inserting it under [section] if missing.

    Returns True if the file was written successfully.
    """
    import re
    text = toml_path.read_text()
    pattern = rf'^({re.escape(field)}\s*=\s*).*$'
    new_text, n = re.subn(pattern, rf'\g<1>"{value}"', text, flags=re.MULTILINE)
    if n == 0:
        # Field doesn't exist yet — insert after the [section] header
        section_pattern = rf'^(\[{re.escape(section)}\]\s*\n)'
        new_text, n = re.subn(
            section_pattern,
            rf'\g<1>{field} = "{value}"\n',
            text,
            count=1,
            flags=re.MULTILINE,
        )
        if n == 0:
            console.print(f"[yellow]Could not update {field} in {toml_path.name} "
                          f"(neither field nor [{section}] section found)[/yellow]")
            return False
    toml_path.write_text(new_text)
    return True


# ---------------------------------------------------------------------------
# clawctl server requirements
# ---------------------------------------------------------------------------

def host_requirements(
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Verify all secrets and config needed for deployment exist locally."""
    cfg, host, _resolved = _get_host(config)

    table = Table(title="Deployment Requirements")
    table.add_column("Check", style="bold")
    table.add_column("Status")
    table.add_column("Detail")

    ok_count = 0
    fail_count = 0

    def check(name: str, passed: bool, detail: str = "") -> None:
        nonlocal ok_count, fail_count
        if passed:
            ok_count += 1
            table.add_row(name, "[green]OK[/green]", detail)
        else:
            fail_count += 1
            table.add_row(name, "[red]MISSING[/red]", detail)

    # Host config
    check("host.ip", bool(host.ip), host.ip or "not set (run: clawctl server provision)")
    check("host.ssh_key", host.ssh_key.expanduser().exists(), str(host.ssh_key))

    # AWS credentials (secrets files, env vars, or ~/.aws/credentials)
    secrets = _secrets_dir(host)
    has_key_id = (secrets / "aws_access_key_id").exists() or bool(os.environ.get("AWS_ACCESS_KEY_ID"))
    has_secret = (secrets / "aws_secret_access_key").exists() or bool(os.environ.get("AWS_SECRET_ACCESS_KEY"))
    has_aws_file = Path("~/.aws/credentials").expanduser().exists()
    check("aws_credentials", has_key_id and has_secret or has_aws_file,
          "secrets dir, env vars, or ~/.aws/credentials")

    # AWS config
    check("host.instance_name", bool(host.instance_name), host.instance_name or "not set")
    check("host.key_pair_name", bool(host.key_pair_name), host.key_pair_name or "not set")
    check("host.static_ip_name", bool(host.static_ip_name), host.static_ip_name or "not set")

    # Tailscale auth key
    ts_key = secrets / "tailscale_auth_key"
    check("tailscale_auth_key", ts_key.exists(), str(ts_key))

    # Web admin password
    web_pw = secrets / "web_admin_password"
    check("web_admin_password", web_pw.exists(), str(web_pw))

    # Per-user secrets
    for user in cfg.users:
        user_secrets = secrets / user.name
        # Check secret files referenced in user.secrets
        for field_name in user.secrets.model_extra:
            secret_file = user_secrets / field_name
            check(f"{user.name}/{field_name}", secret_file.exists(), str(secret_file))

        # Discord token
        if user.channels.discord.enabled:
            dt = user_secrets / "discord_token"
            check(f"{user.name}/discord_token", dt.exists(), str(dt))

    # File permission checks — secrets should not be world-readable
    import stat
    warn_count = 0
    if secrets.exists():
        for sf in secrets.rglob("*"):
            if sf.is_file():
                mode = sf.stat().st_mode
                if mode & stat.S_IROTH:
                    table.add_row(
                        f"perms:{sf.relative_to(secrets)}",
                        "[yellow]WARN[/yellow]",
                        f"world-readable ({oct(mode & 0o777)}), should be 600",
                    )
                    warn_count += 1

    console.print(table)
    if warn_count:
        console.print(
            f"\n[yellow]{warn_count} file(s) have loose permissions.[/yellow] "
            f"Fix with: chmod -R go-rwx {secrets}"
        )
    if fail_count:
        console.print(f"\n[red]{fail_count} missing requirement(s).[/red] Fix them before deploying.")
        raise typer.Exit(1)
    else:
        console.print(f"\n[green]All {ok_count} requirements met.[/green]")


# ---------------------------------------------------------------------------
# clawctl server url
# ---------------------------------------------------------------------------

def host_url(
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Print the web management interface URL and credentials."""
    cfg, host, _resolved = _get_host(config)

    result = _run_ssh(host, "tailscale ip -4 2>/dev/null", check=False)
    ts_ip = result.stdout.strip()
    if result.returncode != 0 or not ts_ip:
        console.print("[red]Could not get Tailscale IP from server.[/red]")
        raise typer.Exit(1)

    url = f"https://{ts_ip}"
    console.print(f"URL:      {url}")

    admin_user = cfg.web.admin_username if cfg.web else "admin"
    console.print(f"Username: {admin_user}")

    pw_file = _secrets_dir(host) / "web_admin_password"
    if pw_file.exists():
        console.print(f"Password: {pw_file.read_text().strip()}")
    else:
        console.print(f"Password: [yellow]not found at {pw_file}[/yellow]")


# ---------------------------------------------------------------------------
# clawctl server status / clawctl status
# ---------------------------------------------------------------------------

def host_status(
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Show the current state of the remote host."""
    cfg, host, _resolved = _get_host(config)

    console.print(f"Host: [bold]{host.ssh_user}@{host.ip}:{host.ssh_port}[/bold]\n")

    # SSH check
    result = _run_ssh(host, "echo ok", check=False)
    if result.returncode != 0:
        console.print("[red]SSH: unreachable[/red]")
        console.print(f"  {result.stderr.strip()}")
        raise typer.Exit(1)
    console.print("[green]SSH: connected[/green]")

    # Gather all status info in one SSH call
    status_script = r"""
echo "::DOCKER::"
docker --version 2>&1 || echo "NOT INSTALLED"
echo "::TAILSCALE::"
sudo tailscale status 2>&1 | head -3 || echo "NOT INSTALLED"
echo "::TAILSCALE_IP::"
tailscale ip -4 2>/dev/null || echo "none"
echo "::CONTAINERS::"
docker ps -a --format '{{.Names}}\t{{.Status}}' 2>/dev/null | grep openclaw || echo "none"
echo "::WEB::"
sudo systemctl is-active clawctl-web 2>/dev/null || echo "inactive"
"""
    result = _run_ssh(host, status_script, check=False)
    output = result.stdout

    def _section(name: str) -> str:
        marker = f"::{name}::"
        if marker not in output:
            return ""
        text = output.split(marker)[1]
        next_marker = text.find("::")
        if next_marker != -1:
            text = text[:next_marker]
        return text.strip()

    # Docker
    docker_out = _section("DOCKER")
    if "NOT INSTALLED" in docker_out:
        console.print("[red]Docker: not installed[/red]")
    else:
        console.print(f"[green]Docker: {docker_out}[/green]")

    # Tailscale
    ts_out = _section("TAILSCALE")
    ts_ip = _section("TAILSCALE_IP")
    if "NOT INSTALLED" in ts_out:
        console.print("[red]Tailscale: not installed[/red]")
    elif "Logged out" in ts_out or "NeedsLogin" in ts_out:
        console.print("[yellow]Tailscale: not connected[/yellow]")
    else:
        console.print(f"[green]Tailscale: connected ({ts_ip})[/green]")

    # Containers
    containers_out = _section("CONTAINERS")
    if containers_out == "none":
        console.print("[yellow]Containers: none running[/yellow]")
    else:
        console.print("Containers:")
        for line in containers_out.splitlines():
            parts = line.split("\t", 1)
            name = parts[0]
            status_text = parts[1] if len(parts) > 1 else ""
            color = "green" if "Up" in status_text else "red"
            console.print(f"  [{color}]{name}: {status_text}[/{color}]")

    # Web service
    web_out = _section("WEB")
    if web_out == "active":
        console.print("[green]Web: running[/green]")
    else:
        console.print(f"[yellow]Web: {web_out}[/yellow]")


# ---------------------------------------------------------------------------
# clawctl server deploy
# ---------------------------------------------------------------------------

def host_deploy(
    initial: Annotated[
        bool,
        typer.Option("--initial", help="Use initial SSH user/port (for fresh instances)"),
    ] = False,
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Rsync code and secrets to the remote host, then reinstall clawctl."""
    cfg, host, resolved_config = _get_host(config)
    repo = _repo_root()

    user = host.initial_ssh_user if initial else host.ssh_user
    port = host.initial_ssh_port if initial else host.ssh_port
    remote_repo = f"/home/{user}/openclaw" if initial else host.remote_repo_path
    remote_home = f"/home/{user}" if initial else host.remote_home

    console.print(f"Deploying to [bold]{user}@{host.ip}:{port}[/bold]...\n")

    # 1. Rsync repo
    console.print("Syncing repo...")
    ssh_flag = f"ssh -p {port} -i {host.ssh_key} -o StrictHostKeyChecking=no"
    rsync_cmd = [
        "rsync", "-az", "--delete",
        "--exclude=.venv", "--exclude=__pycache__", "--exclude=*.pyc",
        "--exclude=data/", "--exclude=build/", "--exclude=.git",
        "--exclude=node_modules",
        "-e", ssh_flag,
        f"{repo}/",
        f"{user}@{host.ip}:{remote_repo}/",
    ]
    result = _run_local(rsync_cmd, check=False)
    if result.returncode != 0:
        console.print(f"[red]rsync failed:[/red] {result.stderr.strip()}")
        raise typer.Exit(1)
    console.print("  [green]Repo synced[/green]")

    # 2. Install the specified config as clawctl.toml on the remote
    if resolved_config and resolved_config.name != "clawctl.toml":
        scp_config = [
            "scp", "-P", str(port), "-i", str(host.ssh_key),
            "-o", "StrictHostKeyChecking=no",
            str(resolved_config),
            f"{user}@{host.ip}:{remote_repo}/clawctl.toml",
        ]
        result_cfg = _run_local(scp_config, check=False)
        if result_cfg.returncode != 0:
            console.print(f"[yellow]Config install warning:[/yellow] {result_cfg.stderr.strip()}")
        else:
            console.print(f"  [green]Installed {resolved_config.name} as clawctl.toml on remote[/green]")

    # 3. Push secrets
    secrets = _secrets_dir(host)
    if secrets.is_dir():
        console.print("Syncing secrets...")
        scp_base = ["scp", "-P", str(port), "-i", str(host.ssh_key),
                     "-o", "StrictHostKeyChecking=no"]
        target = f"{user}@{host.ip}"

        for item in sorted(secrets.iterdir()):
            if item.is_dir():
                username = item.name
                # Secrets go under <repo>/data/secrets/<user>/ (matches clawctl data_root)
                remote_dir = f"{remote_repo}/data/secrets/{username}"
                _run_ssh(host, f"mkdir -p '{remote_dir}'", initial=initial, check=False)
                for secret_file in sorted(item.iterdir()):
                    if secret_file.is_file():
                        _run_local(scp_base + [str(secret_file), f"{target}:{remote_dir}/"], check=False)
                        console.print(f"  [green]{username}/{secret_file.name}[/green]")
            elif item.is_file() and item.name == "tailscale_auth_key":
                remote_dir = f"{remote_repo}/deploy/lightsail/secrets"
                _run_ssh(host, f"mkdir -p '{remote_dir}'", initial=initial, check=False)
                _run_local(scp_base + [str(item), f"{target}:{remote_dir}/"], check=False)
                console.print(f"  [green]tailscale_auth_key[/green]")
            elif item.is_file() and item.name == "web_admin_password":
                remote_dir = f"{remote_repo}/data/secrets/web_admin"
                _run_ssh(host, f"mkdir -p '{remote_dir}'", initial=initial, check=False)
                _run_local(scp_base + [str(item), f"{target}:{remote_dir}/password_plaintext"], check=False)
                console.print(f"  [green]web_admin_password[/green]")

    # 4. Push shared collections if they exist locally
    local_shared = repo / "data" / "shared"
    if local_shared.is_dir() and any(local_shared.iterdir()):
        console.print("Syncing shared collections...")
        remote_shared = f"{remote_repo}/data/shared"
        _run_ssh(host, f"mkdir -p '{remote_shared}'", initial=initial, check=False)
        rsync_shared = [
            "rsync", "-az", "--delete",
            "-e", ssh_flag,
            f"{local_shared}/",
            f"{user}@{host.ip}:{remote_shared}/",
        ]
        result_shared = _run_local(rsync_shared, check=False)
        if result_shared.returncode != 0:
            console.print(f"[yellow]Shared collections rsync warning:[/yellow] {result_shared.stderr.strip()}")
        else:
            count = sum(1 for _ in local_shared.rglob("*") if _.is_file())
            console.print(f"  [green]Shared collections synced ({count} files)[/green]")

    if initial:
        console.print("\n[green]Initial deploy complete.[/green]")
        console.print(f"Code deployed to {remote_repo}")
    else:
        # 5. Reinstall clawctl on server (only when deploying to the final user)
        console.print("Reinstalling clawctl on server...")
        install_cmd = (
            "export PATH=$HOME/.local/bin:$HOME/.local/venv/clawctl/bin:$PATH && "
            f"cd {host.remote_repo_path} && "
            "$HOME/.local/venv/clawctl/bin/pip install -e . -q"
        )
        result = _run_ssh(host, install_cmd, check=False)
        if result.returncode != 0:
            console.print(f"[yellow]clawctl reinstall warning:[/yellow] {result.stderr.strip()}")
        else:
            console.print("  [green]clawctl reinstalled[/green]")

        console.print("\n[green]Deploy complete.[/green]")


# ---------------------------------------------------------------------------
# clawctl server setup
# ---------------------------------------------------------------------------

def host_setup(
    step: Annotated[
        Optional[str],
        typer.Option("--step", "-s", help="Run a single step: harden, deps, docker, users, web"),
    ] = None,
    initial: Annotated[
        bool,
        typer.Option("--initial", help="Use initial SSH user/port (for fresh instances)"),
    ] = False,
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Run setup on the remote host (idempotent). Installs deps, builds Docker, provisions users, starts web."""
    cfg, host, _resolved = _get_host(config)

    remote_step = step or "all"
    user = host.initial_ssh_user if initial else host.ssh_user
    remote_repo = f"/home/{user}/openclaw" if initial else host.remote_repo_path
    setup_script = f"{remote_repo}/deploy/lightsail/remote/setup.sh"

    console.print(f"Running setup on [bold]{user}@{host.ip}[/bold] (step: {remote_step})...\n")

    cmd = _ssh_cmd(host, initial=initial) + [f"chmod +x {setup_script} && sudo {setup_script} {remote_step}"]
    proc = subprocess.run(cmd, text=True)

    if proc.returncode != 0:
        console.print(f"\n[red]Setup failed (exit {proc.returncode}).[/red]")
        raise typer.Exit(proc.returncode)

    # After initial setup, reboot so SSH comes up on 2222
    # (repo move is handled by setup.sh's step_finalize before the web step)
    if initial and remote_step in ("harden", "all"):
        console.print("Rebooting instance for SSH changes to take effect...")
        reboot_cmd = _ssh_cmd(host, initial=True) + ["sudo reboot"]
        subprocess.run(reboot_cmd, text=True, capture_output=True, check=False)

        console.print("Waiting for SSH on port 2222...")
        import time as _time
        for attempt in range(20):
            _time.sleep(5)
            result = _run_ssh(host, "echo ok", initial=False, check=False)
            if result.returncode == 0:
                console.print(f"  [green]SSH on 2222 is up (attempt {attempt + 1})[/green]")
                break
        else:
            console.print("[red]SSH on 2222 did not come up after reboot.[/red]")
            raise typer.Exit(1)

        # Clean up UFW port 22 on the server (left open for the reboot command)
        _run_ssh(host, "sudo ufw delete allow 22/tcp 2>/dev/null || true", initial=False, check=False)
        console.print("  [green]UFW port 22 rule removed[/green]")

        # Close port 22 in Lightsail firewall — no longer needed after hardening
        try:
            ls = _get_boto3_client(host, "lightsail")
            ls.close_instance_public_ports(
                instanceName=host.instance_name,
                portInfo={"fromPort": 22, "toPort": 22, "protocol": "tcp"},
            )
            console.print("  [green]Port 22 closed in Lightsail firewall[/green]")
        except Exception as e:
            console.print(f"  [yellow]Could not close port 22 in Lightsail: {e}[/yellow]")

    console.print("\n[green]Setup complete.[/green]")


# ---------------------------------------------------------------------------
# clawctl server provision
# ---------------------------------------------------------------------------

def host_provision(
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Provision a Lightsail instance (idempotent). Creates instance, static IP, firewall rules."""
    cfg, host, resolved_config = _get_host(config)

    for field in ("instance_name", "key_pair_name", "static_ip_name"):
        if not getattr(host, field):
            console.print(f"[red]host.{field} is not set in {resolved_config.name}[/red]")
            raise typer.Exit(1)

    ls = _get_boto3_client(host, "lightsail")
    sts = _get_boto3_client(host, "sts")

    # Validate credentials
    console.print("Validating AWS credentials...")
    try:
        identity = sts.get_caller_identity()
        console.print(f"  Account: {identity['Account']}")
        console.print(f"  Identity: {identity['Arn']}")
        console.print(f"  Region: {host.aws_region}")
    except Exception as e:
        console.print(f"[red]AWS credentials invalid:[/red] {e}")
        raise typer.Exit(1)

    # Key pair
    console.print(f"\nKey pair '{host.key_pair_name}'...")
    try:
        ls.get_key_pair(keyPairName=host.key_pair_name)
    except ls.exceptions.NotFoundException:
        console.print(f"  [red]Key pair '{host.key_pair_name}' not found in Lightsail.[/red]")
        console.print("  Create it in the Lightsail console and download the .pem file.")
        raise typer.Exit(1)

    key_path = host.ssh_key.expanduser()
    if not key_path.exists():
        console.print(f"  [red]Local .pem missing:[/red] {key_path}")
        raise typer.Exit(1)
    console.print(f"  [green]OK[/green] — exists in Lightsail, local key at {key_path}")

    # Instance
    console.print(f"\nInstance '{host.instance_name}'...")
    instance_exists = False
    try:
        resp = ls.get_instance(instanceName=host.instance_name)
        state = resp["instance"]["state"]["name"]
        if state == "running":
            console.print(f"  [green]Already running[/green]")
            instance_exists = True
        elif state == "stopped":
            console.print("  Exists but stopped — starting...")
            ls.start_instance(instanceName=host.instance_name)
            _wait_instance(ls, host.instance_name, "running")
            instance_exists = True
        else:
            console.print(f"  State: {state} — waiting...")
            _wait_instance(ls, host.instance_name, "running")
            instance_exists = True
    except ls.exceptions.NotFoundException:
        pass

    if not instance_exists:
        console.print(f"  Creating (blueprint={host.blueprint_id}, bundle={host.bundle_id})...")
        ls.create_instances(
            instanceNames=[host.instance_name],
            availabilityZone=f"{host.aws_region}a",
            blueprintId=host.blueprint_id,
            bundleId=host.bundle_id,
            keyPairName=host.key_pair_name,
        )
        console.print("  Waiting for instance (may take ~60s)...")
        _wait_instance(ls, host.instance_name, "running", timeout=180)
        console.print("  [green]Instance running[/green]")

    # Static IP
    console.print(f"\nStatic IP '{host.static_ip_name}'...")
    ip_address = None
    try:
        resp = ls.get_static_ip(staticIpName=host.static_ip_name)
        sip = resp["staticIp"]
        ip_address = sip["ipAddress"]
        if sip.get("isAttached") and sip.get("attachedTo") == host.instance_name:
            console.print(f"  [green]Already attached:[/green] {ip_address}")
        elif sip.get("isAttached"):
            console.print(f"  [red]Attached to '{sip['attachedTo']}', not '{host.instance_name}'[/red]")
            raise typer.Exit(1)
        else:
            console.print(f"  Exists ({ip_address}), attaching...")
            ls.attach_static_ip(staticIpName=host.static_ip_name, instanceName=host.instance_name)
            console.print(f"  [green]Attached[/green]")
    except ls.exceptions.NotFoundException:
        console.print("  Allocating...")
        ls.allocate_static_ip(staticIpName=host.static_ip_name)
        resp = ls.get_static_ip(staticIpName=host.static_ip_name)
        ip_address = resp["staticIp"]["ipAddress"]
        ls.attach_static_ip(staticIpName=host.static_ip_name, instanceName=host.instance_name)
        console.print(f"  [green]Allocated and attached: {ip_address}[/green]")

    # Firewall — open only what we need, close Lightsail defaults (80, 443, 22)
    console.print(f"\nConfiguring firewall...")
    for port, label in [(22, "SSH (initial)"), (2222, "SSH (hardened)")]:
        try:
            ls.open_instance_public_ports(
                instanceName=host.instance_name,
                portInfo={"fromPort": port, "toPort": port, "protocol": "tcp"},
            )
            console.print(f"  Port {port} open ({label})")
        except Exception as e:
            console.print(f"  [yellow]Port {port}: {e}[/yellow]")
    for port in (80, 443, 8080, 8443):
        try:
            ls.close_instance_public_ports(
                instanceName=host.instance_name,
                portInfo={"fromPort": port, "toPort": port, "protocol": "tcp"},
            )
        except Exception:
            pass  # Fine if the port was never open

    # Update config with the IP
    if ip_address and ip_address != host.ip:
        if _update_toml_field(resolved_config, "ip", ip_address):
            console.print(f"\nUpdated host.ip = {ip_address} in {resolved_config.name}")
        else:
            console.print(f"\n[red]Failed to write IP to {resolved_config.name}.[/red]")
            console.print(f"Manually add [bold]ip = \"{ip_address}\"[/bold] to the [host] section.")

    # Clear known_hosts for this IP to avoid SSH host key warnings
    if ip_address:
        _run_local(["ssh-keygen", "-R", ip_address], check=False)
        console.print(f"Cleared known_hosts for {ip_address}")

    console.print(f"\n[green bold]Instance ready![/green bold]")
    console.print(f"  IP:     {ip_address}")
    console.print(f"  Region: {host.aws_region}")
    console.print(f"\nNext: clawctl server deploy --initial && clawctl server setup --initial")


def _wait_instance(ls, name: str, target: str, timeout: int = 120) -> None:
    """Poll until instance reaches target state."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = ls.get_instance(instanceName=name)
            if resp["instance"]["state"]["name"] == target:
                return
        except Exception:
            pass
        time.sleep(5)
    console.print(f"[red]Instance '{name}' did not reach '{target}' within {timeout}s[/red]")
    raise typer.Exit(1)


# ---------------------------------------------------------------------------
# clawctl server destroy
# ---------------------------------------------------------------------------

def host_destroy(
    confirm: Annotated[
        bool,
        typer.Option("--confirm", help="Required to actually destroy the instance"),
    ] = False,
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Destroy the Lightsail instance and release the static IP."""
    cfg, host, resolved_config = _get_host(config)

    if not confirm:
        console.print("This will [red bold]DELETE[/red bold] the Lightsail instance and release the static IP.")
        console.print("The key pair is preserved.")
        console.print(f"\n  Instance: {host.instance_name}")
        console.print(f"  Static IP: {host.static_ip_name}")
        console.print("\nRun with [bold]--confirm[/bold] to proceed.")
        raise typer.Exit(1)

    ls = _get_boto3_client(host, "lightsail")

    # Detach static IP
    try:
        resp = ls.get_static_ip(staticIpName=host.static_ip_name)
        if resp["staticIp"].get("isAttached"):
            console.print(f"Detaching static IP '{host.static_ip_name}'...")
            ls.detach_static_ip(staticIpName=host.static_ip_name)
            time.sleep(3)
    except Exception:
        pass

    # Delete instance
    try:
        console.print(f"Deleting instance '{host.instance_name}'...")
        ls.delete_instance(instanceName=host.instance_name)
        console.print("  [green]Deleted[/green]")
    except ls.exceptions.NotFoundException:
        console.print("  Instance not found, skipping.")

    # Release static IP
    try:
        console.print(f"Releasing static IP '{host.static_ip_name}'...")
        ls.release_static_ip(staticIpName=host.static_ip_name)
        console.print("  [green]Released[/green]")
    except ls.exceptions.NotFoundException:
        console.print("  Static IP not found, skipping.")

    # Clear IP in config
    if not _update_toml_field(resolved_config, "ip", ""):
        console.print("[yellow]Could not clear host.ip in config — edit manually if needed.[/yellow]")
    console.print("\n[green]Teardown complete. Key pair preserved.[/green]")


# ---------------------------------------------------------------------------
# clawctl server teardown
# ---------------------------------------------------------------------------

def host_teardown(
    confirm: Annotated[
        bool,
        typer.Option("--confirm", help="Required to actually tear down"),
    ] = False,
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Stop and remove all containers on the remote host."""
    cfg, host, _resolved = _get_host(config)

    if not confirm:
        console.print("This will stop and remove all OpenClaw containers on the server.")
        console.print("Run with [bold]--confirm[/bold] to proceed.")
        raise typer.Exit(1)

    console.print(f"Tearing down containers on [bold]{host.ip}[/bold]...\n")

    teardown_script = r"""
export PATH=$HOME/.local/bin:$HOME/.local/venv/clawctl/bin:$PATH
for c in $(docker ps -a --format '{{.Names}}' | grep '^openclaw-'); do
    echo "Stopping $c..."
    docker stop "$c" 2>/dev/null || true
    docker rm "$c" 2>/dev/null || true
    echo "  removed $c"
done
echo "Done"
"""
    cmd = _ssh_cmd(host) + [teardown_script]
    proc = subprocess.run(cmd, text=True)

    if proc.returncode != 0:
        console.print(f"\n[red]Teardown failed (exit {proc.returncode}).[/red]")
        raise typer.Exit(proc.returncode)

    console.print("\n[green]Teardown complete.[/green]")


# ---------------------------------------------------------------------------
# clawctl server bootstrap
# ---------------------------------------------------------------------------

def host_bootstrap(
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Full one-shot setup: provision → deploy → setup → deploy → ready.

    Creates the Lightsail instance, pushes code and secrets, hardens the server,
    installs everything, and leaves the server ready to connect to.
    """
    from rich.rule import Rule

    def banner(step: int, title: str) -> None:
        console.print()
        console.print(Rule(f"[bold]Step {step}/5: {title}[/bold]"))
        console.print()

    # Step 1: Provision
    banner(1, "Provision instance")
    host_provision(config=config)

    # Step 2: Initial deploy (ubuntu@22)
    banner(2, "Initial deploy (ubuntu@22)")
    host_deploy(initial=True, config=config)

    # Step 3: Initial setup — harden, reboot, SSH moves to 2222
    banner(3, "Initial setup (harden + reboot)")
    host_setup(step=None, initial=True, config=config)

    # Step 4: Final deploy (openclaw@2222) — reinstalls clawctl
    banner(4, "Final deploy (openclaw@2222)")
    host_deploy(initial=False, config=config)

    # Step 5: Final setup — build Docker, provision users, start web
    banner(5, "Final setup (Docker + users + web)")
    host_setup(step=None, initial=False, config=config)

    console.print()
    console.print(Rule("[bold green]Bootstrap complete[/bold green]"))
    console.print()

    # Show final status
    cfg, host, _resolved = _get_host(config)
    console.print(f"  Server: [bold]{host.ssh_user}@{host.ip}:{host.ssh_port}[/bold]")
    console.print(f"  Region: {host.aws_region}")
    console.print()
    console.print("Next steps:")
    console.print("  clawctl server status -c <config>    — verify everything is running")
    console.print("  clawctl server url -c <config>       — get Tailscale URLs")
