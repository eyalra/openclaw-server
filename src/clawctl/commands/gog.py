"""clawctl gog — manage gog (gogcli) Google Workspace integration."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import docker
import docker.errors
import typer
from rich.console import Console
from rich.panel import Panel

from clawctl.core.config import load_config_or_exit
from clawctl.core.docker_manager import CONTAINER_PREFIX

console = Console()

CONTAINER_EXEC_TIMEOUT = 30  # seconds for non-interactive exec calls


def _get_docker_client(cfg) -> docker.DockerClient:
    """Return a Docker client using the same discovery logic as DockerManager."""
    import os
    from pathlib import Path as _Path

    docker_host = os.environ.get("DOCKER_HOST")
    if not docker_host:
        candidates = [
            _Path.home() / ".colima" / "default" / "docker.sock",
            _Path.home() / ".docker" / "run" / "docker.sock",
        ]
        for candidate in candidates:
            if candidate.exists() and not _Path("/var/run/docker.sock").exists():
                docker_host = f"unix://{candidate}"
                break

    if docker_host:
        return docker.DockerClient(base_url=docker_host)
    return docker.from_env()


def _exec_in_container(
    client: docker.DockerClient,
    container_name: str,
    cmd: list[str],
    *,
    env: dict[str, str] | None = None,
) -> tuple[int, str]:
    """Run a command inside a container and return (exit_code, output)."""
    try:
        container = client.containers.get(container_name)
    except docker.errors.NotFound:
        return 1, f"Container '{container_name}' not found."

    # Check container status - can't exec into restarting containers
    container.reload()
    if container.status == "restarting":
        return 1, f"Container '{container_name}' is restarting. Wait for it to be running, or check logs: docker logs {container_name}"
    if container.status != "running":
        return 1, f"Container '{container_name}' is not running (status: {container.status}). Start it first: docker start {container_name}"

    try:
        result = container.exec_run(
            cmd,
            environment=env or {},
            demux=False,
        )
        output = result.output.decode("utf-8", errors="replace") if result.output else ""
        return result.exit_code, output
    except docker.errors.APIError as e:
        if "409" in str(e) and "restarting" in str(e).lower():
            return 1, f"Container '{container_name}' is restarting. Wait for it to be running, or check logs: docker logs {container_name}"
        raise


def run_gog_auth(
    username: str,
    email: str,
    client: docker.DockerClient,
    *,
    services: str = "gmail",
    readonly: bool = False,
    secrets_mgr=None,
) -> bool:
    """Run the gog OAuth flow for a user. Returns True on success.

    Uses the --remote two-step flow:
      Step 1: print auth URL
      Step 2: exchange redirect URL for token
    """
    container_name = f"{CONTAINER_PREFIX}-{username}"
    
    # Read secrets to pass as environment variables for exec commands
    exec_env = {}
    if secrets_mgr:
        keyring_password = secrets_mgr.read_secret(username, "gog_keyring_password")
        if keyring_password:
            exec_env["GOG_KEYRING_PASSWORD"] = keyring_password.strip()

    # Step 1: get the authorization URL
    console.print()
    console.print(f"[bold]Starting gog OAuth authorization for {email}...[/bold]")
    console.print()

    # gog expects --services as a single comma-separated string argument
    # Clean up the services string to ensure no extra whitespace or issues
    services_clean = ",".join([s.strip() for s in services.split(",") if s.strip()])
    cmd = ["gog", "auth", "add", email, "--services", services_clean, "--remote", "--step=1"]
    
    if readonly:
        cmd.append("--readonly")
    
    console.print(f"   [dim]Debug: Services: {services_clean}, Readonly: {readonly}[/dim]")
    
    exit_code, output = _exec_in_container(
        client,
        container_name,
        cmd,
        env=exec_env,
    )

    if exit_code != 0:
        console.print(f"[red]gog auth step 1 failed:[/red]\n{output.strip()}")
        return False

    # Parse the auth_url from tab-separated output: "auth_url\t<url>"
    auth_url = None
    for line in output.splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2 and parts[0].strip() == "auth_url":
            auth_url = parts[1].strip()
            break

    if not auth_url:
        console.print(f"[red]Could not parse auth URL from gog output:[/red]\n{output.strip()}")
        return False

    # Debug: Parse and validate the scope parameter
    try:
        from urllib.parse import urlparse, parse_qs, unquote
        parsed = urlparse(auth_url)
        params = parse_qs(parsed.query)
        if "scope" in params:
            scope_param = params["scope"][0]
            scopes = unquote(scope_param).split()
            console.print(f"   [dim]Debug: Requested scopes ({len(scopes)}):[/dim]")
            for scope in scopes:
                if scope.startswith("https://"):
                    console.print(f"   [dim]    {scope}[/dim]")
                else:
                    console.print(f"   [dim]    {scope} (identity scope)[/dim]")
    except Exception as e:
        console.print(f"   [dim]Debug: Could not parse scopes: {e}[/dim]")

    # Display the URL for the user to open
    # CRITICAL: Must display URL without wrapping to prevent breaking scope parameter
    # Rich Panel wraps long URLs, breaking the scope parameter. Display separately.
    console.print()
    console.print(Panel(
        "[bold]Open this URL in your browser:[/bold]",
        title="gog OAuth Authorization",
        border_style="blue",
    ))
    console.print()
    # Display URL on its own line without any wrapping - use a simple print
    # This ensures the URL stays intact for copying
    print(auth_url)  # Use plain print to avoid Rich wrapping
    console.print()
    console.print(
        Panel(
            "[bold]After authorizing:[/bold]\n"
            "Google will redirect to a localhost URL that your browser cannot load.\n"
            "Copy the [bold]full redirect URL[/bold] from the address bar and paste it below.",
            title="Next Step",
            border_style="yellow",
        )
    )
    console.print()

    # Step 2: prompt for redirect URL and exchange
    redirect_url = typer.prompt("  Paste the full redirect URL here")
    if not redirect_url.strip():
        console.print("[yellow]Aborted — no redirect URL provided.[/yellow]")
        return False

    # Clean up services string for step 2
    services_clean = ",".join([s.strip() for s in services.split(",") if s.strip()])
    cmd = [
        "gog", "auth", "add", email,
        "--services", services_clean,
        "--remote", "--step=2",
        f"--auth-url={redirect_url.strip()}",
    ]
    
    if readonly:
        cmd.append("--readonly")
    
    exit_code, output = _exec_in_container(
        client,
        container_name,
        cmd,
        env=exec_env,
    )

    if exit_code != 0:
        console.print(f"[red]gog auth step 2 failed:[/red]\n{output.strip()}")
        return False

    # Verify
    exit_code, output = _exec_in_container(
        client,
        container_name,
        ["gog", "auth", "list"],
        env=exec_env,
    )
    authorized = email.lower() in output.lower()

    if authorized:
        console.print(f"[green]✓ gog authorized for {email}[/green]")
    else:
        console.print(
            f"[yellow]Auth flow completed but '{email}' not found in gog auth list.[/yellow]\n"
            f"Output: {output.strip()}"
        )

    return authorized


def gog_setup(
    name: Annotated[str, typer.Argument(help="Username to set up gog for")],
    services: Annotated[
        str,
        typer.Option(
            "--services",
            help="Comma-separated Google services to authorize",
        ),
    ] = "gmail",
    readonly: Annotated[
        bool,
        typer.Option(
            "--readonly",
            help="Use read-only scopes where available",
        ),
    ] = False,
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Complete gog OAuth authorization for a user's Google account.

    Run this after `clawctl user add` to authorize gog to access the user's
    Google Workspace. The container must be running. A browser URL will be
    shown — open it, authorize access, then paste the redirect URL back here.

    The container seeds gog client credentials automatically from
    GOG_CLIENT_ID / GOG_CLIENT_SECRET on first start. This command only
    handles the per-user OAuth token exchange.
    """
    cfg = load_config_or_exit(config)
    user = cfg.get_user(name)

    if user is None:
        console.print(
            f"[red]User '{name}' not found in config.[/red] "
            f"Add a [[users]] block with name = \"{name}\" to clawctl.toml first."
        )
        raise typer.Exit(1)

    if not user.skills.gog.enabled:
        console.print(
            f"[yellow]gog skill is not enabled for '{name}'.[/yellow] "
            "Set skills.gog.enabled = true in clawctl.toml."
        )
        raise typer.Exit(1)

    if not user.skills.gog.email:
        console.print(
            f"[yellow]No email configured for '{name}'s gog skill.[/yellow] "
            "Set skills.gog.email in clawctl.toml."
        )
        raise typer.Exit(1)

    client = _get_docker_client(cfg)
    container_name = f"{CONTAINER_PREFIX}-{name}"

    # Verify container is running
    try:
        container = client.containers.get(container_name)
        if container.status != "running":
            console.print(
                f"[red]Container '{container_name}' is not running (status: {container.status}).[/red] "
                f"Run `clawctl start {name}` first."
            )
            raise typer.Exit(1)
    except docker.errors.NotFound:
        console.print(
            f"[red]Container '{container_name}' not found.[/red] "
            f"Run `clawctl user add {name}` first."
        )
        raise typer.Exit(1)

    # Check if gog credentials are seeded (entrypoint should have done this)
    exit_code, output = _exec_in_container(
        client,
        container_name,
        ["gog", "auth", "status"],
    )
    if "credentials.json" in output and "config_exists: false" in output:
        console.print(
            "[yellow]Warning: gog credentials not yet seeded.[/yellow]\n"
            "Ensure GOG_CLIENT_ID and GOG_CLIENT_SECRET secrets exist and restart the container."
        )

    # Check if already authorized
    exit_code, output = _exec_in_container(client, container_name, ["gog", "auth", "list"])
    if exit_code == 0 and user.skills.gog.email.lower() in output.lower():
        console.print(
            f"[green]gog is already authorized for {user.skills.gog.email}.[/green]"
        )
        if not typer.confirm("Re-authorize anyway?", default=False):
            raise typer.Exit(0)

    # Get secrets manager to pass keyring password to exec commands
    from clawctl.core.secrets import SecretsManager
    from clawctl.core.paths import Paths
    secrets_mgr = SecretsManager(Paths(cfg.clawctl.data_root, cfg.clawctl.build_root))
    
    success = run_gog_auth(name, user.skills.gog.email, client, services=services, readonly=readonly, secrets_mgr=secrets_mgr)
    if not success:
        raise typer.Exit(1)


