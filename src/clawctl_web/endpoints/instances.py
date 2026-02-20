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
from clawlib.core.user_manager import GATEWAY_TOKEN_SECRET_NAME

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
            
            if gateway_token:
                if tailscale_ip:
                    management_urls.append(f"http://{tailscale_ip}:{port}?token={gateway_token}")
                management_urls.append(f"http://localhost:{port}?token={gateway_token}")
            else:
                if tailscale_ip:
                    management_urls.append(f"http://{tailscale_ip}:{port}")
                management_urls.append(f"http://localhost:{port}")
        
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
            
            if gateway_token:
                if tailscale_ip:
                    management_urls.append(f"http://{tailscale_ip}:{port}?token={gateway_token}")
                management_urls.append(f"http://localhost:{port}?token={gateway_token}")
            else:
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
        
        if gateway_token:
            if tailscale_ip:
                management_urls.append(f"http://{tailscale_ip}:{port}?token={gateway_token}")
            management_urls.append(f"http://localhost:{port}?token={gateway_token}")
        else:
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


@router.post("/{username}/restart")
async def restart_instance(
    username: str,
    _user: str = Depends(get_current_user),
):
    """Restart an instance."""
    docker_mgr = _get_docker_manager()

    if not docker_mgr.container_exists(username):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Container for '{username}' does not exist",
        )

    try:
        docker_mgr.restart_container(username)
        return {"message": f"Restarted container for '{username}'", "username": username}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to restart container: {str(e)}",
        )
