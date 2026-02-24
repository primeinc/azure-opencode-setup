"""Tests for locking.py — file locking and backup utilities.

TDD: Written BEFORE implementation.
"""

from __future__ import annotations

import os
import shutil
import sys
from typing import TYPE_CHECKING

import portalocker
import pytest

from azure_opencode_setup.errors import LockError
from azure_opencode_setup.locking import backup_file
from azure_opencode_setup.locking import file_lock

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture

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

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only test")
    def test_backup_has_restricted_perms_on_posix(self, tmp_path: Path) -> None:
        """Backup permissions are restricted on POSIX."""
        original = tmp_path / "auth.json"
        original.write_text("{}", encoding="utf-8")
        original.chmod(0o644)

        backup = backup_file(original)
        mode = backup.stat().st_mode & _MODE_BITS
        _require(condition=mode == _MODE_FILE_USER_ONLY, message="Expected 0o600 perms")

    def test_backup_restricts_permissions_on_windows(
        self,
        tmp_path: Path,
        mocker: MockerFixture,
    ) -> None:
        """Backup file calls restrict_permissions on Windows.

        Verifies that backup_file delegates to io.restrict_permissions
        to enforce owner-only ACL on Windows (or POSIX 0o600 otherwise).

        Backup files must not inherit world-readable ACLs from parent
        directories on Windows.

        Assumptions:
          - Caller validates paths; symlink attacks are out of scope.
          - Race conditions are mitigated by microsecond timestamp + random suffix.
          - If restrict_permissions fails, the backup may be world-readable
            momentarily, but this is acceptable because:
              * The original auth.json is protected by atomic_write_json(secure=True).
              * Backups are ephemeral artifacts.
              * restrict_permissions is best-effort on Windows (logs debug, no raise).
        """
        # ruff: noqa: PLC0415  # Import needed for mocking
        from azure_opencode_setup import locking as locking_module

        mock_restrict = mocker.patch.object(
            locking_module,
            "restrict_permissions",
        )

        original = tmp_path / "auth.json"
        original.write_text('{"secret": "value"}', encoding="utf-8")

        backup = backup_file(original)

        # Assert restrict_permissions was called with the backup path
        mock_restrict.assert_called_once_with(backup)

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX-specific atomic permission test")
    def test_backup_created_with_restricted_perms_atomically(
        self,
        tmp_path: Path,
        mocker: MockerFixture,
    ) -> None:
        """VULN-01/02: Backup must be created WITH restricted perms, not after.

        The current implementation has a TOCTOU race:
          1. shutil.copy2() creates file with inherited permissions
          2. restrict_permissions() tightens perms AFTER creation

        An attacker can read the file in the window between steps 1 and 2.
        If SIGKILL arrives between steps, backup persists world-readable.

        This test verifies that restrict_permissions is called BEFORE the
        backup file content is visible to other processes (i.e., perms are
        set atomically with creation, not as a separate step).
        """
        perms_at_copy_time: list[int] = []

        original_copy2 = shutil.copy2

        def spy_copy2(src: str, dst: str) -> str:
            result = original_copy2(src, dst)
            # Capture perms immediately after copy, before restrict_permissions
            from pathlib import Path

            mode = Path(dst).stat().st_mode & _MODE_BITS
            perms_at_copy_time.append(mode)
            return str(result)

        mocker.patch.object(shutil, "copy2", side_effect=spy_copy2)

        original = tmp_path / "auth.json"
        original.write_text('{"secret": "value"}', encoding="utf-8")
        original.chmod(0o644)  # World-readable source

        backup_file(original)

        # FAILING ASSERTION: Current impl creates file with 0o644, then restricts
        # The file should NEVER exist with permissive perms
        _require(
            condition=len(perms_at_copy_time) == 1,
            message="Expected exactly one copy operation",
        )
        _require(
            condition=perms_at_copy_time[0] == _MODE_FILE_USER_ONLY,
            message=f"TOCTOU: Backup was created with perms {oct(perms_at_copy_time[0])}, "
            f"expected {oct(_MODE_FILE_USER_ONLY)} from creation",
        )

    def test_restrict_permissions_failure_raises_when_strict(
        self,
        tmp_path: Path,
        mocker: MockerFixture,
    ) -> None:
        """VULN-04: ACL failures must be raised when strict mode is requested.

        Current implementation catches OSError and logs at DEBUG level only.
        User believes backup is protected when it may not be.

        When strict=True, restrict_permissions failures MUST propagate.
        """
        from azure_opencode_setup import io as io_module

        mocker.patch.object(
            io_module,
            "_restrict_windows_acl" if sys.platform == "win32" else "Path.chmod",
            side_effect=OSError("Permission denied"),
        )

        original = tmp_path / "auth.json"
        original.write_text('{"secret": "value"}', encoding="utf-8")

        # FAILING: Current impl has no strict parameter and silently suppresses errors
        # This test expects restrict_permissions(path, strict=True) to raise
        from azure_opencode_setup.io import restrict_permissions

        with pytest.raises(OSError, match="Permission denied"):
            restrict_permissions(original, strict=True)

    def test_windows_username_from_win32_api_not_env(
        self,
        tmp_path: Path,
        mocker: MockerFixture,
    ) -> None:
        """VULN-05: Windows username must come from Win32 API, not env var.

        Current implementation trusts os.environ.get("USERNAME") which can
        be attacker-controlled. An attacker could set USERNAME to a different
        user and the ACL would grant access to that user instead.

        The username should come from GetUserNameW or similar Win32 API.
        """
        if sys.platform != "win32":
            pytest.skip("Windows-specific username trust test")

        from azure_opencode_setup import io as io_module

        # Simulate attacker-controlled USERNAME env var
        mocker.patch.dict(os.environ, {"USERNAME": "attacker"})

        # Track what username is passed to the Win32 API
        captured_usernames: list[str] = []
        original_set_acl = io_module._win32_set_owner_only_acl  # pyright: ignore[reportPrivateUsage]  # noqa: SLF001

        def spy_set_acl(file_path: str, username: str) -> None:
            captured_usernames.append(username)
            return original_set_acl(file_path, username)  # pyright: ignore[reportPrivateUsage]

        mocker.patch.object(
            io_module,
            "_win32_set_owner_only_acl",
            side_effect=spy_set_acl,
        )

        original = tmp_path / "auth.json"
        original.write_text('{"secret": "value"}', encoding="utf-8")

        from azure_opencode_setup.io import restrict_permissions

        restrict_permissions(original)

        # FAILING: Current impl uses os.environ["USERNAME"] = "attacker"
        # Should use Win32 GetUserNameW which returns actual current user
        _require(
            condition=len(captured_usernames) == 1,
            message="Expected exactly one ACL call",
        )
        _require(
            condition=captured_usernames[0] != "attacker",
            message="VULN-05: Username came from env var (attacker-controlled), not Win32 API",
        )


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
            flags=(portalocker.LockFlags.EXCLUSIVE | portalocker.LockFlags.NON_BLOCKING),
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
