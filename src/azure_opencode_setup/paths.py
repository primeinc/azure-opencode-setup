"""Canonical file paths for OpenCode config and auth.

Contract (from OpenCode docs — verified via Context7):
  - Config: ``~/.config/opencode/opencode.json``
  - Auth:   ``~/.local/share/opencode/auth.json``

These paths are absolute and OS-independent.  We never use
``%APPDATA%``, ``%LOCALAPPDATA%``, or ``platformdirs``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_CONFIG_REL = Path(".config") / "opencode" / "opencode.json"
_AUTH_REL = Path(".local") / "share" / "opencode" / "auth.json"


def opencode_config_path() -> Path:
    """Return the absolute path to ``opencode.json``."""
    return Path.home() / _CONFIG_REL


def opencode_auth_path() -> Path:
    """Return the absolute path to ``auth.json``."""
    return Path.home() / _AUTH_REL


def ensure_parent_dir(target: Path, *, secure: bool = False) -> None:
    """Create parent directories for *target* if they don't exist.

    Args:
        target: The file whose parent directory chain should exist.
        secure: If ``True`` **and** on POSIX, set the immediate parent to
                ``0o700`` (user-only).  On Windows this is a no-op; ACL
                restriction happens at the file level in ``io.py``.
    """
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)

    if secure and sys.platform != "win32":
        parent.chmod(0o700)
