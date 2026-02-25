"""Instance management endpoints."""

from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from clawctl_web.auth import get_current_user
from clawlib.core.config import find_config_path, load_config
from clawlib.core.docker_manager import DockerManager
from clawlib.core.paths import Paths
from clawlib.core.secrets import SecretsManager
from clawlib.core.user_manager import GATEWAY_TOKEN_SECRET_NAME, UserManager
import json

router = APIRouter()


def _get_tailscale_ip() -> str | None:
    """Get Tailscale IPv4 address if available."""
    try:
        result = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        )
        ip = result.stdout.strip()
        return ip if ip else None
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _get_tailscale_hostname() -> str | None:
    """Get Tailscale MagicDNS hostname if available."""
    try:
        result = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        )
        status_data = json.loads(result.stdout)
        self_info = status_data.get("Self", {})
        dns_name = self_info.get("DNSName", "")
        # Remove trailing dot if present (DNS FQDN format, but breaks URLs)
        if dns_name:
            dns_name = dns_name.rstrip(".")
        return dns_name if dns_name else None
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return None


def _is_tailscale_serve_enabled(username: str, paths: Paths) -> bool:
    """Check if Tailscale Serve is enabled for a user by reading their openclaw.json."""
    try:
        config_path = paths.user_openclaw_config(username)
        if not config_path.exists():
            return False
        config_data = json.loads(config_path.read_text())
        gateway = config_data.get("gateway", {})
        tailscale_config = gateway.get("tailscale", {})
        return tailscale_config.get("mode") == "serve"
    except Exception:
        return False


def _get_docker_manager(config_path: Path | None = None) -> DockerManager:
    """Get DockerManager instance."""
    config_path_resolved = find_config_path(config_path)
    if not config_path_resolved:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configuration file not found",
        )
    config = load_config(config_path_resolved)
    return DockerManager(config)


