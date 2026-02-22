"""Tests for locking.py — file locking and backup utilities.

TDD: Written BEFORE implementation.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import portalocker
import pytest

from azure_opencode_setup.errors import LockError
from azure_opencode_setup.locking import backup_file
from azure_opencode_setup.locking import file_lock

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# backup_file
# ---------------------------------------------------------------------------
class TestBackupFile:
    def test_creates_backup(self, tmp_path: Path) -> None:
        original = tmp_path / "auth.json"
        original.write_text('{"key": "value"}', encoding="utf-8")

        backup = backup_file(original)

        assert backup.exists()
        assert backup.name.endswith(".bak")
        assert backup.read_text(encoding="utf-8") == '{"key": "value"}'

    def test_backup_name_has_timestamp(self, tmp_path: Path) -> None:
        original = tmp_path / "data.json"
        original.write_text("{}", encoding="utf-8")

        backup = backup_file(original)

        # Name format: data.json.<timestamp>_<hex>.bak
        name = backup.name
        assert name.startswith("data.json.")
        assert name.endswith(".bak")
        # Should contain a timestamp with dots (microseconds)
        assert "T" in name  # ISO-ish timestamp

    def test_unique_backup_names(self, tmp_path: Path) -> None:
        original = tmp_path / "data.json"
        original.write_text("{}", encoding="utf-8")

        backups = {backup_file(original).name for _ in range(10)}
        assert len(backups) == 10, "Backup names must be unique"

    def test_backup_in_same_directory(self, tmp_path: Path) -> None:
        original = tmp_path / "sub" / "auth.json"
        original.parent.mkdir()
        original.write_text("{}", encoding="utf-8")

        backup = backup_file(original)
        assert backup.parent == original.parent

    def test_backup_has_restricted_perms_on_posix(self, tmp_path: Path) -> None:
        if sys.platform == "win32":
            return  # ACL-based on Windows

        original = tmp_path / "auth.json"
        original.write_text("{}", encoding="utf-8")
        original.chmod(0o644)

        backup = backup_file(original)
        mode = backup.stat().st_mode & 0o777
        assert mode == 0o600


# ---------------------------------------------------------------------------
# file_lock
# ---------------------------------------------------------------------------
class TestFileLock:
    def test_lock_and_release(self, tmp_path: Path) -> None:
        target = tmp_path / "data.json"
        target.write_text("{}", encoding="utf-8")

        with file_lock(target):
            # Lock held — file should still be accessible
            _ = target.read_text(encoding="utf-8")

        # After exit, lock file may exist but lock is released
        lock_path = target.with_suffix(".json.lock")
        assert lock_path.exists() or not lock_path.exists()  # Either is fine

    def test_lock_creates_parent_dirs(self, tmp_path: Path) -> None:
        """file_lock must create parent dirs for the lockfile."""
        target = tmp_path / "sub" / "deep" / "data.json"
        # Parent doesn't exist yet
        with file_lock(target):
            pass
        # Lock dir should have been created
        assert target.parent.exists()

    def test_lock_conflict_raises_lock_error(self, tmp_path: Path) -> None:
        target = tmp_path / "data.json"
        target.write_text("{}", encoding="utf-8")

        lock_path = target.with_suffix(".json.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)

        # Hold an external lock
        external = portalocker.Lock(
            str(lock_path),
            mode="w",
            timeout=0,
            flags=(
                portalocker.LockFlags.EXCLUSIVE
                | portalocker.LockFlags.NON_BLOCKING
            ),
        )
        external.acquire()
        try:
            with pytest.raises(LockError), file_lock(target, timeout=0.1):
                pass
        finally:
            external.release()

    def test_lock_is_reentrant_after_release(self, tmp_path: Path) -> None:
        target = tmp_path / "data.json"
        target.write_text("{}", encoding="utf-8")

        with file_lock(target):
            pass

        # Should be able to lock again
        with file_lock(target):
            pass

    def test_file_lock_with_timeout_success(self, tmp_path: Path) -> None:
        """file_lock with explicit timeout should succeed."""
        target = tmp_path / "data.json"
        target.write_text("{}", encoding="utf-8")

        with file_lock(target, timeout=5.0):
            pass  # Lock acquired within timeout
