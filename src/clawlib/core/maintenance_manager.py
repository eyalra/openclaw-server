"""Nightly maintenance cycle: backup all users, then restart all containers."""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import schedule

from clawlib.core.paths import Paths
from clawlib.models.config import Config

logger = logging.getLogger(__name__)


class MaintenanceManager:
    """Runs nightly maintenance: git-backup all users, then restart all containers.

    The restart step always writes openclaw.json before restarting, which
    ensures OpenClaw's doctor runs on boot and re-enables plugins (e.g. Discord)
    that require a config change to initialize.
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self.paths = Paths(config.clawctl.data_root, config.clawctl.build_root)
        self.maintenance_config = config.clawctl.maintenance

    def run_cycle(self) -> dict:
        """Run one complete maintenance cycle: backup → restart.

        Returns a dict with keys:
            backed_up: list of usernames that got a new backup commit
            restarted: list of usernames whose containers were restarted
        """
        results: dict = {"backed_up": [], "restarted": [], "errors": []}

        # Step 1: backup (if configured)
        if self.maintenance_config.backup_before_restart:
            logger.info("Maintenance: starting backup phase")
            try:
                from clawlib.core.backup_manager import BackupManager
                backup_mgr = BackupManager(self.config)
                backup_results = backup_mgr.backup_all()
                results["backed_up"] = [u for u, committed in backup_results.items() if committed]
                logger.info(
                    "Maintenance: backup complete — %d users backed up",
                    len(results["backed_up"]),
                )
            except Exception:
                logger.exception("Maintenance: backup phase failed")
                results["errors"].append("backup_failed")

        # Step 2: restart (write config + restart container)
        logger.info("Maintenance: starting restart phase")
        try:
            from clawlib.core.user_manager import UserManager
            user_mgr = UserManager(self.config)
            restarted = user_mgr.restart_all()
            results["restarted"] = restarted
            logger.info(
                "Maintenance: restart complete — %d containers restarted",
                len(restarted),
            )
        except Exception:
            logger.exception("Maintenance: restart phase failed")
            results["errors"].append("restart_failed")

        # Record last run timestamp
        try:
            self.paths.logs_dir.mkdir(parents=True, exist_ok=True)
            self.paths.maintenance_last_run_file.write_text(
                datetime.now(timezone.utc).isoformat()
            )
        except Exception:
            pass

        return results

    def get_last_run(self) -> str | None:
        """Return ISO timestamp of last completed maintenance cycle, or None."""
        f = self.paths.maintenance_last_run_file
        if f.is_file():
            try:
                return f.read_text().strip()
            except Exception:
                return None
        return None

    def get_next_run(self) -> str | None:
        """Return ISO timestamp of next scheduled run, or None if scheduler not active."""
        jobs = schedule.get_jobs()
        if not jobs:
            return None
        # Find the maintenance job (tagged "maintenance")
        maintenance_jobs = [j for j in jobs if "maintenance" in (j.tags or set())]
        if not maintenance_jobs:
            # Fall back to first job
            maintenance_jobs = jobs
        next_run = min(j.next_run for j in maintenance_jobs if j.next_run)
        return next_run.isoformat() if next_run else None

    # --- Daemon management ---

    def run_periodic(self) -> None:
        """Run periodic maintenance loop (blocking). Handles SIGTERM for clean shutdown."""
        restart_time = self.maintenance_config.restart_time
        logger.info("Starting maintenance daemon, scheduled daily at %s UTC", restart_time)

        running = True

        def handle_signal(signum, frame):
            nonlocal running
            logger.info("Received signal %d, stopping maintenance daemon", signum)
            running = False

        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)

        schedule.every().day.at(restart_time).tag("maintenance").do(self.run_cycle)

        logger.info(
            "Maintenance daemon ready. Next run scheduled at %s UTC",
            restart_time,
        )

        while running:
            schedule.run_pending()
            time.sleep(30)

        schedule.clear("maintenance")
        logger.info("Maintenance daemon stopped")

    def start_daemon(self, config_path: Path) -> int:
        """Start the maintenance daemon as a background process.

        Args:
            config_path: Absolute path to the clawctl.toml config file.

        Returns the PID of the spawned process.
        """
        import subprocess

        pid_file = self.paths.maintenance_pid_file

        if self.is_daemon_running():
            msg = "Maintenance daemon is already running"
            raise RuntimeError(msg)

        self.paths.logs_dir.mkdir(parents=True, exist_ok=True)

        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "clawlib.core.maintenance_manager",
                str(config_path),
            ],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        pid_file.write_text(str(proc.pid))
        return proc.pid

    def stop_daemon(self) -> bool:
        """Stop the maintenance daemon. Returns True if it was running."""
        pid_file = self.paths.maintenance_pid_file

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
        """Check if the maintenance daemon is currently running."""
        pid_file = self.paths.maintenance_pid_file

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
        print("Usage: python -m clawlib.core.maintenance_manager <config_path>")
        sys.exit(1)

    config_path = Path(sys.argv[1])
    if not config_path.is_file():
        print(f"Config file not found: {config_path}")
        sys.exit(1)

    config = load_config(config_path)
    paths = Paths(config.clawctl.data_root, config.clawctl.build_root)
    paths.logs_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(paths.logs_dir / "maintenance.log"),
            logging.StreamHandler(),
        ],
    )

    manager = MaintenanceManager(config)
    manager.run_periodic()


if __name__ == "__main__":
    _run_daemon_main()
