"""Cross-platform file locking and backup utilities.

Design invariants:
  - Backups use microsecond timestamps + random suffix to prevent collisions.
  - Backups have restricted permissions (same as secrets files).
  - File locks use ``portalocker`` for cross-platform mutual exclusion.
  - Lock files are sidecar ``.lock`` files (not the data file itself).
"""

from __future__ import annotations

import datetime
import logging
import secrets
import shutil
import sys
from contextlib import contextmanager
from contextlib import suppress
from typing import TYPE_CHECKING

import portalocker

from azure_opencode_setup.errors import LockError

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_logger = logging.getLogger(__name__)


def backup_file(path: Path) -> Path:
    """Create a uniquely-named backup of *path* in the same directory.

    The backup name includes a UTC timestamp with microsecond precision
    plus a 4-hex random suffix to prevent collisions even under rapid
    successive calls.

    Args:
        path (Path): The file to back up (must exist).

    Returns:
        Path: Path to the newly created backup file.
    """
    now = datetime.datetime.now(tz=datetime.UTC)
    ts = now.strftime("%Y%m%dT%H%M%S.%f")
    rand = secrets.token_hex(2)
    backup_name = f"{path.name}.{ts}_{rand}.bak"
    backup_path = path.parent / backup_name

    shutil.copy2(str(path), str(backup_path))

    if sys.platform != "win32":
        backup_path.chmod(0o600)

    return backup_path


@contextmanager
def file_lock(
    path: Path,
    *,
    timeout: float = 30.0,
) -> Iterator[None]:
    """Context manager that holds an exclusive lock on a sidecar lockfile.

    The lock file is ``<path>.lock`` (e.g. ``auth.json.lock``).

    Args:
        path (Path): The data file to protect.
        timeout (float, default=30.0): Seconds to wait for the lock before raising.

    Raises:
        LockError: If the lock cannot be acquired within *timeout*.

    Yields:
        None: The lock is held for the duration of the ``with`` block.
    """
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock: portalocker.Lock | None = None

    try:
        lock = portalocker.Lock(
            str(lock_path),
            mode="w",
            timeout=timeout,
            flags=portalocker.LockFlags.EXCLUSIVE | portalocker.LockFlags.NON_BLOCKING,
        )
        try:
            lock.acquire()
        except portalocker.exceptions.LockException as exc:
            raise LockError(path=str(path), detail=str(exc)) from exc

        yield

    finally:
        if lock is not None:
            with suppress(portalocker.exceptions.LockException):
                _logger.debug("Releasing lock for %s", path)
                lock.release()
