"""Tests for secrets, paths, openclaw config, and user manager."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from clawctl.core.openclaw_config import generate_openclaw_config
from clawctl.core.paths import Paths
from clawctl.core.secrets import SecretsManager
from clawctl.core.user_manager import _resolve_template_dir, copy_template
from clawctl.models.config import Config, DefaultsConfig, UserConfig, UserSecretsConfig


class TestPaths:
    def test_directory_structure(self, tmp_data_root: Path, tmp_build_root: Path):
        paths = Paths(tmp_data_root, tmp_build_root)
        assert paths.data_root == tmp_data_root
        assert paths.build_root == tmp_build_root
        assert paths.logs_dir == tmp_build_root / "logs"
        assert paths.backup_pid_file == tmp_build_root / ".backup.pid"
        assert paths.secrets_root == tmp_data_root / "secrets"
        assert paths.users_root == tmp_data_root / "users"

    def test_user_paths(self, tmp_data_root: Path, tmp_build_root: Path):
        paths = Paths(tmp_data_root, tmp_build_root)
        assert paths.user_openclaw_dir("alice") == tmp_data_root / "users" / "alice" / "openclaw"
        assert paths.user_backup_dir("alice") == tmp_data_root / "users" / "alice" / "backup"
        assert paths.user_config_dir("alice") == tmp_data_root / "users" / "alice" / "config"
        assert paths.user_secrets_dir("alice") == tmp_data_root / "secrets" / "alice"

    def test_build_root_defaults_to_data_root(self, tmp_data_root: Path):
        paths = Paths(tmp_data_root)
        assert paths.build_root == tmp_data_root
        assert paths.logs_dir == tmp_data_root / "logs"

    def test_ensure_base_dirs(self, tmp_data_root: Path, tmp_build_root: Path):
        paths = Paths(tmp_data_root, tmp_build_root)
        paths.ensure_base_dirs()
        assert paths.logs_dir.is_dir()
        assert paths.secrets_root.is_dir()
        assert paths.users_root.is_dir()
        assert tmp_build_root.is_dir()

    def test_ensure_user_dirs(self, tmp_data_root: Path, tmp_build_root: Path):
        paths = Paths(tmp_data_root, tmp_build_root)
        paths.ensure_user_dirs("alice")
        assert paths.user_openclaw_dir("alice").is_dir()
        assert paths.user_workspace_dir("alice").is_dir()
        assert paths.user_backup_dir("alice").is_dir()
        assert paths.user_config_dir("alice").is_dir()
        assert paths.user_secrets_dir("alice").is_dir()


class TestSecretsManager:
    def test_write_and_read_secret(self, tmp_data_root: Path, tmp_build_root: Path):
        paths = Paths(tmp_data_root, tmp_build_root)
        mgr = SecretsManager(paths)
        mgr.write_secret("alice", "api_key", "sk-test-12345")
        assert mgr.read_secret("alice", "api_key") == "sk-test-12345"

    def test_secret_file_permissions(self, tmp_data_root: Path):
        paths = Paths(tmp_data_root)
        mgr = SecretsManager(paths)
        path = mgr.write_secret("alice", "api_key", "secret")
        mode = os.stat(path).st_mode
        # Should be 0600 (owner read/write only)
        assert mode & 0o777 == stat.S_IRUSR | stat.S_IWUSR

    def test_secret_exists(self, tmp_data_root: Path):
        paths = Paths(tmp_data_root)
        mgr = SecretsManager(paths)
        assert mgr.secret_exists("alice", "api_key") is False
        mgr.write_secret("alice", "api_key", "value")
        assert mgr.secret_exists("alice", "api_key") is True

    def test_list_secrets(self, tmp_data_root: Path):
        paths = Paths(tmp_data_root)
        mgr = SecretsManager(paths)
        mgr.write_secret("alice", "api_key", "v1")
        mgr.write_secret("alice", "slack_token", "v2")
        assert mgr.list_secrets("alice") == ["api_key", "slack_token"]

    def test_remove_user_secrets(self, tmp_data_root: Path):
        paths = Paths(tmp_data_root)
        mgr = SecretsManager(paths)
        mgr.write_secret("alice", "api_key", "value")
        mgr.remove_user_secrets("alice")
        assert mgr.list_secrets("alice") == []

    def test_get_required_secrets(self, sample_user: UserConfig, tmp_data_root: Path):
        paths = Paths(tmp_data_root)
        mgr = SecretsManager(paths)
        required = mgr.get_required_secrets(sample_user)
        names = [name for name, _ in required]
        assert "openrouter_api_key" in names
        assert "slack_bot_token" in names
        assert "slack_app_token" in names
        assert "discord_token" in names

    def test_get_required_secrets_with_skills(self, sample_user: UserConfig, tmp_data_root: Path):
        """Skills-enabled users require skill API keys."""
        paths = Paths(tmp_data_root)
        mgr = SecretsManager(paths)
        defaults = DefaultsConfig()
        required = mgr.get_required_secrets(sample_user, defaults)
        names = [name for name, _ in required]
        # gog requires OAuth client credentials and a keyring password
        assert "gog_client_id" in names
        assert "gog_client_secret" in names
        assert "gog_keyring_password" in names
        # the old name is gone
        assert "gog_api_key" not in names
        # gemini uses OAuth login — no API key required at provision time
        assert "gemini_api_key" not in names
        # github uses gh auth login — no secret required at provision time
        assert "github_token" not in names
        # coding_agent doesn't require an API key
        assert "openrouter_api_key" in names

    def test_skill_override_disables_secret(self, tmp_data_root: Path):
        """When a skill is disabled, its API key is not required."""
        from clawctl.models.config import GogSkillConfig, SkillsConfig

        user = UserConfig(
            name="alice",
            skills=SkillsConfig(gog=GogSkillConfig(enabled=False), gemini=True, coding_agent=True),
            secrets=UserSecretsConfig(openrouter_api_key="openrouter_api_key"),
        )
        defaults = DefaultsConfig()
        paths = Paths(tmp_data_root)
        mgr = SecretsManager(paths)
        required = mgr.get_required_secrets(user, defaults)
        names = [name for name, _ in required]
        # gog is disabled — its secrets should be absent
        assert "gog_api_key" not in names
        # gemini uses OAuth (no API key required at provision time regardless of enabled state)
        assert "gemini_api_key" not in names

    def test_skill_secret_deduplication(self, tmp_data_root: Path):
        """Duplicate secrets are not listed twice."""
        from clawctl.models.config import GogSkillConfig, SkillsConfig

        user = UserConfig(
            name="alice",
            skills=SkillsConfig(gog=GogSkillConfig(enabled=True), gemini=True, coding_agent=True),
            secrets=UserSecretsConfig(
                openrouter_api_key="openrouter_api_key",
                gog_api_key="gog_api_key",  # Explicitly declared too
            ),
        )
        defaults = DefaultsConfig()
        paths = Paths(tmp_data_root)
        mgr = SecretsManager(paths)
        required = mgr.get_required_secrets(user, defaults)
        names = [name for name, _ in required]
        # gog_api_key appears only once despite both skill and explicit secret
        assert names.count("gog_api_key") == 1


class TestWorkspaceTemplate:
    def test_copy_template_basic(self, tmp_path: Path):
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "IDENTITY.md").write_text("# Identity\nYou are a helpful agent.")
        (template_dir / "workspace").mkdir()
        (template_dir / "workspace" / "accounts.md").write_text("# Accounts")

        dest_dir = tmp_path / "openclaw"
        dest_dir.mkdir()

        copied = copy_template(template_dir, dest_dir)

        assert (dest_dir / "IDENTITY.md").read_text() == "# Identity\nYou are a helpful agent."
        assert (dest_dir / "workspace" / "accounts.md").read_text() == "# Accounts"
        assert Path("IDENTITY.md") in copied
        assert Path("workspace/accounts.md") in copied

    def test_copy_template_skips_existing(self, tmp_path: Path):
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "IDENTITY.md").write_text("template version")

        dest_dir = tmp_path / "openclaw"
        dest_dir.mkdir()
        (dest_dir / "IDENTITY.md").write_text("user version")

        copied = copy_template(template_dir, dest_dir)

        assert (dest_dir / "IDENTITY.md").read_text() == "user version"
        assert copied == []

    def test_copy_template_mixed(self, tmp_path: Path):
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "existing.md").write_text("template")
        (template_dir / "new.md").write_text("new content")

        dest_dir = tmp_path / "openclaw"
        dest_dir.mkdir()
        (dest_dir / "existing.md").write_text("user content")

        copied = copy_template(template_dir, dest_dir)

        assert (dest_dir / "existing.md").read_text() == "user content"
        assert (dest_dir / "new.md").read_text() == "new content"
        assert Path("new.md") in copied
        assert Path("existing.md") not in copied

    def test_copy_template_nonexistent_dir(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            copy_template(tmp_path / "nonexistent", tmp_path / "dest")

    def test_copy_template_not_a_directory(self, tmp_path: Path):
        template_file = tmp_path / "not-a-dir"
        template_file.write_text("oops")
        with pytest.raises(NotADirectoryError):
            copy_template(template_file, tmp_path / "dest")

    def test_no_template_noop(self):
        user = UserConfig(name="alice", secrets={"openrouter_api_key": "key"})
        defaults = DefaultsConfig()
        assert _resolve_template_dir(user, defaults) is None

    def test_global_template_used(self, tmp_path: Path):
        user = UserConfig(name="alice", secrets={"openrouter_api_key": "key"})
        defaults = DefaultsConfig(workspace_template=tmp_path / "templates" / "default")
        result = _resolve_template_dir(user, defaults)
        assert result == tmp_path / "templates" / "default"

    def test_per_user_overrides_global(self, tmp_path: Path):
        user = UserConfig(
            name="alice",
            secrets={"openrouter_api_key": "key"},
            workspace_template=tmp_path / "templates" / "alice",
        )
        defaults = DefaultsConfig(workspace_template=tmp_path / "templates" / "default")
        result = _resolve_template_dir(user, defaults)
        assert result == tmp_path / "templates" / "alice"


class TestOpenClawConfig:
    def test_generate_basic_config(self, sample_user: UserConfig):
        config = generate_openclaw_config(sample_user, DefaultsConfig())
        assert config["gateway"]["port"] == 18789
        assert config["gateway"]["bind"] == "lan"
        assert config["agents"]["defaults"]["model"]["primary"] == "openrouter/z-ai/glm-4.5-air:free"

    def test_slack_channel_included(self, sample_user: UserConfig):
        config = generate_openclaw_config(sample_user, DefaultsConfig())
        assert "slack" in config["channels"]
        assert config["channels"]["slack"]["enabled"] is True

    def test_discord_channel_included(self, sample_user: UserConfig):
        config = generate_openclaw_config(sample_user, DefaultsConfig())
        assert "discord" in config["channels"]
        assert config["channels"]["discord"]["enabled"] is True

    def test_disabled_channels_excluded(self):
        user = UserConfig(
            name="bob",
            secrets={"openrouter_api_key": "key"},
        )
        config = generate_openclaw_config(user, DefaultsConfig())
        assert "slack" not in config["channels"]
        assert "discord" not in config["channels"]

    def test_gog_email_written_to_openclaw_json(self):
        """When gog is enabled with an email, it appears as hooks.gmail.account in openclaw.json."""
        from clawctl.models.config import GogSkillConfig, SkillsConfig

        user = UserConfig(
            name="alice",
            skills=SkillsConfig(gog=GogSkillConfig(enabled=True, email="alice@example.com")),
            secrets={"openrouter_api_key": "key"},
        )
        config = generate_openclaw_config(user, DefaultsConfig())
        assert "hooks" in config
        assert config["hooks"]["gmail"]["account"] == "alice@example.com"

    def test_gog_email_none_omits_gmail_hook(self):
        """When gog email is not set, hooks.gmail is absent from openclaw.json."""
        from clawctl.models.config import GogSkillConfig, SkillsConfig

        user = UserConfig(
            name="alice",
            skills=SkillsConfig(gog=GogSkillConfig(enabled=True, email=None)),
            secrets={"openrouter_api_key": "key"},
        )
        config = generate_openclaw_config(user, DefaultsConfig())
        assert "gmail" not in config.get("hooks", {})

    def test_gog_disabled_omits_gmail_hook(self):
        """When gog is disabled, hooks.gmail is absent from openclaw.json."""
        from clawctl.models.config import GogSkillConfig, SkillsConfig

        user = UserConfig(
            name="alice",
            skills=SkillsConfig(gog=GogSkillConfig(enabled=False, email="alice@example.com")),
            secrets={"openrouter_api_key": "key"},
        )
        config = generate_openclaw_config(user, DefaultsConfig())
        assert "gmail" not in config.get("hooks", {})


class TestUserManagerRestart:
    """Test that restart_user() regenerates openclaw.json with gateway token."""

    def test_restart_user_regenerates_config_with_gateway_token(
        self, sample_config: Config, tmp_data_root: Path, tmp_build_root: Path
    ):
        """Verify that restart_user() regenerates openclaw.json with gateway token auth."""
        from unittest.mock import MagicMock, patch

        from clawctl.core.user_manager import UserManager

        user_mgr = UserManager(sample_config)
        user = sample_config.users[0]
        username = user.name

        # Setup: provision user (creates initial config with gateway token)
        required_secrets = user_mgr.secrets.get_required_secrets(user, sample_config.clawctl.defaults)
        secret_values = {name: f"test_{name}_value" for name, _ in required_secrets}
        user_mgr.provision_user(user, secret_values)

        # Verify initial config has gateway token
        config_path = user_mgr.paths.user_openclaw_config(username)
        assert config_path.exists()
        initial_config = json.loads(config_path.read_text())
        assert "gateway" in initial_config
        assert "auth" in initial_config["gateway"]
        assert initial_config["gateway"]["auth"]["mode"] == "token"
        initial_token = initial_config["gateway"]["auth"]["token"]
        assert len(initial_token) > 0

        # Corrupt the config: remove gateway auth (simulating stale config)
        initial_config["gateway"].pop("auth")
        initial_config["gateway"].pop("controlUi", None)
        config_path.write_text(json.dumps(initial_config, indent=2) + "\n")

        # Mock docker.restart_container to avoid actually restarting
        with patch.object(user_mgr.docker, "restart_container", MagicMock()):
            # Call restart_user (should regenerate config)
            user_mgr.restart_user(username)

        # Verify config was regenerated with gateway token
        regenerated_config = json.loads(config_path.read_text())
        assert "gateway" in regenerated_config
        assert "auth" in regenerated_config["gateway"]
        assert regenerated_config["gateway"]["auth"]["mode"] == "token"
        regenerated_token = regenerated_config["gateway"]["auth"]["token"]
        
        # Token should match what's stored in secrets
        stored_token = user_mgr.secrets.read_secret(username, "openclaw_gateway_token")
        assert regenerated_token == stored_token
        assert regenerated_token == initial_token  # Should be the same token
        
        # Verify controlUi settings for Docker NAT auth
        assert "controlUi" in regenerated_config["gateway"]
        assert regenerated_config["gateway"]["controlUi"]["allowInsecureAuth"] is True
        assert regenerated_config["gateway"]["controlUi"]["dangerouslyDisableDeviceAuth"] is True
        
        # Verify Discord channel config is preserved if enabled
        if user.channels.discord.enabled:
            assert "discord" in regenerated_config["channels"]
            assert regenerated_config["channels"]["discord"]["enabled"] is True
