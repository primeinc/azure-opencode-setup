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
from typing import cast
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

import azure_opencode_setup.io as io_mod
from azure_opencode_setup.errors import InvalidJsonError
from azure_opencode_setup.errors import InvalidSchemaError
from azure_opencode_setup.io import atomic_write_json
from azure_opencode_setup.io import read_json_object
from azure_opencode_setup.io import restrict_permissions

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterator
    from pathlib import Path


_EXPECTED_SINGLE_FILE = 1
_EXPECTED_NO_FILES = 0
_MODE_BITS = 0o777
_MODE_FILE_USER_ONLY = 0o600
_VALUE_NEW = 2


def _require(*, condition: bool, message: str) -> None:
    """Fail the test if *condition* is false."""
    if not condition:
        pytest.fail(message)


def _private_callable(name: str) -> object:
    """Return a private callable from azure_opencode_setup.io by name."""
    attr = getattr(io_mod, name)
    _require(condition=callable(attr), message="Expected callable")
    return attr


class TestReadJsonObject:
    """Behavior tests for read_json_object."""

    def test_reads_normal_json(self, tmp_path: Path) -> None:
        """Reads a normal JSON object."""
        p = tmp_path / "data.json"
        p.write_text('{"foo": "bar"}', encoding="utf-8")
        result = read_json_object(p)
        _require(condition=result == {"foo": "bar"}, message="Expected JSON object")

    def test_reads_jsonc_with_comments(self, tmp_path: Path) -> None:
        """Reads JSONC (JSON with Comments) used by OpenCode config files."""
        p = tmp_path / "config.json"
        jsonc_content = """{
            "model": "gpt-4o",
            // This is a comment
            "provider": {
                "azure": {} // inline comment
            }
        }"""
        p.write_text(jsonc_content, encoding="utf-8")
        result = read_json_object(p)
        _require(condition=result["model"] == "gpt-4o", message="Expected model")
        _require(condition="provider" in result, message="Expected provider")

    def test_preserves_url_with_double_slash(self, tmp_path: Path) -> None:
        """Does not strip // inside strings (e.g., URLs)."""
        p = tmp_path / "config.json"
        p.write_text('{"url": "https://example.com"}', encoding="utf-8")
        result = read_json_object(p)
        _require(condition=result["url"] == "https://example.com", message="URL preserved")

    def test_reads_bom_prefixed_json(self, tmp_path: Path) -> None:
        """BOM-healing: old PS1 script wrote UTF-8 BOM. Must survive."""
        p = tmp_path / "bom.json"
        p.write_bytes(b"\xef\xbb\xbf" + b'{"key": "value"}')
        result = read_json_object(p)
        _require(condition=result == {"key": "value"}, message="Expected BOM-healed JSON")

    def test_returns_empty_dict_for_missing_file(self, tmp_path: Path) -> None:
        """Missing file returns an empty dict."""
        p = tmp_path / "nonexistent.json"
        result = read_json_object(p)
        _require(condition=result == {}, message="Expected empty dict")

    def test_rejects_corrupt_json(self, tmp_path: Path) -> None:
        """Invalid JSON raises InvalidJsonError."""
        p = tmp_path / "bad.json"
        p.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(InvalidJsonError) as exc_info:
            read_json_object(p)
        _require(condition=str(p) in str(exc_info.value), message="Expected path in error")

    def test_rejects_json_array(self, tmp_path: Path) -> None:
        """Non-dict JSON must raise InvalidSchemaError, not TypeError."""
        p = tmp_path / "array.json"
        p.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(InvalidSchemaError):
            read_json_object(p)

    def test_rejects_json_string(self, tmp_path: Path) -> None:
        """JSON string raises InvalidSchemaError."""
        p = tmp_path / "string.json"
        p.write_text('"just a string"', encoding="utf-8")
        with pytest.raises(InvalidSchemaError):
            read_json_object(p)

    def test_rejects_json_null(self, tmp_path: Path) -> None:
        """JSON null raises InvalidSchemaError."""
        p = tmp_path / "null.json"
        p.write_text("null", encoding="utf-8")
        with pytest.raises(InvalidSchemaError):
            read_json_object(p)

    def test_rejects_json_number(self, tmp_path: Path) -> None:
        """JSON number raises InvalidSchemaError."""
        p = tmp_path / "number.json"
        p.write_text("42", encoding="utf-8")
        with pytest.raises(InvalidSchemaError):
            read_json_object(p)


