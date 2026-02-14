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
from clawctl.models.config import Config, DefaultsConfig, UserConfig


class TestPaths:
    def test_directory_structure(self, tmp_data_root: Path):
        paths = Paths(tmp_data_root)
        assert paths.data_root == tmp_data_root
        assert paths.logs_dir == tmp_data_root / "logs"
        assert paths.secrets_root == tmp_data_root / "secrets"
        assert paths.users_root == tmp_data_root / "users"

    def test_user_paths(self, tmp_data_root: Path):
        paths = Paths(tmp_data_root)
        assert paths.user_openclaw_dir("alice") == tmp_data_root / "users" / "alice" / "openclaw"
        assert paths.user_backup_dir("alice") == tmp_data_root / "users" / "alice" / "backup"
        assert paths.user_secrets_dir("alice") == tmp_data_root / "secrets" / "alice"

    def test_ensure_base_dirs(self, tmp_data_root: Path):
        paths = Paths(tmp_data_root)
        paths.ensure_base_dirs()
        assert paths.logs_dir.is_dir()
        assert paths.secrets_root.is_dir()
        assert paths.users_root.is_dir()

    def test_ensure_user_dirs(self, tmp_data_root: Path):
        paths = Paths(tmp_data_root)
        paths.ensure_user_dirs("alice")
        assert paths.user_openclaw_dir("alice").is_dir()
        assert paths.user_workspace_dir("alice").is_dir()
        assert paths.user_backup_dir("alice").is_dir()
        assert paths.user_secrets_dir("alice").is_dir()


class TestSecretsManager:
    def test_write_and_read_secret(self, tmp_data_root: Path):
        paths = Paths(tmp_data_root)
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
        assert "anthropic_api_key" in names
        assert "slack_bot_token" in names
        assert "slack_app_token" in names
        assert "discord_token" in names


class TestOpenClawConfig:
    def test_generate_basic_config(self, sample_user: UserConfig):
        config = generate_openclaw_config(sample_user, DefaultsConfig())
        assert config["gateway"]["port"] == 18789
        assert config["gateway"]["bind"] == "lan"
        assert config["agent"]["model"] == "anthropic/claude-opus-4-6"

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
            secrets={"anthropic_api_key": "key"},
        )
        config = generate_openclaw_config(user, DefaultsConfig())
        assert "slack" not in config["channels"]
        assert "discord" not in config["channels"]
