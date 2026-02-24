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

_BACKUP_ITERATIONS = 10
_MODE_BITS = 0o777
_MODE_FILE_USER_ONLY = 0o600


def _require(*, condition: bool, message: str) -> None:
    """Fail the test if *condition* is false."""
    if not condition:
        pytest.fail(message)

class TestBackupFile:
    """Behavior tests for backup_file."""

    def test_creates_backup(self, tmp_path: Path) -> None:
        """Creates a backup file with identical contents."""
        original = tmp_path / "auth.json"
        original.write_text('{"key": "value"}', encoding="utf-8")

        backup = backup_file(original)

        _require(condition=backup.exists(), message="Expected backup file created")
        _require(condition=backup.name.endswith(".bak"), message="Expected .bak suffix")
        _require(
            condition=backup.read_text(encoding="utf-8") == '{"key": "value"}',
            message="Expected contents preserved",
        )

    def test_backup_name_has_timestamp(self, tmp_path: Path) -> None:
        """Backup name includes a timestamp-like segment."""
        original = tmp_path / "data.json"
        original.write_text("{}", encoding="utf-8")

        backup = backup_file(original)

        name = backup.name
        _require(condition=name.startswith("data.json."), message="Expected filename prefix")
        _require(condition=name.endswith(".bak"), message="Expected filename suffix")
        _require(condition="T" in name, message="Expected timestamp marker")

    def test_unique_backup_names(self, tmp_path: Path) -> None:
        """Backup names are unique across multiple calls."""
        original = tmp_path / "data.json"
        original.write_text("{}", encoding="utf-8")

        backups = {backup_file(original).name for _ in range(_BACKUP_ITERATIONS)}
        _require(condition=len(backups) == _BACKUP_ITERATIONS, message="Expected unique names")

    def test_backup_in_same_directory(self, tmp_path: Path) -> None:
        """Backup file is created in the same directory as the original."""
        original = tmp_path / "sub" / "auth.json"
        original.parent.mkdir()
        original.write_text("{}", encoding="utf-8")

        backup = backup_file(original)
        _require(
            condition=backup.parent == original.parent,
            message="Expected same parent directory",
        )

    def test_backup_has_restricted_perms_on_posix(self, tmp_path: Path) -> None:
        """Backup permissions are restricted on POSIX."""
        if sys.platform == "win32":
            return

        original = tmp_path / "auth.json"
        original.write_text("{}", encoding="utf-8")
        original.chmod(0o644)

        backup = backup_file(original)
        mode = backup.stat().st_mode & _MODE_BITS
        _require(condition=mode == _MODE_FILE_USER_ONLY, message="Expected 0o600 perms")

class TestFileLock:
    """Behavior tests for file_lock."""

    def test_lock_and_release(self, tmp_path: Path) -> None:
        """Acquires and releases a lock without breaking reads."""
        target = tmp_path / "data.json"
        target.write_text("{}", encoding="utf-8")

        with file_lock(target):
            _ = target.read_text(encoding="utf-8")

    def test_lock_creates_parent_dirs(self, tmp_path: Path) -> None:
        """Creates parent dirs for the lock file."""
        target = tmp_path / "sub" / "deep" / "data.json"
        with file_lock(target):
            pass
        _require(condition=target.parent.exists(), message="Expected parent dir created")

    def test_lock_conflict_raises_lock_error(self, tmp_path: Path) -> None:
        """Conflicting lock raises LockError."""
        target = tmp_path / "data.json"
        target.write_text("{}", encoding="utf-8")

        lock_path = target.with_suffix(".json.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)

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
        """Can re-acquire a lock after release."""
        target = tmp_path / "data.json"
        target.write_text("{}", encoding="utf-8")

        with file_lock(target):
            pass

        with file_lock(target):
            pass

    def test_file_lock_with_timeout_success(self, tmp_path: Path) -> None:
        """file_lock with explicit timeout should succeed."""
        target = tmp_path / "data.json"
        target.write_text("{}", encoding="utf-8")

        with file_lock(target, timeout=5.0):
            pass