def gog_test(
    name: Annotated[str, typer.Argument(help="Username to test gog credentials for")],
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to clawctl.toml"),
    ] = None,
) -> None:
    """Test gog credentials configuration for a user.

    Checks if OAuth client credentials are properly configured and valid.
    This helps diagnose credential setup issues before attempting OAuth authorization.
    """
    cfg = load_config_or_exit(config)
    user = cfg.get_user(name)

    if user is None:
        console.print(
            f"[red]User '{name}' not found in config.[/red] "
            f"Add a [[users]] block with name = \"{name}\" to clawctl.toml first."
        )
        raise typer.Exit(1)

    if not user.skills.gog.enabled:
        console.print(
            f"[yellow]gog skill is not enabled for '{name}'.[/yellow] "
            "Set skills.gog.enabled = true in clawctl.toml."
        )
        raise typer.Exit(1)

    client = _get_docker_client(cfg)
    container_name = f"{CONTAINER_PREFIX}-{name}"

    # Verify container exists
    try:
        container = client.containers.get(container_name)
    except docker.errors.NotFound:
        console.print(
            f"[red]Container '{container_name}' not found.[/red] "
            f"Run `clawctl user add {name}` first."
        )
        raise typer.Exit(1)

    console.print(f"[bold]Testing gog credentials for '{name}'...[/bold]\n")
    
    # Show email configuration
    console.print("Email configuration:")
    config_email = user.skills.gog.email
    if config_email:
        console.print(f"  Config file (clawctl.toml): [cyan]{config_email}[/cyan]")
        
        # Check what's in openclaw.json
        from clawctl.core.paths import Paths
        paths = Paths(cfg.clawctl.data_root, cfg.clawctl.build_root)
        openclaw_config_path = paths.user_openclaw_config(name)
        if openclaw_config_path.exists():
            try:
                import json
                with open(openclaw_config_path) as f:
                    openclaw_config = json.load(f)
                openclaw_email = openclaw_config.get("hooks", {}).get("gmail", {}).get("account")
                if openclaw_email:
                    if openclaw_email == config_email:
                        console.print(f"  Container config (openclaw.json): [green]{openclaw_email}[/green] [dim]✓ matches[/dim]")
                    else:
                        console.print(f"  Container config (openclaw.json): [yellow]{openclaw_email}[/yellow] [dim]⚠ differs from config file[/dim]")
                        console.print(f"  [yellow]Warning: Email mismatch! Container needs to be recreated to use updated email.[/yellow]")
                else:
                    console.print(f"  Container config (openclaw.json): [yellow]not configured[/yellow]")
            except Exception as e:
                console.print(f"  Container config (openclaw.json): [red]error reading: {e}[/red]")
        else:
            console.print(f"  Container config (openclaw.json): [yellow]file not found[/yellow]")
    else:
        console.print(f"  [yellow]No email configured in clawctl.toml[/yellow]")
    
    console.print()

    # Check container status
    container.reload()
    if container.status == "restarting":
        console.print(
            f"[red]Container is restarting (likely crashing).[/red]"
        )
        
        # Try to inspect the credentials file even if container is restarting
        console.print("\n  Attempting to inspect credentials file...")
        try:
            # Try to read credentials.json from the host mount
            from clawctl.core.paths import Paths
            paths = Paths(cfg.clawctl.data_root, cfg.clawctl.build_root)
            config_dir = paths.user_config_dir(name)
            creds_file = config_dir / "gogcli" / "credentials.json"
            
            if creds_file.exists():
                import json
                try:
                    with open(creds_file) as f:
                        creds_data = json.load(f)
                    console.print(f"  [yellow]Found credentials.json on host[/yellow]")
                    console.print(f"  [dim]  Structure: {list(creds_data.keys())}[/dim]")
                    if "installed" in creds_data:
                        console.print(f"  [dim]  Has 'installed' key: ✓[/dim]")
                        if "client_id" in creds_data["installed"]:
                            cid = creds_data["installed"]["client_id"]
                            console.print(f"  [dim]  Client ID: {cid[:30]}... (length: {len(cid)})[/dim]")
                        else:
                            console.print(f"  [red]  Missing 'client_id' in installed object[/red]")
                        if "client_secret" in creds_data["installed"]:
                            console.print(f"  [dim]  Has client_secret: ✓ (length: {len(creds_data['installed']['client_secret'])})[/dim]")
                        else:
                            console.print(f"  [red]  Missing 'client_secret' in installed object[/red]")
                    else:
                        console.print(f"  [red]  Missing 'installed' key in credentials.json[/red]")
                        console.print(f"  [dim]  Available keys: {list(creds_data.keys())}[/dim]")
                except json.JSONDecodeError as e:
                    console.print(f"  [red]  credentials.json is invalid JSON: {e}[/red]")
                except Exception as e:
                    console.print(f"  [yellow]  Could not read credentials.json: {e}[/yellow]")
            else:
                console.print(f"  [dim]  credentials.json not found at {creds_file}[/dim]")
        except Exception as e:
            console.print(f"  [yellow]  Could not inspect credentials: {e}[/yellow]")
        
        # Show recent logs
        console.print(f"\n  Recent container logs:")
        try:
            logs = container.logs(tail=10).decode('utf-8', errors='replace')
            for line in logs.strip().split('\n')[-5:]:
                console.print(f"  [dim]  {line}[/dim]")
        except Exception as e:
            console.print(f"  [yellow]  Could not read logs: {e}[/yellow]")
        
        console.print(f"\n  Check full logs: [bold]docker logs {container_name}[/bold]")
        console.print("  Common causes:")
        console.print("    - Invalid gog credentials (GOG_CLIENT_ID/SECRET)")
        console.print("    - Corrupted credentials.json file")
        console.print("    - Docker image needs rebuild with updated entrypoint.sh")
        console.print("  Fix:")
        console.print("    1. Rebuild image: docker build -t openclaw-instance:latest --build-arg OPENCLAW_VERSION=latest docker/")
        console.print("    2. Remove and recreate container: clawctl user remove alice && clawctl user add alice")
        raise typer.Exit(1)
    elif container.status != "running":
        console.print(
            f"[yellow]Container is not running (status: {container.status}).[/yellow] "
            f"Starting container to test credentials..."
        )
        try:
            container.start()
            # Wait a moment for container to start
            import time
            for _ in range(10):  # Wait up to 5 seconds
                time.sleep(0.5)
                container.reload()
                if container.status == "running":
                    break
                if container.status == "restarting":
                    console.print(f"[red]Container started but is now restarting (crashing).[/red]")
                    console.print(f"  Check logs: [bold]docker logs {container_name}[/bold]")
                    raise typer.Exit(1)
        except typer.Exit:
            raise
        except Exception as e:
            console.print(f"[red]Failed to start container: {e}[/red]")
            raise typer.Exit(1)

    # Test 1: Check if secrets are mounted
    console.print("1. Checking secrets...")
    from clawctl.core.secrets import SecretsManager
    from clawctl.core.paths import Paths
    secrets_mgr = SecretsManager(Paths(cfg.clawctl.data_root, cfg.clawctl.build_root))
    
    required_secrets = ["gog_client_id", "gog_client_secret", "gog_keyring_password"]
    secrets_ok = True
    for secret_name in required_secrets:
        if secrets_mgr.secret_exists(name, secret_name):
            secret_value = secrets_mgr.read_secret(name, secret_name)
            if secret_value and secret_value.strip():
                console.print(f"   [green]✓[/green] {secret_name}: present")
            else:
                console.print(f"   [red]✗[/red] {secret_name}: empty")
                secrets_ok = False
        else:
            console.print(f"   [red]✗[/red] {secret_name}: missing")
            secrets_ok = False

    if not secrets_ok:
        console.print("\n[yellow]Some secrets are missing or empty. Fix them and try again.[/yellow]")
        raise typer.Exit(1)

    console.print()

    # Test 2: Check gog auth status (credentials.json)
    console.print("2. Checking gog credentials configuration...")
    exit_code, output = _exec_in_container(
        client,
        container_name,
        ["gog", "auth", "status"],
    )

    # Show full debug output
    console.print("   [dim]Debug: gog auth status output:[/dim]")
    for line in output.strip().split("\n"):
        console.print(f"   [dim]  {line}[/dim]")

    if exit_code != 0:
        console.print(f"\n   [red]✗[/red] gog auth status failed (exit code: {exit_code})")
        console.print(f"   Full output: {output.strip()}")
        raise typer.Exit(1)

    # Parse status output - gog auth status outputs tab-separated key-value pairs
    status_lines = output.strip().split("\n")
    credentials_ok = False
    keyring_ok = False
    
    # Check if credentials.json file actually exists
    exit_code_file, output_file = _exec_in_container(
        client,
        container_name,
        ["test", "-f", "/home/node/.config/gogcli/credentials.json"],
    )
    file_exists = exit_code_file == 0
    
    for line in status_lines:
        line = line.strip()
        if not line:
            continue
            
        # Parse space-separated key-value pairs (gog uses spaces, not tabs)
        # Format: "key        value" (multiple spaces)
        parts = line.split(None, 1)  # Split on whitespace, max 1 split
        if len(parts) == 2:
            key = parts[0].strip()
            value = parts[1].strip()
            
            if key == "config_exists":
                if value.lower() == "true":
                    if file_exists:
                        console.print("\n   [green]✓[/green] credentials.json: exists")
                        credentials_ok = True
                    else:
                        console.print("\n   [yellow]⚠[/yellow] config_exists=true but file not found")
                else:
                    console.print("\n   [yellow]⚠[/yellow] credentials.json: not configured")
            elif key == "keyring_backend":
                if value == "file":
                    if not keyring_ok:  # Only print once
                        console.print("   [green]✓[/green] keyring backend: file")
                        keyring_ok = True
                else:
                    console.print(f"   [yellow]⚠[/yellow] keyring backend: {value}")
        else:
            # Fallback for lines that don't match the pattern
            if "credentials.json" in line.lower() and not credentials_ok:
                if "true" in line.lower() or "exists" in line.lower():
                    if file_exists:
                        console.print("\n   [green]✓[/green] credentials.json: exists")
                        credentials_ok = True
            elif "keyring" in line.lower() and "file" in line.lower() and not keyring_ok:
                console.print("   [green]✓[/green] keyring backend: configured")
                keyring_ok = True

    # If we didn't find credentials_ok from parsing, check file directly
    if not credentials_ok and file_exists:
        console.print("\n   [yellow]⚠[/yellow] credentials.json exists but gog status unclear")
        # Try to validate it
        exit_code_val, output_val = _exec_in_container(
            client,
            container_name,
            ["node", "-e", """
                try {
                    const creds = require('/home/node/.config/gogcli/credentials.json');
                    // Check both flattened and installed wrapper formats
                    const clientId = creds.client_id || (creds.installed && creds.installed.client_id);
                    const clientSecret = creds.client_secret || (creds.installed && creds.installed.client_secret);
                    if (clientId && clientSecret) {
                        console.log('File exists and has required fields');
                        process.exit(0);
                    } else {
                        console.log('File exists but missing required fields');
                        process.exit(1);
                    }
                } catch (e) {
                    console.log('File exists but invalid:', e.message);
                    process.exit(1);
                }
            """],
        )
        if exit_code_val == 0:
            console.print("   [green]✓[/green] credentials.json: file is valid")
            credentials_ok = True
        else:
            console.print(f"   [red]✗[/red] credentials.json: {output_val.strip()}")

    if not credentials_ok:
        console.print("\n[yellow]gog credentials not properly configured.[/yellow]")
        console.print("   This usually means:")
        console.print("   - GOG_CLIENT_ID or GOG_CLIENT_SECRET secrets are invalid")
        console.print("   - The container entrypoint failed to set up credentials")
        console.print("   - Check container logs: docker logs {container_name}")
        raise typer.Exit(1)

    console.print()

    # Test 3: Try to read credentials.json directly
    console.print("\n3. Validating credentials.json format...")
    exit_code, output = _exec_in_container(
        client,
        container_name,
        ["node", "-e", """
            try {
                const creds = require('/home/node/.config/gogcli/credentials.json');
                // gog stores credentials in flattened format (client_id/client_secret at top level)
                // even though we send it in 'installed' wrapper format
                const clientId = creds.client_id || (creds.installed && creds.installed.client_id);
                const clientSecret = creds.client_secret || (creds.installed && creds.installed.client_secret);
                
                if (!clientId) {
                    console.log('ERROR: Missing client_id');
                    console.log('  Has creds.client_id:', !!creds.client_id);
                    console.log('  Has creds.installed.client_id:', !!(creds.installed && creds.installed.client_id));
                    process.exit(1);
                }
                if (!clientSecret) {
                    console.log('ERROR: Missing client_secret');
                    console.log('  Has creds.client_secret:', !!creds.client_secret);
                    console.log('  Has creds.installed.client_secret:', !!(creds.installed && creds.installed.client_secret));
                    process.exit(1);
                }
                console.log('OK: credentials.json is valid');
                console.log('Format:', creds.client_id ? 'flattened' : 'installed wrapper');
                console.log('Client ID:', clientId.substring(0, 30) + '...');
                console.log('Client ID length:', clientId.length);
                console.log('Has client_secret:', !!clientSecret);
                console.log('Client secret length:', clientSecret.length);
            } catch (e) {
                console.log('ERROR:', e.message);
                process.exit(1);
            }
        """],
    )

    console.print("   [dim]Debug: credentials.json validation output:[/dim]")
    for line in output.strip().split("\n"):
        console.print(f"   [dim]  {line}[/dim]")

    if exit_code != 0:
        console.print(f"\n   [red]✗[/red] credentials.json validation failed:")
        console.print(f"   {output.strip()}")
        raise typer.Exit(1)
    else:
        # Extract just the OK message for clean display
        ok_line = [l for l in output.strip().split("\n") if l.startswith("OK:")]
        if ok_line:
            console.print(f"\n   [green]✓[/green] {ok_line[0]}")
        else:
            console.print(f"\n   [green]✓[/green] credentials.json is valid")

    console.print()

    # Test 3.5: Try to validate credentials with Google (if possible)
    console.print("\n3.5. Testing credentials with Google API...")
    # Try to get a token or validate the credentials format
    exit_code, output = _exec_in_container(
        client,
        container_name,
        ["sh", "-c", """
            # Try to read and validate the credentials format
            if [ -f /home/node/.config/gogcli/credentials.json ]; then
                echo "Credentials file exists"
                # Check if we can parse it (gog stores in flattened format)
                node -e "
                    const creds = require('/home/node/.config/gogcli/credentials.json');
                    // Check both flattened and installed wrapper formats
                    const clientId = creds.client_id || (creds.installed && creds.installed.client_id);
                    const clientSecret = creds.client_secret || (creds.installed && creds.installed.client_secret);
                    const clientIdPattern = /^[0-9-]+\\.apps\\.googleusercontent\\.com$/;
                    
                    if (!clientId || !clientSecret) {
                        console.log('ERROR: Missing client_id or client_secret');
                        process.exit(1);
                    }
                    
                    console.log('Client ID format:', clientIdPattern.test(clientId) ? 'valid' : 'invalid');
                    console.log('Client ID length:', clientId.length);
                    console.log('Client secret length:', clientSecret.length);
                    console.log('Format:', creds.client_id ? 'flattened' : 'installed wrapper');
                    // auth_uri and token_uri are only in installed wrapper format
                    if (creds.installed) {
                        console.log('Has auth_uri:', !!creds.installed.auth_uri);
                        console.log('Has token_uri:', !!creds.installed.token_uri);
                    }
                " 2>&1 || echo "Failed to parse credentials"
            else
                echo "Credentials file not found"
            fi
        """],
    )
    
    console.print("   [dim]Debug: Credential validation output:[/dim]")
    for line in output.strip().split("\n"):
        if line.strip():
            console.print(f"   [dim]  {line}[/dim]")

    console.print()

    # Test 4: Check authorization status
    console.print("\n4. Authorization status:")
    if user.skills.gog.email:
        # Check if already authorized
        exit_code, output = _exec_in_container(
            client,
            container_name,
            ["gog", "auth", "list"],
        )
        
        console.print("   [dim]Debug: gog auth list output:[/dim]")
        for line in output.strip().split("\n"):
            console.print(f"   [dim]  {line}[/dim]")
        
        if exit_code == 0:
            if user.skills.gog.email.lower() in output.lower():
                console.print(f"\n   [green]✓[/green] Account '{user.skills.gog.email}' is already authorized")
            else:
                console.print(f"\n   [yellow]⚠[/yellow] Account '{user.skills.gog.email}' not yet authorized")
                console.print(f"   Run: clawctl gog setup {name}")
        else:
            console.print(f"\n   [yellow]⚠[/yellow] Could not check authorization status (exit code: {exit_code})")
            console.print(f"   Output: {output.strip()}")
    else:
        console.print("   [yellow]⚠[/yellow] No email configured - cannot check authorization")
        console.print(f"   Set skills.gog.email in clawctl.toml for user '{name}'")

    console.print()
    console.print("[green]✓ All credential checks passed![/green]")
    console.print("\nNext steps:")
    if user.skills.gog.email:
        console.print(f"  - Run [bold]clawctl gog setup {name}[/bold] to authorize Google account access")
    else:
        console.print(f"  - Configure email in clawctl.toml: [users.skills.gog] email = \"your@email.com\"")
        console.print(f"  - Then run [bold]clawctl gog setup {name}[/bold]")
