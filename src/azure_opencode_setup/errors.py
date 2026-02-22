"""Typed exception hierarchy for azure-opencode-setup.

Every error that can reach the CLI must be an ``OpenCodeSetupError`` subclass
so the CLI layer can map it to a deterministic exit code.
"""

from __future__ import annotations


class OpenCodeSetupError(Exception):
    """Base for all azure-opencode-setup errors."""


class InvalidJsonError(OpenCodeSetupError):
    """Raised when a file contains syntactically invalid JSON."""

    def __init__(self, *, path: str, detail: str) -> None:
        """Store structured error context for CLI reporting."""
        self.path = path
        self.detail = detail
        super().__init__(f"Invalid JSON in {path}: {detail}")


class InvalidSchemaError(OpenCodeSetupError):
    """Raised when JSON is valid but has the wrong shape (e.g. array instead of object)."""

    def __init__(self, *, path: str, detail: str) -> None:
        """Store structured error context for CLI reporting."""
        self.path = path
        self.detail = detail
        super().__init__(f"Invalid schema in {path}: {detail}")


class PermissionRestrictError(OpenCodeSetupError):
    """Raised when a filesystem permission operation fails."""

    def __init__(self, *, path: str, cause: BaseException) -> None:
        """Store path and underlying OS cause for diagnostics."""
        self.path = path
        self.cause = cause
        super().__init__(f"Permission error on {path}: {cause}")


class LockError(OpenCodeSetupError):
    """Raised when a file lock cannot be acquired."""

    def __init__(self, *, path: str, detail: str) -> None:
        """Store lock target path and timeout/failure detail."""
        self.path = path
        self.detail = detail
        super().__init__(f"Lock error on {path}: {detail}")


class ValidationError(OpenCodeSetupError):
    """Raised when user input fails validation (e.g. resource_name injection)."""

    def __init__(self, *, field: str, detail: str) -> None:
        """Store which field failed and a human-readable reason."""
        self.field = field
        self.detail = detail
        super().__init__(f"Validation error on '{field}': {detail}")
