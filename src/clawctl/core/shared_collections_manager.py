"""S3-based sync system for shared document collections."""

from __future__ import annotations

# Re-export from clawlib for consistency with backup_manager pattern
from clawlib.core.shared_collections_manager import (  # noqa: F401
    SharedCollectionsManager,
    _run_daemon_main,
)

__all__ = ["SharedCollectionsManager", "_run_daemon_main"]

if __name__ == "__main__":
    _run_daemon_main()
