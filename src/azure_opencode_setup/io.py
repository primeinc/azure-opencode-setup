"""JSON I/O with BOM-healing, atomic writes, and permission restriction.

Design invariants:
  - Reads with ``utf-8-sig`` to silently strip a UTF-8 BOM.
  - Writes clean UTF-8 without BOM.
  - Writes are atomic: tempfile → fsync → replace.
  - ``secure=True`` restricts file to owner-only (POSIX: 0o600, Windows: ACL).
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import re
import stat
import sys
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING
from typing import cast

from azure_opencode_setup.errors import InvalidJsonError
from azure_opencode_setup.errors import InvalidSchemaError

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Mapping
    from typing import Protocol

    class _Advapi32(Protocol):
        LookupAccountNameW: Callable[..., int]
        GetLengthSid: Callable[..., int]
        InitializeAcl: Callable[..., int]
        AddAccessAllowedAce: Callable[..., int]
        SetNamedSecurityInfoW: Callable[..., int]
        GetUserNameW: Callable[..., int]

    class _Kernel32(Protocol):
        GetLastError: Callable[[], int]

    class _Windll(Protocol):
        advapi32: object
        kernel32: object


_logger = logging.getLogger(__name__)


def _strip_jsonc_comments(text: str) -> str:
    """Strip single-line // comments from JSONC text.

    OpenCode config files support JSON with Comments (JSONC). This function
    removes // comments while preserving strings that contain //.

    Args:
        text: JSON or JSONC text.

    Returns:
        JSON text with comments removed.
    """
    # Match strings first to skip them, then match // comments to remove
    # Pattern: "..." strings (with escaped quotes) OR // comments to end of line
    pattern = r'"(?:[^"\\]|\\.)*"|//[^\n]*'

    def replacer(match: re.Match[str]) -> str:
        s = match.group(0)
        if s.startswith('"'):
            return s  # Keep strings
        return ""  # Remove comments

    return re.sub(pattern, replacer, text)


def read_json_object(path: Path) -> dict[str, object]:
    """Read a JSON file and return its contents as a dict.

    Args:
        path (Path): Path to the JSON file.

    Returns:
        dict[str, object]: The parsed dict. If the file does not exist, returns ``{}``.

    Raises:
        InvalidJsonError: If the file contains syntactically invalid JSON.
        InvalidSchemaError: If the JSON is valid but is not a dict/object.
    """
    if not path.exists():
        return {}

    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        msg = str(exc)
        raise InvalidJsonError(path=str(path), detail=msg) from exc

    # Strip JSONC comments before parsing
    text = _strip_jsonc_comments(text)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InvalidJsonError(path=str(path), detail=str(exc)) from exc

    if not isinstance(parsed, dict):
        actual_type = type(parsed).__name__
        raise InvalidSchemaError(
            path=str(path),
            detail=f"Expected a JSON object (dict), got {actual_type}",
        )

    return cast("dict[str, object]", parsed)


def atomic_write_json(
    path: Path,
    data: Mapping[str, object],
    *,
    secure: bool = False,
) -> None:
    """Atomically write *data* as pretty-printed JSON to *path*.

    1. Serialize to string (fail-fast before touching disk).
    2. Write to a tempfile in the same directory.
    3. fsync the tempfile.
    4. Replace the target file atomically.
    5. Optionally restrict permissions.

    Args:
        path (Path): Destination file.
        data (Mapping[str, object]): Dict-like data to serialize.
        secure (bool, default=False): If ``True``, restrict the file to owner-only after write.

    Returns:
        None: Writes the JSON file as a side effect.
    """
    content = json.dumps(dict(data), indent=2, ensure_ascii=False) + "\n"
    encoded = content.encode("utf-8")

    path.parent.mkdir(parents=True, exist_ok=True)

    fd = -1
    tmp_path_str: str | None = None
    try:
        fd, tmp_path_str = tempfile.mkstemp(
            dir=str(path.parent),
            prefix=".tmp_",
            suffix=".json",
        )
        # Handle partial writes from os.write
        written = 0
        while written < len(encoded):
            written += os.write(fd, encoded[written:])
        os.fsync(fd)
        os.close(fd)
        fd = -1

        _atomic_replace(tmp_path_str, str(path))
        tmp_path_str = None

        if secure:
            restrict_permissions(path, strict=True)

    finally:
        if fd >= 0:
            os.close(fd)
        if tmp_path_str is not None:
            _cleanup_tmp(tmp_path_str)


def restrict_permissions(path: Path, *, strict: bool = False) -> None:
    """Restrict *path* to owner-only access.

    Args:
        path (Path): File path to restrict.
        strict (bool, default=False): If ``True``, raise on failure instead of logging.

    Returns:
        None: Applies filesystem permission changes as a side effect.

    Raises:
        OSError: If ``strict=True`` and permission restriction fails.

    Notes:
        - POSIX: ``chmod 0o600``.
        - Windows: Uses Win32 API via ctypes to set owner-only ACL.
    """
    if sys.platform == "win32":
        _restrict_windows_acl(path, strict=strict)
    else:
        try:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            if strict:
                raise
            _logger.debug("Failed to restrict permissions for %s", path)


def _cleanup_tmp(tmp_path_str: str) -> None:
    """Remove a temporary file, ignoring errors.

    Args:
        tmp_path_str (str): Path string to remove.

    Returns:
        None: Removes a temporary file as a side effect.
    """
    with suppress(OSError):
        Path(tmp_path_str).unlink()


def _atomic_replace(src: str, dst: str) -> None:
    """Replace *dst* with *src* atomically.

    On POSIX, ``Path.replace`` is atomic.
    On Windows, ``Path.replace`` works for files (since Python 3.3+).

    Args:
        src (str): Source path.
        dst (str): Destination path.

    Returns:
        None: Replaces the destination file as a side effect.
    """
    Path(src).replace(dst)


def _get_current_username() -> str:
    """Get current username via Win32 GetUserNameW API.

    Returns:
        str: The current user's username.

    Raises:
        OSError: If the Win32 API call fails.
    """
    if sys.platform != "win32":
        return ""

    windll = cast("_Windll", ctypes.windll)
    advapi32 = cast("_Advapi32", windll.advapi32)
    kernel32 = cast("_Kernel32", windll.kernel32)

    size = ctypes.c_ulong(256)
    buf = ctypes.create_unicode_buffer(256)

    if not advapi32.GetUserNameW(buf, ctypes.byref(size)):
        err_code = kernel32.GetLastError()
        msg = f"GetUserNameW failed: error {err_code}"
        raise OSError(msg)

    return buf.value


def _restrict_windows_acl(path: Path, *, strict: bool = False) -> None:
    """Best-effort ACL restriction on Windows using Win32 ctypes.

    Sets the file DACL to grant GENERIC_ALL to the current user only,
    removing inherited ACEs.

    Args:
        path (Path): File path to restrict.
        strict (bool, default=False): If ``True``, raise on failure instead of logging.

    Returns:
        None: Attempts to apply ACL restriction as a side effect.

    Raises:
        OSError: If ``strict=True`` and ACL restriction fails.
    """
    try:
        username = _get_current_username()
        if not username:
            return
        _win32_set_owner_only_acl(str(path), username)
    except OSError as exc:
        if strict:
            raise
        _logger.debug("Win32 ACL restriction failed for %s: %s", path, exc)


def _win32_set_owner_only_acl(file_path: str, username: str) -> None:
    """Use Win32 API to restrict file to owner-only access.

    This replaces the icacls subprocess call to avoid S603 (subprocess
    with variable arguments).  Uses SetNamedSecurityInfoW via ctypes.

    Args:
        file_path (str): Path to the target file.
        username (str): Username that should retain access.

    Returns:
        None: Applies a DACL to the file as a side effect.

    Raises:
        OSError: If Win32 API calls fail.
    """
    if sys.platform != "win32":
        return

    windll = cast("_Windll", ctypes.windll)
    advapi32 = cast("_Advapi32", windll.advapi32)
    kernel32 = cast("_Kernel32", windll.kernel32)

    se_file_object = 1
    dacl_security_information = 0x00000004
    acl_revision = 2
    generic_all = 0x10000000

    sid = ctypes.create_string_buffer(256)
    sid_size = ctypes.c_ulong(256)
    domain = ctypes.create_unicode_buffer(256)
    domain_size = ctypes.c_ulong(256)
    sid_type = ctypes.c_ulong()

    ok = advapi32.LookupAccountNameW(
        None,
        username,
        sid,
        ctypes.byref(sid_size),
        domain,
        ctypes.byref(domain_size),
        ctypes.byref(sid_type),
    )
    if not ok:
        err_code = kernel32.GetLastError()
        msg = f"LookupAccountNameW failed: error {err_code}"
        raise OSError(msg)

    sid_length = advapi32.GetLengthSid(sid)
    ace_size = 4 + 4 + sid_length
    acl_size = 8 + ace_size

    acl_buf = ctypes.create_string_buffer(acl_size)
    if not advapi32.InitializeAcl(acl_buf, acl_size, acl_revision):
        err_code = kernel32.GetLastError()
        msg = f"InitializeAcl failed: error {err_code}"
        raise OSError(msg)

    if not advapi32.AddAccessAllowedAce(
        acl_buf,
        acl_revision,
        generic_all,
        sid,
    ):
        err_code = kernel32.GetLastError()
        msg = f"AddAccessAllowedAce failed: error {err_code}"
        raise OSError(msg)

    protected_dacl = 0x80000000 | dacl_security_information
    result = advapi32.SetNamedSecurityInfoW(
        file_path,
        se_file_object,
        protected_dacl,
        None,
        None,
        acl_buf,
        None,
    )
    if result != 0:
        msg = f"SetNamedSecurityInfoW failed: error {result}"
        raise OSError(msg)
