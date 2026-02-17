"""Tests for config loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from clawctl.core.config import load_config
from clawctl.models.config import Config, ClawctlSettings, UserConfig


class TestConfigModels:
    def test_valid_username(self):
        user = UserConfig(
            name="alice",
            secrets={"openrouter_api_key": "key"},
        )
        assert user.name == "alice"

    def test_username_with_hyphens(self):
        user = UserConfig(
            name="alice-dev",
            secrets={"openrouter_api_key": "key"},
        )
        assert user.name == "alice-dev"

    def test_invalid_username_uppercase(self):
        with pytest.raises(ValueError, match="lowercase"):
            UserConfig(
                name="Alice",
                secrets={"openrouter_api_key": "key"},
            )

    def test_invalid_username_spaces(self):
        with pytest.raises(ValueError, match="lowercase"):
            UserConfig(
                name="alice smith",
                secrets={"openrouter_api_key": "key"},
            )

    def test_invalid_username_too_long(self):
        with pytest.raises(ValueError, match="lowercase"):
            UserConfig(
                name="a" * 33,
                secrets={"openrouter_api_key": "key"},
            )

    def test_invalid_username_starts_with_hyphen(self):
        with pytest.raises(ValueError, match="lowercase"):
            UserConfig(
                name="-alice",
                secrets={"openrouter_api_key": "key"},
            )

    def test_config_get_user(self, sample_config: Config):
        user = sample_config.get_user("testuser")
        assert user is not None
        assert user.name == "testuser"

    def test_config_get_user_not_found(self, sample_config: Config):
        assert sample_config.get_user("nobody") is None

    def test_config_get_usernames(self, sample_config: Config):
        assert sample_config.get_usernames() == ["testuser"]


class TestConfigLoading:
    def test_load_valid_toml(self, tmp_path: Path, sample_config_toml: str):
        config_file = tmp_path / "clawctl.toml"
        config_file.write_text(sample_config_toml)
        cfg = load_config(config_file)
        assert cfg.clawctl.openclaw_version == "latest"
        assert len(cfg.users) == 1
        assert cfg.users[0].name == "testuser"
        assert cfg.users[0].channels.slack.enabled is True

    def test_load_missing_file(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "missing.toml")

    def test_load_invalid_toml(self, tmp_path: Path):
        config_file = tmp_path / "bad.toml"
        config_file.write_text("this is not [valid toml")
        with pytest.raises(ValueError, match="Invalid TOML"):
            load_config(config_file)

    def test_load_missing_required_field(self, tmp_path: Path):
        config_file = tmp_path / "incomplete.toml"
        config_file.write_text("[clawctl]\n# missing data_root\n")
        with pytest.raises(ValueError, match="validation failed"):
            load_config(config_file)

    def test_backup_interval_bounds(self):
        with pytest.raises(ValueError):
            ClawctlSettings(
                data_root="/tmp/test",
                backup={"interval_minutes": 3},  # below minimum of 5
            )

    def test_relative_data_root_resolved(self, tmp_path: Path):
        """data_root = 'build' resolves relative to the config file's directory."""
        config_file = tmp_path / "clawctl.toml"
        config_file.write_text("""\
[clawctl]
data_root = "build"
openclaw_version = "latest"

[[users]]
name = "testuser"

[users.secrets]
openrouter_api_key = "openrouter_api_key"
""")
        cfg = load_config(config_file)
        assert cfg.clawctl.data_root == tmp_path / "build"
        assert cfg.clawctl.data_root.is_absolute()

    def test_absolute_data_root_preserved(self, tmp_path: Path):
        """Absolute data_root stays as-is."""
        abs_path = tmp_path / "my-data"
        config_file = tmp_path / "clawctl.toml"
        config_file.write_text(f"""\
[clawctl]
data_root = "{abs_path}"
openclaw_version = "latest"

[[users]]
name = "testuser"

[users.secrets]
openrouter_api_key = "openrouter_api_key"
""")
        cfg = load_config(config_file)
        assert cfg.clawctl.data_root == abs_path