@router.get("/")
async def list_instances(
    _user: str = Depends(get_current_user),
    config_path: Path | None = None,
):
    """Get status of all instances."""
    docker_mgr = _get_docker_manager(config_path)
    config = load_config(find_config_path(config_path))
    paths = Paths(config.clawctl.data_root, config.clawctl.build_root)
    secrets_mgr = SecretsManager(paths)
    tailscale_ip = _get_tailscale_ip()
    statuses = docker_mgr.get_all_statuses()

    # Get all configured users
    configured_users = {user.name: user for user in config.users}
    
    # Also find containers that exist but aren't in config (orphaned containers)
    import docker
    orphaned_containers = {}
    try:
        all_containers = docker_mgr.client.containers.list(all=True)
        for container in all_containers:
            # Check if it's an openclaw container
            if container.name.startswith("openclaw-"):
                username = container.name.replace("openclaw-", "")
                if username not in configured_users:
                    # Get status and port for orphaned container
                    container_status = container.status
                    port = None
                    try:
                        ports = container.attrs.get("NetworkSettings", {}).get("Ports", {})
                        bindings = ports.get("18789/tcp")
                        if bindings:
                            port = bindings[0].get("HostPort")
                    except Exception:
                        pass
                    orphaned_containers[username] = {
                        "status": container_status,
                        "port": port,
                    }
    except Exception:
        # If we can't list containers, just use configured users
        pass

    result = []
    # Add configured users
    for username, user in configured_users.items():
        info = statuses.get(username, {"status": "unknown", "port": "-"})
        port = info["port"] if info["port"] != "-" else None
        
        # Get management URLs
        management_urls = []
        if port:
            gateway_token = secrets_mgr.read_secret(username, GATEWAY_TOKEN_SECRET_NAME)
            if not gateway_token:
                gateway_token = secrets_mgr.read_secret(username, "gateway_token")
            
            # Check if Tailscale Serve is enabled in config
            # Note: Even if enabled, gateways bind to loopback inside containers and need
            # Tailscale Serve configured INSIDE the container (not on host). Since Tailscale
            # isn't installed in containers, we use Docker port mapping instead.
            tailscale_serve_enabled = _is_tailscale_serve_enabled(username, paths)
            
            # basePath is always set for reverse-proxy setups (/gateway/{username})
            # We compute it directly instead of reading from the container config
            # (which may have restrictive permissions from the gateway process)
            base_path = f"/gateway/{username}"
            
            if gateway_token:
                from urllib.parse import urlencode
                # Prefer HTTPS via Tailscale Serve + nginx reverse proxy
                tailscale_hostname = _get_tailscale_hostname()
                if tailscale_hostname:
                    ws_url = f"wss://{tailscale_hostname}{base_path}"
                    qs = urlencode({"token": gateway_token, "gatewayUrl": ws_url})
                    management_urls.append(f"https://{tailscale_hostname}{base_path}/?{qs}")
                # Fallback: direct HTTP via Docker port mapping
                token_param = f"?token={gateway_token}"
                if tailscale_ip:
                    management_urls.append(f"http://{tailscale_ip}:{port}{base_path}/{token_param}")
                management_urls.append(f"http://localhost:{port}{base_path}/{token_param}")
            else:
                tailscale_hostname = _get_tailscale_hostname()
                if tailscale_hostname:
                    management_urls.append(f"https://{tailscale_hostname}{base_path}/")
                if tailscale_ip:
                    management_urls.append(f"http://{tailscale_ip}:{port}{base_path}/")
                management_urls.append(f"http://localhost:{port}{base_path}/")
        
        # Get model pricing if available
        model_pricing = None
        if user and user.agent.model:
            # Try to get pricing from OpenRouter models cache
            try:
                from clawctl_web.endpoints.models import _get_cached_models
                cached_models = _get_cached_models()
                if cached_models:
                    model_match = next(
                        (m for m in cached_models if m.get("id") == user.agent.model),
                        None
                    )
                    if model_match:
                        model_pricing = model_match.get("pricing")
            except Exception:
                pass
        
        result.append(
            {
                "username": username,
                "status": info["status"],
                "port": port,
                "management_urls": management_urls,
                "model": user.agent.model if user else None,
                "model_pricing": model_pricing,
                "in_config": True,
            }
        )
    
    # Add orphaned containers (exist but not in config)
    for username, info in orphaned_containers.items():
        port = info["port"]
        management_urls = []
        if port:
            gateway_token = secrets_mgr.read_secret(username, GATEWAY_TOKEN_SECRET_NAME)
            if not gateway_token:
                gateway_token = secrets_mgr.read_secret(username, "gateway_token")
            
            # Check if Tailscale Serve is enabled in config
            # Note: Even if enabled, gateways bind to loopback inside containers and need
            # Tailscale Serve configured INSIDE the container (not on host). Since Tailscale
            # isn't installed in containers, we use Docker port mapping instead.
            tailscale_serve_enabled = _is_tailscale_serve_enabled(username, paths)
            
            if gateway_token:
                token_param = f"?token={gateway_token}"
                # Use Docker port mapping URLs (gateways accessible via mapped ports)
                # HTTP is fine since we're on Tailscale private network
                if tailscale_ip:
                    management_urls.append(f"http://{tailscale_ip}:{port}{token_param}")
                # Localhost URL (for local access)
                management_urls.append(f"http://localhost:{port}{token_param}")
            else:
                # No token - just show port-based URLs
                if tailscale_ip:
                    management_urls.append(f"http://{tailscale_ip}:{port}")
                management_urls.append(f"http://localhost:{port}")
        
        result.append(
            {
                "username": username,
                "status": info["status"],
                "port": port,
                "management_urls": management_urls,
                "model": None,
                "in_config": False,
            }
        )

    return {"instances": result}


