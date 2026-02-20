"""Model management endpoints for fetching available models from providers."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from clawctl_web.auth import get_current_user
from clawlib.core.config import find_config_path, load_config

router = APIRouter()

# In-memory cache for OpenRouter models
# Format: {"data": [...], "timestamp": float, "ttl": int}
_openrouter_cache: dict[str, Any] = {}
CACHE_TTL_SECONDS = 3600  # 1 hour

# Static model options that should always be included
STATIC_MODEL_OPTIONS = {
    "openrouter": [
        "openrouter/z-ai/glm-4.5-air:free",
        "google/gemini-2.5-flash-lite",
        "openai/gpt-5-nano",
        "openai/gpt-4o-mini",
    ],
    "anthropic": [
        "anthropic/claude-sonnet-4-20250514",
        "anthropic/claude-opus-4-20250514",
    ],
}


async def _fetch_openrouter_models(api_key: str | None = None) -> list[dict[str, Any]]:
    """Fetch models from OpenRouter API.
    
    Note: OpenRouter's public models endpoint doesn't require authentication.
    The api_key parameter is kept for potential future use but is not currently needed.
    
    Args:
        api_key: Optional OpenRouter API key (not currently used, kept for future compatibility).
        
    Returns:
        List of model dictionaries with id, name, pricing, etc.
    """
    import httpx
    
    headers = {
        "Content-Type": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    
    url = "https://openrouter.ai/api/v1/models"
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            # OpenRouter returns {"data": [...]}
            if isinstance(data, dict) and "data" in data:
                return data["data"]
            elif isinstance(data, list):
                return data
            else:
                return []
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to fetch models from OpenRouter: {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error fetching models: {str(e)}",
        )


def _get_cached_models() -> list[dict[str, Any]] | None:
    """Get cached OpenRouter models if still valid."""
    if not _openrouter_cache:
        return None
    
    cache_age = time.time() - _openrouter_cache.get("timestamp", 0)
    if cache_age < _openrouter_cache.get("ttl", CACHE_TTL_SECONDS):
        return _openrouter_cache.get("data")
    
    return None


def _set_cached_models(models: list[dict[str, Any]]) -> None:
    """Cache OpenRouter models (with converted pricing)."""
    _openrouter_cache["data"] = models
    _openrouter_cache["timestamp"] = time.time()
    _openrouter_cache["ttl"] = CACHE_TTL_SECONDS


def _convert_pricing_to_per_million(pricing: dict[str, Any]) -> dict[str, Any]:
    """Convert per-token prices to per-million-token prices.
    
    OpenRouter API always returns prices per token (e.g., 0.0000001),
    so we always multiply by 1,000,000 to get per million tokens (e.g., 0.1).
    
    Returns prices rounded to appropriate precision for display.
    """
    converted = {}
    
    if pricing.get("prompt"):
        try:
            price_per_token = float(pricing["prompt"])
            price_per_million = price_per_token * 1_000_000
            
            # Format to appropriate precision with fixed decimal places
            if price_per_million >= 0.01:
                converted["prompt"] = f"{price_per_million:.2f}"
            elif price_per_million >= 0.001:
                converted["prompt"] = f"{price_per_million:.3f}"
            elif price_per_million >= 0.0001:
                converted["prompt"] = f"{price_per_million:.4f}"
            else:
                converted["prompt"] = f"{price_per_million:.6f}"
        except (ValueError, TypeError):
            converted["prompt"] = pricing.get("prompt")
    
    if pricing.get("completion"):
        try:
            price_per_token = float(pricing["completion"])
            price_per_million = price_per_token * 1_000_000
            
            # Format to appropriate precision with fixed decimal places
            if price_per_million >= 0.01:
                converted["completion"] = f"{price_per_million:.2f}"
            elif price_per_million >= 0.001:
                converted["completion"] = f"{price_per_million:.3f}"
            elif price_per_million >= 0.0001:
                converted["completion"] = f"{price_per_million:.4f}"
            else:
                converted["completion"] = f"{price_per_million:.6f}"
        except (ValueError, TypeError):
            converted["completion"] = pricing.get("completion")
    
    if pricing.get("request"):
        # Request prices are already per-request, not per-token
        converted["request"] = pricing.get("request")
    
    return converted


def _filter_models_by_price(
    models: list[dict[str, Any]],
    price_limits: Any | None,
) -> list[dict[str, Any]]:
    """Filter models based on price limits from config.
    
    Args:
        models: List of model dictionaries with pricing info.
               Prices should already be converted to per-million-token format.
        price_limits: ModelPriceLimits object from config, or None.
        
    Returns:
        Filtered list of models.
    """
    if not price_limits:
        return models
    
    filtered = []
    for model in models:
        pricing = model.get("pricing", {})
        
        # Check prompt price limit (prices are already per-million-token)
        if price_limits.max_prompt_price_per_million is not None:
            prompt_price = pricing.get("prompt")
            if prompt_price is not None:
                try:
                    prompt_price_float = float(prompt_price)
                    if prompt_price_float > price_limits.max_prompt_price_per_million:
                        continue
                except (ValueError, TypeError):
                    pass  # Skip filtering if price is invalid
        
        # Check completion price limit (prices are already per-million-token)
        if price_limits.max_completion_price_per_million is not None:
            completion_price = pricing.get("completion")
            if completion_price is not None:
                try:
                    completion_price_float = float(completion_price)
                    if completion_price_float > price_limits.max_completion_price_per_million:
                        continue
                except (ValueError, TypeError):
                    pass  # Skip filtering if price is invalid
        
        # Check request price limit
        if price_limits.max_request_price is not None:
            request_price = pricing.get("request")
            if request_price is not None:
                try:
                    request_price_float = float(request_price)
                    if request_price_float > price_limits.max_request_price:
                        continue
                except (ValueError, TypeError):
                    pass  # Skip filtering if price is invalid
        
        filtered.append(model)
    
    return filtered


@router.get("/openrouter")
async def get_openrouter_models(
    _user: str = Depends(get_current_user),
    refresh: bool = Query(False, description="Force refresh from API, bypassing cache"),
):
    """Get available models from OpenRouter.
    
    Returns a list of models with their IDs, names, pricing, and metadata.
    Results are cached for 1 hour by default. Use refresh=true to bypass cache.
    
    Note: OpenRouter's public models endpoint doesn't require authentication.
    API keys are only needed when actually using models (handled by OpenClaw containers).
    
    Args:
        refresh: If True, bypass cache and fetch fresh data from API.
    """
    # Get price limits from config for filtering
    price_limits = None
    try:
        config_path_resolved = find_config_path()
        if config_path_resolved:
            config = load_config(config_path_resolved)
            web_config = getattr(config, 'web', None)
            if web_config and web_config.model_price_limits:
                price_limits = web_config.model_price_limits
    except Exception:
        pass
    
    # Check cache first unless refresh is requested
    if not refresh:
        cached = _get_cached_models()
        if cached is not None:
            # Cached models already have converted pricing - DO NOT convert again!
            # Apply price filtering to cached models if needed
            if price_limits:
                cached = _filter_models_by_price(cached, price_limits)
            return {
                "models": cached,
                "cached": True,
                "source": "cache",
            }
    
    # Fetch from API (no API key needed for public models endpoint)
    try:
        models = await _fetch_openrouter_models(None)
        
        # Transform to a more usable format
        # OpenRouter API returns prices per token, but we want per million tokens
        formatted_models = []
        for model in models:
            pricing = model.get("pricing", {})
            # Convert per-token prices to per-million-token prices
            converted_pricing = _convert_pricing_to_per_million(pricing)
            
            formatted_model = {
                "id": model.get("id", ""),
                "name": model.get("name", model.get("id", "")),
                "pricing": converted_pricing,
                "context_length": model.get("context_length"),
                "architecture": model.get("architecture", {}),
                "top_provider": model.get("top_provider", {}),
                "per_request_limits": model.get("per_request_limits", {}),
            }
            formatted_models.append(formatted_model)
        
        # Apply price filtering from config
        try:
            config_path_resolved = find_config_path()
            if config_path_resolved:
                config = load_config(config_path_resolved)
                web_config = getattr(config, 'web', None)
                if web_config and web_config.model_price_limits:
                    formatted_models = _filter_models_by_price(
                        formatted_models,
                        web_config.model_price_limits,
                    )
        except Exception:
            # If config loading fails, continue without filtering
            pass
        
        # Cache the results
        _set_cached_models(formatted_models)
        
        return {
            "models": formatted_models,
            "cached": False,
            "source": "api",
        }
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        # If API fails but we have cached data, return that
        cached = _get_cached_models()
        if cached is not None:
            return {
                "models": cached,
                "cached": True,
                "source": "cache_fallback",
                "warning": f"API fetch failed, returning cached data: {str(e)}",
            }
        
        # No cache available, raise error
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to fetch models and no cache available: {str(e)}",
        )


@router.get("/list")
async def get_models_list(
    provider: str = Query("openrouter", description="Provider: openrouter or anthropic"),
    _user: str = Depends(get_current_user),
    refresh: bool = Query(False, description="Force refresh from API"),
):
    """Get a complete, ready-to-display list of models for a provider.
    
    This endpoint handles all business logic:
    - Fetches models from OpenRouter (if provider is openrouter)
    - Merges with static model options
    - Applies price filtering from config
    - Returns a complete list ready for display
    
    Args:
        provider: Provider name (openrouter or anthropic)
        refresh: If True, bypass cache and fetch fresh data
        
    Returns:
        List of models with id, name, pricing, and display text ready for UI
    """
    static_models = STATIC_MODEL_OPTIONS.get(provider, [])
    
    # For OpenRouter, fetch from API and merge with static
    if provider == "openrouter":
        try:
            # Get OpenRouter models (this handles caching and price filtering)
            openrouter_response = await get_openrouter_models(
                _user=_user,
                refresh=refresh,
            )
            fetched_models = openrouter_response.get("models", [])
            
            # Create a map of fetched models by ID for quick lookup
            fetched_map = {m["id"]: m for m in fetched_models}
            
            # Build final list: start with static models (with pricing if available)
            final_models = []
            static_ids = set()
            
            for static_id in static_models:
                static_ids.add(static_id)
                fetched = fetched_map.get(static_id)
                if fetched:
                    # Use fetched model with pricing
                    final_models.append(fetched)
                else:
                    # Static model not in fetched list, add it anyway
                    final_models.append({
                        "id": static_id,
                        "name": static_id,
                        "pricing": None,
                    })
            
            # Add remaining fetched models that aren't in static list
            for model in fetched_models:
                if model["id"] not in static_ids:
                    final_models.append(model)
            
            # Sort alphabetically by name
            final_models.sort(key=lambda m: m.get("name", m.get("id", "")).lower())
            
            return {
                "provider": provider,
                "models": final_models,
                "total": len(final_models),
                "static_count": len(static_models),
                "fetched_count": len(fetched_models),
            }
        except Exception as e:
            # If API fails, return static models only
            return {
                "provider": provider,
                "models": [
                    {"id": m, "name": m, "pricing": None}
                    for m in static_models
                ],
                "total": len(static_models),
                "static_count": len(static_models),
                "fetched_count": 0,
                "warning": f"Failed to fetch from API: {str(e)}",
            }
    else:
        # For non-OpenRouter providers, return static models only
        return {
            "provider": provider,
            "models": [
                {"id": m, "name": m, "pricing": None}
                for m in static_models
            ],
            "total": len(static_models),
            "static_count": len(static_models),
            "fetched_count": 0,
        }
