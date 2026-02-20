"""User management endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from clawctl_web.auth import get_current_user
from clawlib.core.config import find_config_path, load_config
from clawlib.core.docker_manager import DockerManager
from clawlib.core.secrets import SecretsManager
from clawlib.core.openclaw_config import write_openclaw_config, generate_openclaw_config
import json
from clawlib.core.user_manager import GATEWAY_TOKEN_SECRET_NAME, Paths

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


class ModelUpdateRequest(BaseModel):
    model: str
    provider: str | None = None  # Optional: "openrouter" or "anthropic" to help determine routing


@router.patch("/{username}/model")
async def update_user_model(
    username: str,
    request: ModelUpdateRequest,
    _user: str = Depends(get_current_user),
    config_path: Path | None = None,
):
    """Update a user's model and restart their container."""
    config_path_resolved = find_config_path(config_path)
    if not config_path_resolved:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configuration file not found",
        )
    
    config = load_config(config_path_resolved)
    user = config.get_user(username)
    
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{username}' not found",
        )
    
    # Initialize secrets manager for validation
    paths = Paths(config.clawctl.data_root, config.clawctl.build_root)
    secrets_mgr = SecretsManager(paths)
    
    # Check if model requires OpenRouter and verify API key is configured
    model_requires_openrouter = (
        request.model.startswith("openrouter/") or 
        request.model.startswith("openai/") or
        request.model.startswith("google/") or
        request.model.startswith("anthropic/") or
        request.model.startswith("meta/") or
        "/" in request.model  # Most OpenRouter models have provider/model format
    )
    
    if model_requires_openrouter:
        # Verify OpenRouter API key is configured
        openrouter_key = secrets_mgr.read_secret(username, "openrouter_api_key")
        if not openrouter_key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Model '{request.model}' requires OpenRouter API key. Please configure the 'openrouter_api_key' secret for user '{username}'.",
            )
    
    # Validate model exists in OpenRouter (if it's an OpenRouter model)
    if model_requires_openrouter:
        try:
            from clawctl_web.endpoints.models import _get_cached_models
            cached_models = _get_cached_models()
            
            if cached_models:
                model_exists = any(m.get("id") == request.model for m in cached_models)
                if not model_exists:
                    # Try to find similar models
                    model_lower = request.model.lower()
                    similar = [
                        m.get("id")
                        for m in cached_models
                        if model_lower.split("/")[-1] in m.get("id", "").lower()
                        or any(part in m.get("id", "").lower() for part in model_lower.split("/")[-1].split("-") if len(part) > 3)
                    ][:5]
                    
                    error_msg = f"Model '{request.model}' not found in OpenRouter."
                    if similar:
                        error_msg += f" Did you mean: {', '.join(similar[:3])}?"
                    else:
                        error_msg += " Please check the model name or refresh the model list."
                    
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=error_msg,
                    )
        except HTTPException:
            raise
        except Exception:
            # If validation fails, continue anyway (model might be valid but cache unavailable)
            pass
    
    try:
        # Update model in config file
        from clawlib.core.config_writer import update_user_model
        update_user_model(config_path_resolved, username, request.model)
        
        # Reload config to get updated user
        config = load_config(config_path_resolved)
        user = config.get_user(username)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to reload updated configuration",
            )
        
        # Regenerate openclaw.json with new model
        # (paths and secrets_mgr already initialized above)
        gateway_token = secrets_mgr.read_secret(username, GATEWAY_TOKEN_SECRET_NAME)
        if not gateway_token:
            import secrets as secrets_module
            gateway_token = secrets_module.token_urlsafe(32)
            secrets_mgr.write_secret(username, GATEWAY_TOKEN_SECRET_NAME, gateway_token)
        
        # Determine provider if not explicitly provided
        # Infer from model name or use provided provider
        provider = request.provider
        if not provider:
            if request.model.startswith("anthropic/"):
                provider = "anthropic"
            elif request.model.startswith("openrouter/"):
                provider = "openrouter"
            else:
                # Default to openrouter for models with provider/model format
                provider = "openrouter" if "/" in request.model else None
        
        # Generate config content
        # Pass provider info to ensure correct routing
        config_content = generate_openclaw_config(
            user,
            config.clawctl.defaults,
            gateway_token=gateway_token,
            provider=provider,
        )
        config_json = json.dumps(config_content, indent=2)
        
        # Write config file via container to avoid permission issues
        # The container runs as UID 1000 and can write to the mounted volume
        docker_mgr = DockerManager(config)
        container_name = f"openclaw-{username}"
        
        config_file_path_in_container = "/home/node/.openclaw/openclaw.json"
        
        # Check if container exists
        if not docker_mgr.container_exists(username):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Container for user '{username}' not found. Please create the user first.",
            )
        
        container = docker_mgr.client.containers.get(container_name)
        
        # Write config file inside container using base64 to avoid shell escaping issues
        import base64
        config_b64 = base64.b64encode(config_json.encode()).decode()
        
        # Use base64 command (usually available) to decode and write the file
        # Split into chunks to avoid command line length limits
        cmd = f"""bash -c 'echo "{config_b64}" | base64 -d > "{config_file_path_in_container}"'"""
        
        exec_result = container.exec_run(
            cmd,
            user="1000",
            workdir="/home/node",
        )
        
        if exec_result.exit_code != 0:
            error_output = exec_result.output.decode() if hasattr(exec_result, 'output') else str(exec_result)
            # Fallback: try using node to write the file (container is Node.js based)
            node_cmd = f"""node -e "const fs = require('fs'); const data = Buffer.from('{config_b64}', 'base64').toString(); fs.writeFileSync('{config_file_path_in_container}', data);" """
            exec_result2 = container.exec_run(
                node_cmd,
                user="1000",
                workdir="/home/node",
            )
            
            if exec_result2.exit_code != 0:
                error_output2 = exec_result2.output.decode() if hasattr(exec_result2, 'output') else str(exec_result2)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to write config file via container. Base64: {error_output[:200]}. Node: {error_output2[:200]}",
                )
        
        # Restart container to apply changes
        docker_mgr = DockerManager(config)
        if docker_mgr.container_exists(username):
            docker_mgr.restart_container(username)
            
            # Configure agent auth to ensure correct provider is used
            _configure_agent_auth(docker_mgr, username, request.model, secrets_mgr)
        
        return {
            "message": f"Model updated to {request.model} for {username}",
            "model": request.model,
        }
    except ImportError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Config writing not available: {str(e)}",
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update model: {str(e)}",
        )
