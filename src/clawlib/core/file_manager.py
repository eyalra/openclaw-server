"""Secure per-user file push management for OpenClaw instances."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from clawlib.core.paths import Paths

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = ".manifest.json"
MANIFEST_VERSION = 1

DEFAULT_MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
DEFAULT_MAX_TOTAL_SIZE = 500 * 1024 * 1024  # 500 MB


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _validate_relative_path(rel: str) -> str:
    """Validate and normalise a relative path, raising on traversal attempts."""
    if not rel or rel.strip() == "":
        raise ValueError("Path must not be empty")

    normalized = Path(rel).as_posix()

    if normalized.startswith("/"):
        raise ValueError(f"Absolute paths are not allowed: {rel}")
    if ".." in normalized.split("/"):
        raise ValueError(f"Path traversal (..) is not allowed: {rel}")
    if "\x00" in rel:
        raise ValueError("Null bytes are not allowed in paths")
    for part in Path(normalized).parts:
        if part in {".", ".."} or part.startswith(".manifest"):
            raise ValueError(f"Reserved path component: {part}")

    return normalized


class FileManager:
    """Manages per-user pushed files with integrity tracking.

    Files are stored at ``data/users/{username}/files/`` and bind-mounted
    read-only into the container at ``/mnt/files``.
    """

    def __init__(
        self,
        paths: Paths,
        *,
        max_file_size: int = DEFAULT_MAX_FILE_SIZE,
        max_total_size: int = DEFAULT_MAX_TOTAL_SIZE,
    ) -> None:
        self.paths = paths
        self.max_file_size = max_file_size
        self.max_total_size = max_total_size

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def push_file(
        self,
        username: str,
        source: Path,
        dest: str | None = None,
        *,
        executable: bool = False,
    ) -> dict:
        """Copy a single file into the user's files directory.

        Args:
            username: Target user.
            source: Local path to the file to push.
            dest: Relative destination path inside the files dir.
                  Defaults to the source filename.
            executable: If True, file gets 755 permissions instead of 644.

        Returns:
            Manifest entry dict for the pushed file.
        """
        source = Path(source).resolve()
        if not source.is_file():
            raise FileNotFoundError(f"Source is not a file: {source}")
        if source.is_symlink():
            raise ValueError(f"Symlinks are not allowed: {source}")

        dest_rel = _validate_relative_path(dest or source.name)
        file_size = source.stat().st_size

        if file_size > self.max_file_size:
            raise ValueError(
                f"File size {file_size} exceeds limit {self.max_file_size}"
            )

        files_dir = self.paths.user_files_dir(username)
        files_dir.mkdir(parents=True, exist_ok=True)
        self._check_total_size(username, file_size, excluding=dest_rel)

        dest_path = files_dir / dest_rel
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        shutil.copy2(source, dest_path)
        self._set_permissions(dest_path, executable=executable)

        checksum = _sha256(dest_path)
        entry = {
            "sha256": checksum,
            "size": file_size,
            "executable": executable,
            "pushed_at": datetime.now(timezone.utc).isoformat(),
        }
        self._manifest_set(username, dest_rel, entry)

        logger.info("Pushed %s → %s/%s (%d bytes)", source.name, username, dest_rel, file_size)
        return entry

    def push_directory(
        self,
        username: str,
        source_dir: Path,
        dest: str | None = None,
    ) -> list[str]:
        """Recursively push all files from a directory.

        Returns list of relative paths that were pushed.
        """
        source_dir = Path(source_dir).resolve()
        if not source_dir.is_dir():
            raise NotADirectoryError(f"Not a directory: {source_dir}")

        pushed: list[str] = []
        for src_file in sorted(source_dir.rglob("*")):
            if not src_file.is_file() or src_file.is_symlink():
                continue
            rel_to_source = src_file.relative_to(source_dir).as_posix()
            if dest:
                dest_rel = f"{dest}/{rel_to_source}"
            else:
                dest_rel = f"{source_dir.name}/{rel_to_source}"
            self.push_file(username, src_file, dest_rel)
            pushed.append(dest_rel)

        return pushed

    def list_files(self, username: str) -> dict[str, dict]:
        """Return the manifest entries for all pushed files.

        Returns:
            {relative_path: {sha256, size, executable, pushed_at}}
        """
        manifest = self._manifest_read(username)
        return manifest.get("files", {})

    def remove_file(self, username: str, rel_path: str) -> bool:
        """Remove a single pushed file and its manifest entry.

        Returns True if the file was removed.
        """
        rel_path = _validate_relative_path(rel_path)
        files_dir = self.paths.user_files_dir(username)
        target = files_dir / rel_path

        removed = False
        if target.is_file():
            target.unlink()
            removed = True
            # Clean up empty parent directories up to files_dir
            parent = target.parent
            while parent != files_dir:
                try:
                    parent.rmdir()
                    parent = parent.parent
                except OSError:
                    break

        self._manifest_remove(username, rel_path)
        if removed:
            logger.info("Removed %s/%s", username, rel_path)
        return removed

    def remove_all(self, username: str) -> int:
        """Remove all pushed files for a user. Returns count of files removed."""
        files_dir = self.paths.user_files_dir(username)
        count = 0
        if files_dir.exists():
            for item in files_dir.iterdir():
                if item.name == MANIFEST_FILENAME:
                    continue
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
                count += 1
            # Reset manifest
            self._manifest_write(username, {"version": MANIFEST_VERSION, "files": {}})
        logger.info("Removed all files for %s (%d entries)", username, count)
        return count

    def verify_integrity(self, username: str) -> dict[str, str]:
        """Verify all pushed files against manifest checksums.

        Returns:
            {relative_path: status} where status is "ok", "mismatch", or "missing".
        """
        manifest = self._manifest_read(username)
        files_dir = self.paths.user_files_dir(username)
        results: dict[str, str] = {}

        for rel_path, entry in manifest.get("files", {}).items():
            file_path = files_dir / rel_path
            if not file_path.is_file():
                results[rel_path] = "missing"
            elif _sha256(file_path) != entry["sha256"]:
                results[rel_path] = "mismatch"
            else:
                results[rel_path] = "ok"

        return results

    # ------------------------------------------------------------------
    # Manifest helpers
    # ------------------------------------------------------------------

    def _manifest_path(self, username: str) -> Path:
        return self.paths.user_files_dir(username) / MANIFEST_FILENAME

    def _manifest_read(self, username: str) -> dict:
        path = self._manifest_path(username)
        if not path.is_file():
            return {"version": MANIFEST_VERSION, "files": {}}
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Corrupt manifest for %s, resetting", username)
            return {"version": MANIFEST_VERSION, "files": {}}

    def _manifest_write(self, username: str, data: dict) -> None:
        path = self._manifest_path(username)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n")

    def _manifest_set(self, username: str, rel_path: str, entry: dict) -> None:
        manifest = self._manifest_read(username)
        manifest["files"][rel_path] = entry
        self._manifest_write(username, manifest)

    def _manifest_remove(self, username: str, rel_path: str) -> None:
        manifest = self._manifest_read(username)
        manifest["files"].pop(rel_path, None)
        self._manifest_write(username, manifest)

    # ------------------------------------------------------------------
    # Size / permission helpers
    # ------------------------------------------------------------------

    def _current_total_size(self, username: str, excluding: str | None = None) -> int:
        """Sum of all file sizes according to the manifest."""
        manifest = self._manifest_read(username)
        total = 0
        for rel, entry in manifest.get("files", {}).items():
            if excluding and rel == excluding:
                continue
            total += entry.get("size", 0)
        return total

    def _check_total_size(
        self, username: str, new_size: int, excluding: str | None = None
    ) -> None:
        current = self._current_total_size(username, excluding=excluding)
        if current + new_size > self.max_total_size:
            raise ValueError(
                f"Total size {current + new_size} would exceed limit "
                f"{self.max_total_size} for user {username}"
            )

    @staticmethod
    def _set_permissions(path: Path, *, executable: bool = False) -> None:
        try:
            os.chmod(path, 0o755 if executable else 0o644)
        except OSError:
            pass
