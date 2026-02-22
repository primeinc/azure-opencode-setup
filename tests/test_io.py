"""Tests for io.py — BOM-healing JSON read, atomic write, permissions.

TDD: Written BEFORE implementation.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from contextlib import contextmanager
from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from azure_opencode_setup.errors import InvalidJsonError
from azure_opencode_setup.errors import InvalidSchemaError
from azure_opencode_setup.io import _restrict_windows_acl
from azure_opencode_setup.io import _win32_set_owner_only_acl
from azure_opencode_setup.io import atomic_write_json
from azure_opencode_setup.io import read_json_object
from azure_opencode_setup.io import restrict_permissions

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


# ---------------------------------------------------------------------------
# read_json_object
# ---------------------------------------------------------------------------
class TestReadJsonObject:
    def test_reads_normal_json(self, tmp_path: Path) -> None:
        p = tmp_path / "data.json"
        p.write_text('{"foo": "bar"}', encoding="utf-8")
        result = read_json_object(p)
        assert result == {"foo": "bar"}

    def test_reads_bom_prefixed_json(self, tmp_path: Path) -> None:
        """BOM-healing: old PS1 script wrote UTF-8 BOM. Must survive."""
        p = tmp_path / "bom.json"
        p.write_bytes(b"\xef\xbb\xbf" + b'{"key": "value"}')
        result = read_json_object(p)
        assert result == {"key": "value"}

    def test_returns_empty_dict_for_missing_file(self, tmp_path: Path) -> None:
        p = tmp_path / "nonexistent.json"
        result = read_json_object(p)
        assert result == {}

    def test_rejects_corrupt_json(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.json"
        p.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(InvalidJsonError) as exc_info:
            read_json_object(p)
        assert str(p) in str(exc_info.value)

    def test_rejects_json_array(self, tmp_path: Path) -> None:
        """Non-dict JSON must raise InvalidSchemaError, not TypeError."""
        p = tmp_path / "array.json"
        p.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(InvalidSchemaError):
            read_json_object(p)

    def test_rejects_json_string(self, tmp_path: Path) -> None:
        p = tmp_path / "string.json"
        p.write_text('"just a string"', encoding="utf-8")
        with pytest.raises(InvalidSchemaError):
            read_json_object(p)

    def test_rejects_json_null(self, tmp_path: Path) -> None:
        p = tmp_path / "null.json"
        p.write_text("null", encoding="utf-8")
        with pytest.raises(InvalidSchemaError):
            read_json_object(p)

    def test_rejects_json_number(self, tmp_path: Path) -> None:
        p = tmp_path / "number.json"
        p.write_text("42", encoding="utf-8")
        with pytest.raises(InvalidSchemaError):
            read_json_object(p)


# ---------------------------------------------------------------------------
# atomic_write_json
# ---------------------------------------------------------------------------
class TestAtomicWriteJson:
    def test_writes_valid_json(self, tmp_path: Path) -> None:
        p = tmp_path / "out.json"
        atomic_write_json(p, {"hello": "world"})
        result = json.loads(p.read_text(encoding="utf-8"))
        assert result == {"hello": "world"}

    def test_output_has_no_bom(self, tmp_path: Path) -> None:
        p = tmp_path / "out.json"
        atomic_write_json(p, {"k": "v"})
        raw = p.read_bytes()
        assert raw[:3] != b"\xef\xbb\xbf", "Must not write UTF-8 BOM"

    def test_output_is_utf8(self, tmp_path: Path) -> None:
        p = tmp_path / "out.json"
        atomic_write_json(p, {"emoji": "\U0001f600"})
        raw = p.read_bytes()
        # Must be valid UTF-8 (no latin-1 or other encodings)
        decoded = raw.decode("utf-8")
        assert json.loads(decoded)["emoji"] == "\U0001f600"

    def test_output_is_pretty_printed(self, tmp_path: Path) -> None:
        p = tmp_path / "out.json"
        atomic_write_json(p, {"a": 1, "b": 2})
        text = p.read_text(encoding="utf-8")
        # Should have newlines (pretty printed with indent)
        assert "\n" in text

    def test_output_ends_with_newline(self, tmp_path: Path) -> None:
        p = tmp_path / "out.json"
        atomic_write_json(p, {"a": 1})
        text = p.read_text(encoding="utf-8")
        assert text.endswith("\n")

    def test_no_temp_file_left_on_success(self, tmp_path: Path) -> None:
        p = tmp_path / "out.json"
        atomic_write_json(p, {"a": 1})
        # Only the target file should exist
        files = list(tmp_path.iterdir())
        assert len(files) == 1
        assert files[0].name == "out.json"

    def test_no_temp_file_left_on_failure(self, tmp_path: Path) -> None:
        p = tmp_path / "out.json"
        # Simulate an exception during serialization by mocking json.dumps
        with (
            patch(
                "azure_opencode_setup.io.json.dumps",
                side_effect=TypeError("boom"),
            ),
            pytest.raises(TypeError),
        ):
            atomic_write_json(p, {"a": 1})

        # No temp files or target file should remain
        files = list(tmp_path.iterdir())
        assert len(files) == 0

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        p = tmp_path / "out.json"
        atomic_write_json(p, {"v": 1})
        atomic_write_json(p, {"v": 2})
        result = json.loads(p.read_text(encoding="utf-8"))
        assert result["v"] == 2


# ---------------------------------------------------------------------------
# restrict_permissions
# ---------------------------------------------------------------------------
class TestRestrictPermissions:
    def test_posix_sets_0600(self, tmp_path: Path) -> None:
        if sys.platform == "win32":
            return  # ACL-based — tested separately

        p = tmp_path / "protected.json"
        p.write_text("{}", encoding="utf-8")
        restrict_permissions(p)
        mode = stat.S_IMODE(p.stat().st_mode)
        assert mode == 0o600

    def test_windows_calls_acl_restriction(self, tmp_path: Path) -> None:
        """On Windows, restrict_permissions must attempt ACL restriction."""
        if sys.platform != "win32":
            return  # Only test on Windows

        p = tmp_path / "protected.json"
        p.write_text("{}", encoding="utf-8")
        # Should not raise — best-effort
        restrict_permissions(p)
        # Verify file is still readable by us
        _ = p.read_text(encoding="utf-8")

    def test_posix_atomic_write_restricts(self, tmp_path: Path) -> None:
        """atomic_write_json with secure=True should restrict permissions."""
        if sys.platform == "win32":
            return

        p = tmp_path / "secure.json"
        atomic_write_json(p, {"data": "value"}, secure=True)
        mode = stat.S_IMODE(p.stat().st_mode)
        assert mode == 0o600

    def test_windows_atomic_write_secure(self, tmp_path: Path) -> None:
        """atomic_write_json with secure=True should not fail on Windows."""
        if sys.platform != "win32":
            return

        p = tmp_path / "secure.json"
        atomic_write_json(p, {"data": "value"}, secure=True)
        # File should exist and be readable
        result = json.loads(p.read_text(encoding="utf-8"))
        assert result["data"] == "value"

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        p = tmp_path / "sub" / "deep" / "file.json"
        atomic_write_json(p, {"nested": True})
        assert p.exists()
        result = json.loads(p.read_text(encoding="utf-8"))
        assert result["nested"] is True


# ---------------------------------------------------------------------------
# Coverage: error paths and platform-specific branches
# ---------------------------------------------------------------------------


class TestReadJsonObjectErrors:
    """Cover error branches in read_json_object."""

    def test_permission_denied_wraps_oserror(self, tmp_path: Path) -> None:
        p = tmp_path / "noaccess.json"
        p.write_text('{"ok": true}', encoding="utf-8")
        with (
            patch.object(
                type(p),
                "read_text",
                side_effect=PermissionError("access denied"),
            ),
            pytest.raises(InvalidJsonError, match="access denied"),
        ):
            read_json_object(p)


class TestAtomicWriteFinallyPaths:
    """Cover finally-block cleanup in atomic_write_json."""

    def test_cleanup_called_on_write_error(self, tmp_path: Path) -> None:
        """If os.write fails, temp file is cleaned up and fd closed."""
        p = tmp_path / "fail.json"
        with (
            patch(
                "azure_opencode_setup.io.os.write",
                side_effect=OSError("write failed"),
            ),
            pytest.raises(OSError, match="write failed"),
        ):
            atomic_write_json(p, {"data": 1})
        # No temp files should remain
        remaining = list(tmp_path.glob("*.tmp*"))
        assert remaining == []


class TestRestrictWindowsAcl:
    """Cover _restrict_windows_acl branches via mocking."""

    def test_no_username_env_returns_silently(self, tmp_path: Path) -> None:
        """When USERNAME env var is missing, _restrict_windows_acl returns."""
        p = tmp_path / "test.json"
        p.write_text("{}", encoding="utf-8")
        with patch.dict(os.environ, {}, clear=True):
            _restrict_windows_acl(p)  # Should not raise

    def test_win32_acl_oserror_suppressed(self, tmp_path: Path) -> None:
        """Win32 ACL OSError is caught and logged, not raised."""
        p = tmp_path / "test.json"
        p.write_text("{}", encoding="utf-8")
        with (
            patch.dict(os.environ, {"USERNAME": "testuser"}),
            patch(
                "azure_opencode_setup.io._win32_set_owner_only_acl",
                side_effect=OSError("win32 fail"),
            ),
        ):
            _restrict_windows_acl(p)  # Should not raise, just log

    def test_restrict_permissions_posix_branch(self, tmp_path: Path) -> None:
        """On POSIX, restrict_permissions calls chmod 0o600."""
        p = tmp_path / "test.json"
        p.write_text("{}", encoding="utf-8")
        with patch("azure_opencode_setup.io.sys") as mock_sys:
            mock_sys.platform = "linux"
            restrict_permissions(p)
            # Verify file was chmod'd (can only fully check on POSIX)
            if sys.platform != "win32":
                mode = p.stat().st_mode & 0o777
                assert mode == stat.S_IRUSR | stat.S_IWUSR


# ---------------------------------------------------------------------------
# _win32_set_owner_only_acl coverage via full ctypes mocking
# ---------------------------------------------------------------------------


@contextmanager
def _win32_ctypes_mock(
    lookup_ok: bool = True,
    init_acl_ok: bool = True,
    add_ace_ok: bool = True,
    set_security_ret: int = 0,
) -> Iterator[MagicMock]:
    """Context manager that patches sys.platform and ctypes for Win32 ACL tests."""
    mock_windll = MagicMock()
    mock_windll.advapi32.LookupAccountNameW.return_value = int(lookup_ok)
    mock_windll.advapi32.InitializeAcl.return_value = int(init_acl_ok)
    mock_windll.advapi32.AddAccessAllowedAce.return_value = int(add_ace_ok)
    mock_windll.advapi32.SetNamedSecurityInfoW.return_value = set_security_ret
    mock_windll.kernel32.GetLastError.return_value = 5

    with (
        patch("azure_opencode_setup.io.sys") as mock_sys,
        patch("azure_opencode_setup.io.ctypes") as mock_ctypes,
    ):
        mock_sys.platform = "win32"
        mock_ctypes.windll = mock_windll
        mock_ctypes.c_ulong = MagicMock
        mock_ctypes.create_string_buffer = MagicMock(return_value=MagicMock())
        mock_ctypes.byref = MagicMock()
        yield mock_windll


class TestWin32SetOwnerOnlyAcl:
    """Cover _win32_set_owner_only_acl branches."""

    def test_non_win32_returns_immediately(self) -> None:
        """On non-Windows, _win32_set_owner_only_acl returns immediately."""
        with patch("azure_opencode_setup.io.sys") as mock_sys:
            mock_sys.platform = "linux"
            _win32_set_owner_only_acl("C:\\fake\\file.json", "testuser")

    def test_lookup_account_failure(self) -> None:
        """LookupAccountNameW failure raises OSError."""
        with _win32_ctypes_mock(lookup_ok=False):
            with pytest.raises(OSError, match="LookupAccountNameW"):
                _win32_set_owner_only_acl("C:\\fake\\file.json", "testuser")

    def test_initialize_acl_failure(self) -> None:
        """InitializeAcl failure raises OSError."""
        with _win32_ctypes_mock(init_acl_ok=False):
            with pytest.raises(OSError, match="InitializeAcl"):
                _win32_set_owner_only_acl("C:\\fake\\file.json", "testuser")

    def test_add_access_allowed_ace_failure(self) -> None:
        """AddAccessAllowedAce failure raises OSError."""
        with _win32_ctypes_mock(add_ace_ok=False):
            with pytest.raises(OSError, match="AddAccessAllowedAce"):
                _win32_set_owner_only_acl("C:\\fake\\file.json", "testuser")

    def test_set_named_security_info_failure(self) -> None:
        """SetNamedSecurityInfoW failure raises OSError."""
        with _win32_ctypes_mock(set_security_ret=5):
            with pytest.raises(OSError, match="SetNamedSecurityInfoW"):
                _win32_set_owner_only_acl("C:\\fake\\file.json", "testuser")

    def test_success_path(self) -> None:
        """Full success path through _win32_set_owner_only_acl."""
        with _win32_ctypes_mock():
            _win32_set_owner_only_acl("C:\\fake\\file.json", "testuser")
