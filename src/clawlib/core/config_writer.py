"""Config writing utilities for updating TOML configuration files."""

from __future__ import annotations

from pathlib import Path

try:
    import tomli_w
except ImportError:
    tomli_w = None


def update_web_config_price_limits(
    config_path: Path,
    max_prompt_price: float | None = None,
    max_completion_price: float | None = None,
    max_request_price: float | None = None,
) -> None:
    """Update model price limits in the web config section.
    
    Args:
        config_path: Path to the clawctl.toml file.
        max_prompt_price: Maximum prompt price per million tokens (USD), or None to clear.
        max_completion_price: Maximum completion price per million tokens (USD), or None to clear.
        max_request_price: Maximum request price (USD), or None to clear.
        
    Raises:
        ImportError: If tomli_w is not available.
        FileNotFoundError: If config file doesn't exist.
        ValueError: If TOML is invalid.
    """
    if tomli_w is None:
        raise ImportError("tomli_w is required for writing config files")
    
    if not config_path.is_file():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    # Read existing config
    import tomllib
    text = config_path.read_text()
    try:
        data = tomllib.loads(text)
    except Exception as e:
        raise ValueError(f"Invalid TOML: {e}") from e
    
    # Ensure web section exists
    if "web" not in data:
        data["web"] = {}
    
    # Update or create model_price_limits section
    if "model_price_limits" not in data["web"]:
        data["web"]["model_price_limits"] = {}
    
    price_limits = data["web"]["model_price_limits"]
    
    # Update values (None means remove the key)
    if max_prompt_price is not None:
        price_limits["max_prompt_price_per_million"] = max_prompt_price
    elif "max_prompt_price_per_million" in price_limits:
        del price_limits["max_prompt_price_per_million"]
    
    if max_completion_price is not None:
        price_limits["max_completion_price_per_million"] = max_completion_price
    elif "max_completion_price_per_million" in price_limits:
        del price_limits["max_completion_price_per_million"]
    
    if max_request_price is not None:
        price_limits["max_request_price"] = max_request_price
    elif "max_request_price" in price_limits:
        del price_limits["max_request_price"]
    
    # Remove empty model_price_limits section
    if not price_limits:
        del data["web"]["model_price_limits"]
    
    # Write back to file
    # Note: tomli_w doesn't preserve comments, but it's the best we have
    config_path.write_text(tomli_w.dumps(data))


def update_user_model(
    config_path: Path,
    username: str,
    model: str,
) -> None:
    """Update a user's model in the configuration file.
    
    Args:
        config_path: Path to the clawctl.toml file.
        username: Username to update.
        model: New model identifier (e.g., "openrouter/z-ai/glm-4.5-air:free").
        
    Raises:
        ImportError: If tomli_w is not available.
        FileNotFoundError: If config file doesn't exist.
        ValueError: If TOML is invalid or user not found.
    """
    if tomli_w is None:
        raise ImportError("tomli_w is required for writing config files")
    
    if not config_path.is_file():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    # Read existing config
    import tomllib
    text = config_path.read_text()
    try:
        data = tomllib.loads(text)
    except Exception as e:
        raise ValueError(f"Invalid TOML: {e}") from e
    
    # Find the user in the users list
    users = data.get("users", [])
    user_found = False
    
    for user in users:
        if user.get("name") == username:
            # Update the model in the agent section
            if "agent" not in user:
                user["agent"] = {}
            user["agent"]["model"] = model
            user_found = True
            break
    
    if not user_found:
        raise ValueError(f"User '{username}' not found in configuration")
    
    # Write back to file
    # Note: tomli_w doesn't preserve comments, but it's the best we have
    config_path.write_text(tomli_w.dumps(data))
