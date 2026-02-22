"""Tests for paths.py — contract-exact OpenCode paths.

TDD: Written BEFORE implementation.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from azure_opencode_setup.paths import ensure_parent_dir
from azure_opencode_setup.paths import opencode_auth_path
from azure_opencode_setup.paths import opencode_config_path

if TYPE_CHECKING:
    import pytest


def _fake_home() -> Path:
    """Return a deterministic fake home directory for monkeypatch tests."""
    return Path("/fakehome")


class TestOpenCodeConfigPath:
    def test_returns_correct_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Config path must be ~/.config/opencode/opencode.json regardless of OS."""
        monkeypatch.setattr(Path, "home", staticmethod(_fake_home))

        result = opencode_config_path()
        assert result == Path("/fakehome/.config/opencode/opencode.json")

    def test_path_is_absolute(self) -> None:
        result = opencode_config_path()
        assert result.is_absolute()

    def test_path_has_json_suffix(self) -> None:
        assert opencode_config_path().suffix == ".json"


class TestOpenCodeAuthPath:
    def test_returns_correct_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Auth path must be ~/.local/share/opencode/auth.json regardless of OS."""
        monkeypatch.setattr(Path, "home", staticmethod(_fake_home))

        result = opencode_auth_path()
        assert result == Path("/fakehome/.local/share/opencode/auth.json")

    def test_path_is_absolute(self) -> None:
        result = opencode_auth_path()
        assert result.is_absolute()

    def test_path_has_json_suffix(self) -> None:
        assert opencode_auth_path().suffix == ".json"


class TestEnsureParentDir:
    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        target = tmp_path / "sub" / "deep" / "file.json"
        ensure_parent_dir(target)
        assert target.parent.is_dir()

    def test_idempotent_on_existing_dir(self, tmp_path: Path) -> None:
        target = tmp_path / "file.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        # Should not raise
        ensure_parent_dir(target)
        assert target.parent.is_dir()

    def test_posix_permissions_on_auth_parent(self, tmp_path: Path) -> None:
        """On POSIX, auth parent dir should be 0o700 (user-only)."""
        if sys.platform == "win32":
            return  # Skip on Windows — permissions are ACL-based

        target = tmp_path / "secure" / "auth.json"
        ensure_parent_dir(target, secure=True)
        perm = target.parent.stat()
        assert perm.st_mode & 0o777 == 0o700

    def test_secure_flag_false_allows_group(self, tmp_path: Path) -> None:
        """secure=False should not enforce 0o700 on POSIX."""
        if sys.platform == "win32":
            return

        target = tmp_path / "insecure" / "auth.json"
        ensure_parent_dir(target, secure=False)
        perm = target.parent.stat()
        # At least owner should have write
        assert perm.st_mode & 0o200

    def test_does_not_use_appdata(self) -> None:
        """Regression: must never use APPDATA or LOCALAPPDATA paths."""
        for p in [opencode_config_path(), opencode_auth_path()]:
            path_str = str(p)
            assert "AppData" not in path_str
            assert "APPDATA" not in path_str
            local_appdata = os.environ.get("LOCALAPPDATA", "NOVAR")
            assert local_appdata not in path_str or "NOVAR" in path_str
