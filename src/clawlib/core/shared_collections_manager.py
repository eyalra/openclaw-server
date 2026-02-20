"""Sync system for shared document collections from S3 or local directories."""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import schedule

from clawlib.core.paths import Paths
from clawlib.models.config import Config, SharedCollectionsConfig

logger = logging.getLogger(__name__)


class SharedCollectionsManager:
    """Manages shared document collections synced from S3 or local directories.

    Each collection syncs to {data_root}/shared/{collection_name}/.
    Collections can be deeply nested (e.g., "newsletters/2024/january").
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self.paths = Paths(config.clawctl.data_root, config.clawctl.build_root)
        self.shared_config = config.clawctl.shared_collections

    def sync_collection(self, name: str) -> bool:
        """Sync a single collection from the configured source.

        Args:
            name: Collection name (can be nested)

        Returns:
            True if sync succeeded, False otherwise
        """
        if not self.shared_config:
            logger.warning("Shared collections not configured")
            return False

        # Validate collection name
        try:
            collection_path = self.paths.shared_collection_dir(name)
        except ValueError as e:
            logger.error("Invalid collection name %s: %s", name, e)
            return False

        # Dispatch to appropriate sync method based on source type
        if self.shared_config.source_type == "s3":
            return self._sync_from_s3(name, collection_path)
        elif self.shared_config.source_type == "local":
            return self._sync_from_local(name, collection_path)
        else:
            logger.error("Unknown source_type: %s", self.shared_config.source_type)
            return False

    def _sync_from_s3(self, name: str, collection_path: Path) -> bool:
        """Sync a collection from S3.

        Args:
            name: Collection name (can be nested)
            collection_path: Destination path for the collection

        Returns:
            True if sync succeeded, False otherwise
        """
        if not self.shared_config or not self.shared_config.s3_bucket:
            logger.error("S3 configuration not available")
            return False

        # Build S3 source path
        prefix = self.shared_config.s3_prefix.rstrip("/")
        if prefix:
            s3_source = f"s3://{self.shared_config.s3_bucket}/{prefix}/{name}/"
        else:
            s3_source = f"s3://{self.shared_config.s3_bucket}/{name}/"

        # Ensure destination directory exists
        collection_path.mkdir(parents=True, exist_ok=True)

        # Run aws s3 sync
        cmd = [
            "aws",
            "s3",
            "sync",
            s3_source,
            str(collection_path) + "/",
            "--delete",  # Remove files that no longer exist in S3
        ]

        logger.info("Syncing collection %s from %s", name, s3_source)

        try:
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=3600,  # 1 hour timeout
            )
            logger.info("Successfully synced collection %s", name)
            if result.stdout:
                logger.debug("Sync output: %s", result.stdout)

            # Set appropriate permissions (755 dirs, 644 files)
            self._set_permissions(collection_path)

            return True
        except subprocess.CalledProcessError as e:
            logger.error("Failed to sync collection %s: %s", name, e.stderr)
            return False
        except subprocess.TimeoutExpired:
            logger.error("Sync timeout for collection %s", name)
            return False
        except FileNotFoundError:
            logger.error("aws CLI not found. Please install AWS CLI.")
            return False

    def _sync_from_local(self, name: str, collection_path: Path) -> bool:
        """Sync a collection from a local directory.

        Args:
            name: Collection name (can be nested)
            collection_path: Destination path for the collection

        Returns:
            True if sync succeeded, False otherwise
        """
        if not self.shared_config or not self.shared_config.local_source_base:
            logger.error("Local source configuration not available")
            return False

        source_path = self.shared_config.local_source_base / name

        if not source_path.exists():
            logger.warning("Source directory does not exist: %s", source_path)
            return False

        if not source_path.is_dir():
            logger.error("Source path is not a directory: %s", source_path)
            return False

        # Ensure destination directory exists
        collection_path.mkdir(parents=True, exist_ok=True)

        logger.info("Syncing collection %s from %s", name, source_path)

        try:
            # Remove destination if it exists to ensure clean sync (like S3 --delete)
            if collection_path.exists():
                shutil.rmtree(collection_path)

            # Copy the entire directory tree
            shutil.copytree(source_path, collection_path)

            logger.info("Successfully synced collection %s", name)

            # Set appropriate permissions (755 dirs, 644 files)
            self._set_permissions(collection_path)

            return True
        except (OSError, shutil.Error) as e:
            logger.error("Failed to sync collection %s: %s", name, e)
            return False

    def sync_all(self) -> dict[str, bool]:
        """Sync all configured collections.

        Returns:
            {collection_name: success} mapping
        """
        if not self.shared_config:
            logger.warning("Shared collections not configured")
            return {}

        results = {}
        for collection_name in self.shared_config.collections:
            try:
                results[collection_name] = self.sync_collection(collection_name)
            except Exception:
                logger.exception("Sync failed for collection %s", collection_name)
                results[collection_name] = False

        return results

    def _set_permissions(self, path: Path) -> None:
        """Set appropriate permissions on synced files."""
        try:
            # Set directory permissions to 755
            for root, dirs, files in os.walk(path):
                os.chmod(root, 0o755)
                # Set file permissions to 644
                for file in files:
                    file_path = Path(root) / file
                    os.chmod(file_path, 0o644)
        except (PermissionError, OSError) as e:
            logger.warning("Could not set permissions on %s: %s", path, e)

    # --- Daemon management ---

    def run_periodic(self) -> None:
        """Run periodic sync loop (blocking). Handles SIGTERM for clean shutdown."""
        if not self.shared_config:
            logger.error("Shared collections not configured")
            return

        schedule_str = self.shared_config.sync_schedule.lower()
        logger.info("Starting periodic sync with schedule: %s", schedule_str)

        running = True

        def handle_signal(signum, frame):
            nonlocal running
            logger.info("Received signal %d, stopping sync daemon", signum)
            running = False

        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)

        # Run immediately on start
        self.sync_all()

        # Schedule based on schedule string
        if schedule_str == "daily":
            schedule.every().day.at("02:00").do(self.sync_all)
        elif schedule_str == "hourly":
            schedule.every().hour.do(self.sync_all)
        else:
            # Try to parse as cron expression (simple support for "HH:MM" format)
            if ":" in schedule_str and len(schedule_str.split(":")) == 2:
                try:
                    hour, minute = map(int, schedule_str.split(":"))
                    schedule.every().day.at(f"{hour:02d}:{minute:02d}").do(self.sync_all)
                except ValueError:
                    logger.error("Invalid schedule format: %s. Using daily.", schedule_str)
                    schedule.every().day.at("02:00").do(self.sync_all)
            else:
                logger.error("Invalid schedule format: %s. Using daily.", schedule_str)
                schedule.every().day.at("02:00").do(self.sync_all)

        while running:
            schedule.run_pending()
            time.sleep(60)  # Check every minute

        logger.info("Sync daemon stopped")

    def start_daemon(self, config_path: Path) -> int:
        """Start the sync daemon as a background process.

        Args:
            config_path: Absolute path to the clawctl.toml config file.

        Returns:
            The PID of the spawned process.
        """
        import subprocess

        pid_file = self.paths.build_root / ".shared-collections-sync.pid"

        if self.is_daemon_running():
            msg = "Shared collections sync daemon is already running"
            raise RuntimeError(msg)

        # Spawn a detached process running this module with the config path
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "clawctl.core.shared_collections_manager",
                str(config_path),
            ],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        pid_file.write_text(str(proc.pid))
        return proc.pid

    def stop_daemon(self) -> bool:
        """Stop the sync daemon. Returns True if it was running."""
        pid_file = self.paths.build_root / ".shared-collections-sync.pid"

        if not pid_file.is_file():
            return False

        pid = int(pid_file.read_text().strip())

        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass  # already dead

        pid_file.unlink(missing_ok=True)
        return True

    def is_daemon_running(self) -> bool:
        """Check if the sync daemon is currently running."""
        pid_file = self.paths.build_root / ".shared-collections-sync.pid"

        if not pid_file.is_file():
            return False

        pid = int(pid_file.read_text().strip())

        try:
            os.kill(pid, 0)  # signal 0 = check existence
            return True
        except (ProcessLookupError, PermissionError):
            # Stale PID file
            pid_file.unlink(missing_ok=True)
            return False


def _run_daemon_main() -> None:
    """Entry point when this module is run as a script for the daemon process."""
    from clawlib.core.config import load_config

    if len(sys.argv) < 2:
        print("Usage: python -m clawctl.core.shared_collections_manager <config_path>")
        sys.exit(1)

    config_path = Path(sys.argv[1])
    if not config_path.is_file():
        print(f"Config file not found: {config_path}")
        sys.exit(1)

    config = load_config(config_path)

    if not config.clawctl.shared_collections:
        print("Shared collections not configured in config file")
        sys.exit(1)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(
                Paths(config.clawctl.data_root, config.clawctl.build_root).logs_dir
                / "shared-collections-sync.log"
            ),
            logging.StreamHandler(),
        ],
    )

    manager = SharedCollectionsManager(config)
    manager.run_periodic()


if __name__ == "__main__":
    _run_daemon_main()
