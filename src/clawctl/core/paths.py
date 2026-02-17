"""Path resolution for clawctl data layout."""

from __future__ import annotations

from pathlib import Path


class Paths:
    """Resolves all host-side paths for a clawctl deployment.

    Layout:
        <data_root>/
        ├── .backup.pid
        ├── logs/
        ├── secrets/<username>/
        └── users/<username>/
            ├── openclaw/       # bind-mounted into container
            └── backup/         # git backup repo
    """

    def __init__(self, data_root: Path) -> None:
        self.data_root = Path(data_root).resolve()

    # --- Top-level ---

    @property
    def logs_dir(self) -> Path:
        return self.data_root / "logs"

    @property
    def backup_pid_file(self) -> Path:
        return self.data_root / ".backup.pid"

    @property
    def secrets_root(self) -> Path:
        return self.data_root / "secrets"

    @property
    def users_root(self) -> Path:
        return self.data_root / "users"

    # --- Per-user ---

    def user_dir(self, username: str) -> Path:
        return self.users_root / username

    def user_openclaw_dir(self, username: str) -> Path:
        """The directory bind-mounted as /home/node/.openclaw in the container."""
        return self.user_dir(username) / "openclaw"

    def user_openclaw_config(self, username: str) -> Path:
        return self.user_openclaw_dir(username) / "openclaw.json"

    def user_workspace_dir(self, username: str) -> Path:
        return self.user_openclaw_dir(username) / "workspace"

    def user_backup_dir(self, username: str) -> Path:
        return self.user_dir(username) / "backup"

    def user_secrets_dir(self, username: str) -> Path:
        return self.secrets_root / username

    # --- Directory creation ---

    def ensure_user_dirs(self, username: str) -> None:
        """Create all directories for a user."""
        self.user_openclaw_dir(username).mkdir(parents=True, exist_ok=True)
        self.user_workspace_dir(username).mkdir(parents=True, exist_ok=True)
        self.user_backup_dir(username).mkdir(parents=True, exist_ok=True)
        self.user_secrets_dir(username).mkdir(parents=True, exist_ok=True)

    def ensure_base_dirs(self) -> None:
        """Create base directory structure."""
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.secrets_root.mkdir(parents=True, exist_ok=True)
        self.users_root.mkdir(parents=True, exist_ok=True)
