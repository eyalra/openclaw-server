"""Tests for BackupManager."""

from __future__ import annotations

from pathlib import Path

import pytest

from clawctl.core.backup_manager import BackupManager
from clawctl.core.paths import Paths
from clawctl.models.config import Config


class TestBackupManager:
    @pytest.fixture
    def manager(self, sample_config: Config) -> BackupManager:
        paths = Paths(sample_config.clawctl.data_root, sample_config.clawctl.build_root)
        paths.ensure_base_dirs()
        paths.ensure_user_dirs("testuser")
        return BackupManager(sample_config)

    def test_init_user_backup(self, manager: BackupManager):
        manager.init_user_backup("testuser")
        backup_dir = manager.paths.user_backup_dir("testuser")
        assert (backup_dir / ".git").is_dir()
        assert (backup_dir / ".gitignore").is_file()

    def test_init_idempotent(self, manager: BackupManager):
        manager.init_user_backup("testuser")
        manager.init_user_backup("testuser")  # should not error
        backup_dir = manager.paths.user_backup_dir("testuser")
        assert (backup_dir / ".git").is_dir()

    def test_backup_no_changes(self, manager: BackupManager):
        manager.init_user_backup("testuser")
        result = manager.backup_user("testuser")
        assert result is False  # no files to backup

    def test_backup_with_changes(self, manager: BackupManager):
        # Create a file in the openclaw workspace
        workspace = manager.paths.user_workspace_dir("testuser")
        (workspace / "memory.md").write_text("# Memory\nSome context here")

        result = manager.backup_user("testuser")
        assert result is True

        # Verify git commit was made
        import git

        repo = git.Repo(manager.paths.user_backup_dir("testuser"))
        commits = list(repo.iter_commits())
        # Initial commit + backup commit
        assert len(commits) == 2
        assert "Backup" in commits[0].message

    def test_backup_detects_no_further_changes(self, manager: BackupManager):
        workspace = manager.paths.user_workspace_dir("testuser")
        (workspace / "memory.md").write_text("# Memory")

        manager.backup_user("testuser")
        result = manager.backup_user("testuser")
        assert result is False  # no new changes

    def test_backup_detects_modifications(self, manager: BackupManager):
        workspace = manager.paths.user_workspace_dir("testuser")
        (workspace / "memory.md").write_text("# Memory v1")
        manager.backup_user("testuser")

        (workspace / "memory.md").write_text("# Memory v2")
        result = manager.backup_user("testuser")
        assert result is True

    def test_backup_all(self, manager: BackupManager):
        workspace = manager.paths.user_workspace_dir("testuser")
        (workspace / "test.md").write_text("content")

        results = manager.backup_all()
        assert results["testuser"] is True

    def test_daemon_not_running_initially(self, manager: BackupManager):
        assert manager.is_daemon_running() is False

    def test_stale_pid_file_cleaned(self, manager: BackupManager):
        # Write a PID that doesn't exist
        manager.paths.backup_pid_file.write_text("99999999")
        assert manager.is_daemon_running() is False
        assert not manager.paths.backup_pid_file.exists()
