"""User management endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from clawctl_web.auth import get_current_user
from clawlib.core.config import find_config_path, load_config

router = APIRouter()


def _configure_agent_auth(
    docker_mgr: DockerManager,
    username: str,
    model: str,
    secrets_mgr: SecretsManager,
) -> None:
    """Configure the agent's auth provider based on the model.
    
    This ensures OpenClaw uses the correct API provider by clearing
    cached auth state so it reconfigures with the correct provider.
    """
    model_lower = model.lower()
    container_name = f"openclaw-{username}"
    
    try:
        container = docker_mgr.client.containers.get(container_name)
        
        # Clear agent auth state to force reconfiguration
        # This removes any cached provider preference
        # OpenClaw will detect the correct provider from available env vars
        agent_auth_dir = "/home/node/.openclaw/agents/main/agent"
        commands = [
            f"rm -f {agent_auth_dir}/auth-profiles.json",
            f"rm -f {agent_auth_dir}/auth.json",
        ]
        
        for cmd in commands:
            try:
                exec_result = container.exec_run(
                    cmd,
                    user="1000",
                    workdir="/home/node",
                )
                if exec_result.exit_code != 0:
                    # Non-fatal - file might not exist
                    pass
            except Exception:
                # Non-fatal - continue
                pass
        
    except Exception:
        # Non-fatal - configuration will happen on next agent interaction
        pass


@router.get("/")
async def list_users(
    _user: str = Depends(get_current_user),
    config_path: Path | None = None,
):
    """List all configured users."""
    config_path_resolved = find_config_path(config_path)
    if not config_path_resolved:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configuration file not found",
        )
    config = load_config(config_path_resolved)

    users_list = []
    for user in config.users:
        users_list.append(
            {
                "name": user.name,
                "model": user.agent.model,
                "skills": {
                    "gog": user.skills.gog.enabled,
                    "gemini": user.skills.gemini,
                    "coding_agent": user.skills.coding_agent,
                    "github": user.skills.github,
                },
                "channels": {
                    "slack": user.channels.slack.enabled,
                    "discord": user.channels.discord.enabled,
                },
            }
        )

    return {"users": users_list}