@router.get("/{username}/status")
async def get_instance_status(
    username: str,
    _user: str = Depends(get_current_user),
):
    """Get status of a specific instance."""
    docker_mgr = _get_docker_manager()
    config = load_config(find_config_path())
    paths = Paths(config.clawctl.data_root, config.clawctl.build_root)
    secrets_mgr = SecretsManager(paths)
    tailscale_ip = _get_tailscale_ip()
    
    status_val = docker_mgr.get_container_status(username)
    port = docker_mgr.get_container_port(username) if status_val == "running" else None
    
    # Get management URLs
    management_urls = []
    if port:
        gateway_token = secrets_mgr.read_secret(username, GATEWAY_TOKEN_SECRET_NAME)
        if not gateway_token:
            gateway_token = secrets_mgr.read_secret(username, "gateway_token")
        
        # Check if Tailscale Serve is enabled in config
        # Note: Even if enabled, gateways bind to loopback inside containers and need
        # Tailscale Serve configured INSIDE the container (not on host). Since Tailscale
        # isn't installed in containers, we use Docker port mapping instead.
        tailscale_serve_enabled = _is_tailscale_serve_enabled(username, paths)
        
        if gateway_token:
            token_param = f"?token={gateway_token}"
            # Gateways require HTTPS or localhost for secure context (device identity)
            # HTTP over Tailscale IP doesn't satisfy this requirement
            # Frontend will show SSH port forwarding instructions
            if tailscale_ip:
                # Still show the URL, but frontend will warn about secure context
                management_urls.append(f"http://{tailscale_ip}:{port}{token_param}")
            # Localhost URL (works if accessed via SSH port forwarding)
            management_urls.append(f"http://localhost:{port}{token_param}")
        else:
            # No token - just show port-based URLs
            if tailscale_ip:
                management_urls.append(f"http://{tailscale_ip}:{port}")
            management_urls.append(f"http://localhost:{port}")

    user = config.get_user(username)
    model = user.agent.model if user else None

    return {
        "username": username,
        "status": status_val,
        "port": port,
        "management_urls": management_urls,
        "model": model,
    }


@router.post("/{username}/start")
async def start_instance(
    username: str,
    _user: str = Depends(get_current_user),
):
    """Start an instance."""
    docker_mgr = _get_docker_manager()
    config = load_config(find_config_path())

    if not config.get_user(username):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{username}' not found",
        )

    if not docker_mgr.container_exists(username):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Container for '{username}' does not exist",
        )

    try:
        docker_mgr.start_container(username)
        # Run openclaw doctor --fix to ensure full authentication
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Running openclaw doctor --fix for started container {username}")
        doctor_success = docker_mgr.run_doctor_fix(username)
        if not doctor_success:
            logger.warning(
                f"openclaw doctor --fix failed for {username} after start. "
                "Gateway authentication may not be fully configured."
            )
        return {"message": f"Started container for '{username}'", "username": username}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start container: {str(e)}",
        )


@router.post("/{username}/stop")
async def stop_instance(
    username: str,
    _user: str = Depends(get_current_user),
):
    """Stop an instance."""
    docker_mgr = _get_docker_manager()

    if not docker_mgr.container_exists(username):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Container for '{username}' does not exist",
        )

    try:
        docker_mgr.stop_container(username)
        return {"message": f"Stopped container for '{username}'", "username": username}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop container: {str(e)}",
        )


@router.get("/{username}/discord/pairing")
async def list_discord_pairing(
    username: str,
    _user: str = Depends(get_current_user),
):
    """List pending Discord pairing requests for an instance."""
    docker_mgr = _get_docker_manager()
    if not docker_mgr.container_exists(username):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Container for '{username}' does not exist",
        )
    requests = docker_mgr.list_discord_pairing(username)
    return {"requests": requests}


@router.post("/{username}/discord/pairing/{code}/approve")
async def approve_discord_pairing(
    username: str,
    code: str,
    _user: str = Depends(get_current_user),
):
    """Approve a pending Discord pairing request."""
    docker_mgr = _get_docker_manager()
    if not docker_mgr.container_exists(username):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Container for '{username}' does not exist",
        )
    success, message = docker_mgr.approve_discord_pairing(username, code)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )
    return {"message": message, "username": username, "code": code}


@router.post("/{username}/restart")
async def restart_instance(
    username: str,
    _user: str = Depends(get_current_user),
):
    """Restart an instance.
    
    Regenerates openclaw.json with gateway token authentication before restarting
    to ensure full authentication is set up for gateway URLs and Discord integration.
    """
    config = load_config(find_config_path())
    user_mgr = UserManager(config)

    if not user_mgr.docker.container_exists(username):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Container for '{username}' does not exist",
        )

    try:
        user_mgr.restart_user(username)
        return {"message": f"Restarted container for '{username}'", "username": username}
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to restart container: {str(e)}",
        )