class TestAtomicWriteJson:
    """Behavior tests for atomic_write_json."""

    def test_writes_valid_json(self, tmp_path: Path) -> None:
        """Writes a JSON object to disk."""
        p = tmp_path / "out.json"
        atomic_write_json(p, {"hello": "world"})
        result = json.loads(p.read_text(encoding="utf-8"))
        _require(condition=result == {"hello": "world"}, message="Expected JSON output")

    def test_output_has_no_bom(self, tmp_path: Path) -> None:
        """Written JSON never includes a UTF-8 BOM."""
        p = tmp_path / "out.json"
        atomic_write_json(p, {"k": "v"})
        raw = p.read_bytes()
        _require(condition=raw[:3] != b"\xef\xbb\xbf", message="BOM must not be written")

    def test_output_is_utf8(self, tmp_path: Path) -> None:
        """Written bytes decode as UTF-8."""
        p = tmp_path / "out.json"
        atomic_write_json(p, {"emoji": "\U0001f600"})
        raw = p.read_bytes()
        decoded = raw.decode("utf-8")
        _require(
            condition=json.loads(decoded)["emoji"] == "\U0001f600",
            message="Expected UTF-8 round trip",
        )

    def test_output_is_pretty_printed(self, tmp_path: Path) -> None:
        """Written JSON includes indentation/newlines."""
        p = tmp_path / "out.json"
        atomic_write_json(p, {"a": 1, "b": 2})
        text = p.read_text(encoding="utf-8")
        _require(condition="\n" in text, message="Expected pretty-printed JSON")

    def test_output_ends_with_newline(self, tmp_path: Path) -> None:
        """Written JSON ends with a newline."""
        p = tmp_path / "out.json"
        atomic_write_json(p, {"a": 1})
        text = p.read_text(encoding="utf-8")
        _require(condition=text.endswith("\n"), message="Expected trailing newline")

    def test_no_temp_file_left_on_success(self, tmp_path: Path) -> None:
        """Successful write leaves only the destination file."""
        p = tmp_path / "out.json"
        atomic_write_json(p, {"a": 1})
        files = list(tmp_path.iterdir())
        _require(
            condition=len(files) == _EXPECTED_SINGLE_FILE,
            message="Expected only destination file",
        )
        _require(condition=files[0].name == "out.json", message="Expected destination filename")

    def test_no_temp_file_left_on_failure(self, tmp_path: Path) -> None:
        """Failed serialization leaves no partial files behind."""
        p = tmp_path / "out.json"
        with (
            patch(
                "azure_opencode_setup.io.json.dumps",
                side_effect=TypeError("boom"),
            ),
            pytest.raises(TypeError),
        ):
            atomic_write_json(p, {"a": 1})
        files = list(tmp_path.iterdir())
        _require(condition=len(files) == _EXPECTED_NO_FILES, message="Expected no files")

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        """Second write overwrites the first atomically."""
        p = tmp_path / "out.json"
        atomic_write_json(p, {"v": 1})
        atomic_write_json(p, {"v": _VALUE_NEW})
        result = json.loads(p.read_text(encoding="utf-8"))
        _require(condition=result["v"] == _VALUE_NEW, message="Expected overwrite")


class TestRestrictPermissions:
    """Behavior tests for restrict_permissions and secure writes."""

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only test")
    def test_posix_sets_0600(self, tmp_path: Path) -> None:
        """On POSIX, restrict_permissions sets 0o600."""
        p = tmp_path / "protected.json"
        p.write_text("{}", encoding="utf-8")
        restrict_permissions(p)
        mode = stat.S_IMODE(p.stat().st_mode)
        _require(condition=mode == _MODE_FILE_USER_ONLY, message="Expected 0o600")

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only test")
    def test_windows_calls_acl_restriction(self, tmp_path: Path) -> None:
        """On Windows, restrict_permissions must attempt ACL restriction."""
        p = tmp_path / "protected.json"
        p.write_text("{}", encoding="utf-8")
        restrict_permissions(p)
        _ = p.read_text(encoding="utf-8")

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only test")
    def test_posix_atomic_write_restricts(self, tmp_path: Path) -> None:
        """atomic_write_json with secure=True should restrict permissions."""
        p = tmp_path / "secure.json"
        atomic_write_json(p, {"data": "value"}, secure=True)
        mode = stat.S_IMODE(p.stat().st_mode)
        _require(condition=mode == _MODE_FILE_USER_ONLY, message="Expected 0o600")

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only test")
    def test_windows_atomic_write_secure(self, tmp_path: Path) -> None:
        """atomic_write_json with secure=True should not fail on Windows."""
        p = tmp_path / "secure.json"
        atomic_write_json(p, {"data": "value"}, secure=True)
        result = json.loads(p.read_text(encoding="utf-8"))
        _require(condition=result["data"] == "value", message="Expected readable output")

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        """Creates parent directories when needed."""
        p = tmp_path / "sub" / "deep" / "file.json"
        atomic_write_json(p, {"nested": True})
        _require(condition=p.exists(), message="Expected file created")
        result = json.loads(p.read_text(encoding="utf-8"))
        _require(condition=result["nested"] is True, message="Expected nested value")


