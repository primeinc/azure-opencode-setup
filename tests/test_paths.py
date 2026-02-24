"""Tests for paths.py — contract-exact OpenCode paths.

TDD: Written BEFORE implementation.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from azure_opencode_setup.paths import ensure_parent_dir
from azure_opencode_setup.paths import opencode_auth_path
from azure_opencode_setup.paths import opencode_config_path

_MODE_DIR_USER_ONLY = 0o700
_MODE_BITS = 0o777
_MODE_USER_WRITE = 0o200


def _require(*, condition: bool, message: str) -> None:
    """Fail the test if *condition* is false."""
    if not condition:
        pytest.fail(message)


def _fake_home() -> Path:
    """Return a deterministic fake home directory for monkeypatch tests."""
    return Path("/fakehome")


class TestOpenCodeConfigPath:
    """Contract tests for opencode_config_path."""

    def test_returns_correct_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Config path must be ~/.config/opencode/opencode.json regardless of OS."""
        monkeypatch.setattr(Path, "home", staticmethod(_fake_home))

        result = opencode_config_path()
        _require(
            condition=result == Path("/fakehome/.config/opencode/opencode.json"),
            message="Expected canonical config path",
        )

    def test_path_is_absolute(self) -> None:
        """Config path is absolute."""
        result = opencode_config_path()
        _require(condition=result.is_absolute(), message="Expected absolute path")

    def test_path_has_json_suffix(self) -> None:
        """Config path ends with .json."""
        _require(
            condition=opencode_config_path().suffix == ".json",
            message="Expected .json suffix",
        )


class TestOpenCodeAuthPath:
    """Contract tests for opencode_auth_path."""

    def test_returns_correct_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Auth path must be ~/.local/share/opencode/auth.json regardless of OS."""
        monkeypatch.setattr(Path, "home", staticmethod(_fake_home))

        result = opencode_auth_path()
        _require(
            condition=result == Path("/fakehome/.local/share/opencode/auth.json"),
            message="Expected canonical auth path",
        )

    def test_path_is_absolute(self) -> None:
        """Auth path is absolute."""
        result = opencode_auth_path()
        _require(condition=result.is_absolute(), message="Expected absolute path")

    def test_path_has_json_suffix(self) -> None:
        """Auth path ends with .json."""
        _require(condition=opencode_auth_path().suffix == ".json", message="Expected .json suffix")


class TestEnsureParentDir:
    """Behavior tests for ensure_parent_dir."""

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        """Creates the parent directory chain."""
        target = tmp_path / "sub" / "deep" / "file.json"
        ensure_parent_dir(target)
        _require(condition=target.parent.is_dir(), message="Expected parent dir created")

    def test_idempotent_on_existing_dir(self, tmp_path: Path) -> None:
        """Does not fail when parent already exists."""
        target = tmp_path / "file.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        ensure_parent_dir(target)
        _require(condition=target.parent.is_dir(), message="Expected parent dir exists")

    def test_posix_permissions_on_auth_parent(self, tmp_path: Path) -> None:
        """On POSIX, auth parent dir should be 0o700 (user-only)."""
        if sys.platform == "win32":
            return

        target = tmp_path / "secure" / "auth.json"
        ensure_parent_dir(target, secure=True)
        perm = target.parent.stat()
        _require(
            condition=(perm.st_mode & _MODE_BITS) == _MODE_DIR_USER_ONLY,
            message="Expected secure parent permissions",
        )

    def test_secure_flag_false_allows_group(self, tmp_path: Path) -> None:
        """secure=False should not enforce 0o700 on POSIX."""
        if sys.platform == "win32":
            return

        target = tmp_path / "insecure" / "auth.json"
        ensure_parent_dir(target, secure=False)
        perm = target.parent.stat()
        _require(
            condition=bool(perm.st_mode & _MODE_USER_WRITE),
            message="Expected owner write permission",
        )

    def test_does_not_use_appdata(self) -> None:
        """Regression: must never use APPDATA or LOCALAPPDATA paths."""
        for p in [opencode_config_path(), opencode_auth_path()]:
            path_str = str(p)
            _require(condition="AppData" not in path_str, message="Must not use AppData")
            _require(condition="APPDATA" not in path_str, message="Must not use APPDATA")
            local_appdata = os.environ.get("LOCALAPPDATA", "NOVAR")
            _require(
                condition=(local_appdata not in path_str) or ("NOVAR" in path_str),
                message="Must not use LOCALAPPDATA",
            )
