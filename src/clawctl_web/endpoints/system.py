"""System information endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel

from clawctl_web.auth import get_current_user
from clawlib.core.config import find_config_path, load_config
from clawlib.core.docker_manager import DockerManager

router = APIRouter()


@router.get("/config")
async def get_config(
    _user: str = Depends(get_current_user),
    config_path: Path | None = None,
):
    """Get system configuration (sanitized - no secrets)."""
    config_path_resolved = find_config_path(config_path)
    if not config_path_resolved:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configuration file not found",
        )
    config = load_config(config_path_resolved)

    # Return sanitized config (no secrets)
    from clawlib.models.config import WebConfig
    
    web_config = getattr(config, 'web', None) or WebConfig()
    
    web_data = {
        "enabled": web_config.enabled,
        "port": web_config.port,
        "host": web_config.host,
    }
    
    # Add price limits if configured
    if web_config.model_price_limits:
        web_data["model_price_limits"] = {
            "max_prompt_price_per_million": web_config.model_price_limits.max_prompt_price_per_million,
            "max_completion_price_per_million": web_config.model_price_limits.max_completion_price_per_million,
            "max_request_price": web_config.model_price_limits.max_request_price,
        }
    else:
        web_data["model_price_limits"] = None
    
    return {
        "clawctl": {
            "data_root": str(config.clawctl.data_root),
            "build_root": str(config.clawctl.build_root),
            "openclaw_version": config.clawctl.openclaw_version,
            "image_name": config.clawctl.image_name,
            "log_level": config.clawctl.log_level,
            "knowledge_dir": str(config.clawctl.knowledge_dir) if config.clawctl.knowledge_dir else None,
        },
        "web": web_data,
        "user_count": len(config.users),
    }


@router.post("/update")
async def trigger_update(
    _user: str = Depends(get_current_user),
):
    """Trigger OpenClaw version update (rebuilds image and restarts containers)."""
    config_path_resolved = find_config_path()
    if not config_path_resolved:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configuration file not found",
        )
    config = load_config(config_path_resolved)
    docker_mgr = DockerManager(config)

    try:
        updated = docker_mgr.rebuild_all()
        return {
            "message": f"Updated {len(updated)} containers",
            "updated": updated,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update: {str(e)}",
        )


class PriceLimitsRequest(BaseModel):
    max_prompt_price_per_million: float | None = None
    max_completion_price_per_million: float | None = None
    max_request_price: float | None = None


@router.put("/price-limits")
async def update_price_limits(
    limits: PriceLimitsRequest,
    _user: str = Depends(get_current_user),
):
    """Update model price limits in configuration."""
    config_path_resolved = find_config_path()
    if not config_path_resolved:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configuration file not found",
        )
    
    try:
        from clawlib.core.config_writer import update_web_config_price_limits
        
        update_web_config_price_limits(
            config_path_resolved,
            max_prompt_price=limits.max_prompt_price_per_million,
            max_completion_price=limits.max_completion_price_per_million,
            max_request_price=limits.max_request_price,
        )
        
        # Clear models cache to force refresh with new filters
        from clawctl_web.endpoints.models import _openrouter_cache
        _openrouter_cache.clear()  # Clear the entire cache dict to force fresh fetch
        
        return {
            "message": "Price limits updated successfully",
            "limits": {
                "max_prompt_price_per_million": limits.max_prompt_price_per_million,
                "max_completion_price_per_million": limits.max_completion_price_per_million,
                "max_request_price": limits.max_request_price,
            },
        }
    except ImportError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Config writing not available: {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update price limits: {str(e)}",
        )