class TestReadJsonObjectErrors:
    """Cover error branches in read_json_object."""

    def test_permission_denied_wraps_oserror(self, tmp_path: Path) -> None:
        """Permission errors are wrapped as InvalidJsonError."""
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
        remaining = list(tmp_path.glob("*.tmp*"))
        _require(condition=remaining == [], message="Expected no temp files")


class TestRestrictWindowsAcl:
    """Cover _restrict_windows_acl branches via mocking."""

    def test_no_username_env_returns_silently(self, tmp_path: Path) -> None:
        """When USERNAME env var is missing, _restrict_windows_acl returns."""
        p = tmp_path / "test.json"
        p.write_text("{}", encoding="utf-8")
        with patch.dict(os.environ, {}, clear=True):
            func = cast("Callable[[object], None]", _private_callable("_restrict_windows_acl"))
            func(p)

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
            func = cast("Callable[[object], None]", _private_callable("_restrict_windows_acl"))
            func(p)

    def test_restrict_permissions_posix_branch(self, tmp_path: Path) -> None:
        """On POSIX, restrict_permissions calls chmod 0o600."""
        p = tmp_path / "test.json"
        p.write_text("{}", encoding="utf-8")
        with patch("azure_opencode_setup.io.sys") as mock_sys:
            mock_sys.platform = "linux"
            restrict_permissions(p)
            if sys.platform != "win32":
                mode = p.stat().st_mode & _MODE_BITS
                _require(
                    condition=mode == (stat.S_IRUSR | stat.S_IWUSR),
                    message="Expected user-only mode",
                )


@contextmanager
def _win32_ctypes_mock(
    *,
    fail_calls: set[str] | None = None,
    set_security_ret: int = 0,
) -> Iterator[MagicMock]:
    """Context manager that patches sys.platform and ctypes for Win32 ACL tests."""
    failures = fail_calls or set()
    lookup_ok = "LookupAccountNameW" not in failures
    init_acl_ok = "InitializeAcl" not in failures
    add_ace_ok = "AddAccessAllowedAce" not in failures
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
            func = cast(
                "Callable[[str, str], None]",
                _private_callable("_win32_set_owner_only_acl"),
            )
            func("C:\\fake\\file.json", "testuser")

    def test_lookup_account_failure(self) -> None:
        """LookupAccountNameW failure raises OSError."""
        func = cast("Callable[[str, str], None]", _private_callable("_win32_set_owner_only_acl"))
        with (
            _win32_ctypes_mock(fail_calls={"LookupAccountNameW"}),
            pytest.raises(OSError, match="LookupAccountNameW"),
        ):
            func("C:\\fake\\file.json", "testuser")

    def test_initialize_acl_failure(self) -> None:
        """InitializeAcl failure raises OSError."""
        func = cast("Callable[[str, str], None]", _private_callable("_win32_set_owner_only_acl"))
        with (
            _win32_ctypes_mock(fail_calls={"InitializeAcl"}),
            pytest.raises(OSError, match="InitializeAcl"),
        ):
            func("C:\\fake\\file.json", "testuser")

    def test_add_access_allowed_ace_failure(self) -> None:
        """AddAccessAllowedAce failure raises OSError."""
        func = cast("Callable[[str, str], None]", _private_callable("_win32_set_owner_only_acl"))
        with (
            _win32_ctypes_mock(fail_calls={"AddAccessAllowedAce"}),
            pytest.raises(OSError, match="AddAccessAllowedAce"),
        ):
            func("C:\\fake\\file.json", "testuser")

    def test_set_named_security_info_failure(self) -> None:
        """SetNamedSecurityInfoW failure raises OSError."""
        func = cast("Callable[[str, str], None]", _private_callable("_win32_set_owner_only_acl"))
        with (
            _win32_ctypes_mock(set_security_ret=5),
            pytest.raises(OSError, match="SetNamedSecurityInfoW"),
        ):
            func("C:\\fake\\file.json", "testuser")

    def test_success_path(self) -> None:
        """Full success path through _win32_set_owner_only_acl."""
        func = cast("Callable[[str, str], None]", _private_callable("_win32_set_owner_only_acl"))
        with _win32_ctypes_mock():
            func("C:\\fake\\file.json", "testuser")
