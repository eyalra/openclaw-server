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

    def test_load_missing_clawctl_section(self, tmp_path: Path):
        config_file = tmp_path / "incomplete.toml"
        config_file.write_text("# no [clawctl] section at all\n")
        with pytest.raises(ValueError, match="validation failed"):
            load_config(config_file)

    def test_backup_interval_bounds(self):
        with pytest.raises(ValueError):
            ClawctlSettings(
                data_root="/tmp/test",
                backup={"interval_minutes": 3},  # below minimum of 5
            )

    def test_relative_roots_resolved(self, tmp_path: Path):
        """Relative data_root and build_root resolve relative to the config file's directory."""
        config_file = tmp_path / "clawctl.toml"
        config_file.write_text("""\
[clawctl]
data_root = "data"
build_root = "build"
openclaw_version = "latest"

[[users]]
name = "testuser"

[users.secrets]
openrouter_api_key = "openrouter_api_key"
""")
        cfg = load_config(config_file)
        assert cfg.clawctl.data_root == tmp_path / "data"
        assert cfg.clawctl.data_root.is_absolute()
        assert cfg.clawctl.build_root == tmp_path / "build"
        assert cfg.clawctl.build_root.is_absolute()

    def test_absolute_roots_preserved(self, tmp_path: Path):
        """Absolute data_root and build_root stay as-is."""
        abs_data = tmp_path / "my-data"
        abs_build = tmp_path / "my-build"
        config_file = tmp_path / "clawctl.toml"
        config_file.write_text(f"""\
[clawctl]
data_root = "{abs_data}"
build_root = "{abs_build}"
openclaw_version = "latest"

[[users]]
name = "testuser"

[users.secrets]
openrouter_api_key = "openrouter_api_key"
""")
        cfg = load_config(config_file)
        assert cfg.clawctl.data_root == abs_data
        assert cfg.clawctl.build_root == abs_build

    def test_relative_workspace_template_resolved(self, tmp_path: Path):
        """Relative workspace_template resolves relative to config file directory."""
        config_file = tmp_path / "clawctl.toml"
        config_file.write_text("""\
[clawctl]

[clawctl.defaults]
workspace_template = "templates/default"

[[users]]
name = "testuser"
workspace_template = "templates/custom"

[users.secrets]
openrouter_api_key = "openrouter_api_key"
""")
        cfg = load_config(config_file)
        assert cfg.clawctl.defaults.workspace_template == tmp_path / "templates" / "default"
        assert cfg.clawctl.defaults.workspace_template.is_absolute()
        assert cfg.users[0].workspace_template == tmp_path / "templates" / "custom"
        assert cfg.users[0].workspace_template.is_absolute()

    def test_no_workspace_template_is_none(self, tmp_path: Path):
        """When workspace_template is omitted, the field is None."""
        config_file = tmp_path / "clawctl.toml"
        config_file.write_text("""\
[clawctl]

[[users]]
name = "testuser"

[users.secrets]
openrouter_api_key = "openrouter_api_key"
""")
        cfg = load_config(config_file)
        assert cfg.clawctl.defaults.workspace_template is None
        assert cfg.users[0].workspace_template is None

    def test_default_skills_enabled(self, tmp_path: Path):
        """Default skills (gog, gemini, coding_agent) are enabled by default."""
        config_file = tmp_path / "clawctl.toml"
        config_file.write_text("""\
[clawctl]

[[users]]
name = "testuser"

[users.secrets]
openrouter_api_key = "openrouter_api_key"
""")
        cfg = load_config(config_file)
        assert cfg.clawctl.defaults.skills.gog.enabled is True
        assert cfg.clawctl.defaults.skills.gemini is True
        assert cfg.clawctl.defaults.skills.coding_agent is True
        # User inherits defaults
        assert cfg.users[0].skills.gog.enabled is True
        assert cfg.users[0].skills.gemini is True
        assert cfg.users[0].skills.coding_agent is True

    def test_user_skill_override(self, tmp_path: Path):
        """User can override default skill settings."""
        config_file = tmp_path / "clawctl.toml"
        config_file.write_text("""\
[clawctl]

[clawctl.defaults.skills]
gemini = true
coding_agent = true

[clawctl.defaults.skills.gog]
enabled = true

[[users]]
name = "testuser"

[users.skills]
gemini = false

[users.secrets]
openrouter_api_key = "openrouter_api_key"
""")
        cfg = load_config(config_file)
        assert cfg.users[0].skills.gog.enabled is True
        assert cfg.users[0].skills.gemini is False
        assert cfg.users[0].skills.coding_agent is True

    def test_skills_config_in_defaults(self, tmp_path: Path):
        """Skills can be configured globally in [clawctl.defaults.skills]."""
        config_file = tmp_path / "clawctl.toml"
        config_file.write_text("""\
[clawctl]

[clawctl.defaults.skills]
gemini = true
coding_agent = false

[clawctl.defaults.skills.gog]
enabled = false

[[users]]
name = "testuser"

[users.secrets]
openrouter_api_key = "openrouter_api_key"
""")
        cfg = load_config(config_file)
        assert cfg.clawctl.defaults.skills.gog.enabled is False
        assert cfg.clawctl.defaults.skills.gemini is True
        assert cfg.clawctl.defaults.skills.coding_agent is False

    def test_gog_email_loaded_from_toml(self, tmp_path: Path):
        """Gog email is parsed from the user's skills.gog config."""
        config_file = tmp_path / "clawctl.toml"
        config_file.write_text("""\
[clawctl]

[[users]]
name = "alice"

[users.skills.gog]
enabled = true
email = "alice@example.com"

[users.secrets]
openrouter_api_key = "openrouter_api_key"
""")
        cfg = load_config(config_file)
        assert cfg.users[0].skills.gog.email == "alice@example.com"

    def test_gog_email_defaults_to_none(self, tmp_path: Path):
        """Gog email is None when not specified."""
        config_file = tmp_path / "clawctl.toml"
        config_file.write_text("""\
[clawctl]

[[users]]
name = "alice"

[users.secrets]
openrouter_api_key = "openrouter_api_key"
""")
        cfg = load_config(config_file)
        assert cfg.users[0].skills.gog.email is None
