"""Tests for typed domain model (types.py) and exceptions (errors.py).

TDD: These tests are written BEFORE the implementation exists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import get_type_hints

import pytest

from azure_opencode_setup.errors import InvalidJsonError
from azure_opencode_setup.errors import InvalidSchemaError
from azure_opencode_setup.errors import LockError
from azure_opencode_setup.errors import OpenCodeSetupError
from azure_opencode_setup.errors import PermissionRestrictError
from azure_opencode_setup.errors import ValidationError
from azure_opencode_setup.types import AuthEntry

if TYPE_CHECKING:
    from azure_opencode_setup.types import AuthFile
    from azure_opencode_setup.types import OpenCodeConfig
    from azure_opencode_setup.types import ProviderConfig

_MIN_STR_LEN = 5


def _require(*, condition: bool, message: str) -> None:
    """Fail the test if *condition* is false."""
    if not condition:
        pytest.fail(message)


class TestErrorHierarchy:
    """Behavior tests for custom error classes."""

    def test_errors_caught_as_base(self) -> None:
        """Errors can be caught as OpenCodeSetupError."""
        err = InvalidJsonError(path="/fake/bad.json", detail="Unexpected token")
        try:
            raise err
        except OpenCodeSetupError as caught:
            _require(condition=caught is err, message="Expected to catch as base")

    def test_invalid_json_error(self) -> None:
        """InvalidJsonError carries path and detail."""
        err = InvalidJsonError(path="/fake/bad.json", detail="Unexpected token")
        _require(condition=err.path == "/fake/bad.json", message="Expected path preserved")
        _require(condition=err.detail == "Unexpected token", message="Expected detail preserved")
        _require(condition="bad.json" in str(err), message="Expected filename in str")

    def test_invalid_schema_error(self) -> None:
        """InvalidSchemaError carries path and detail."""
        err = InvalidSchemaError(path="/fake/list.json", detail="expected object, got list")
        _require(condition=err.path == "/fake/list.json", message="Expected path preserved")
        _require(condition="expected object" in str(err), message="Expected detail in str")

    def test_permission_error_wrapped(self) -> None:
        """PermissionRestrictError wraps a cause exception."""
        cause = PermissionError("access denied")
        err = PermissionRestrictError(path="/fake/auth.json", cause=cause)
        _require(condition=err.path == "/fake/auth.json", message="Expected path preserved")
        _require(condition=err.cause is cause, message="Expected cause preserved")
        _require(condition="auth.json" in str(err), message="Expected filename in str")

    def test_lock_error(self) -> None:
        """LockError includes detail string."""
        err = LockError(path="/fake/auth.json", detail="timed out after 5s")
        _require(condition="timed out" in str(err), message="Expected detail in str")

    def test_validation_error(self) -> None:
        """ValidationError includes field and detail."""
        err = ValidationError(field="resource_name", detail="contains invalid chars")
        _require(condition=err.field == "resource_name", message="Expected field preserved")
        _require(condition="invalid chars" in str(err), message="Expected detail in str")

    def test_all_errors_have_str(self) -> None:
        """Every custom error must produce a meaningful str()."""
        cases = [
            InvalidJsonError(path="/a", detail="d"),
            InvalidSchemaError(path="/a", detail="d"),
            PermissionRestrictError(path="/a", cause=OSError("x")),
            LockError(path="/a", detail="d"),
            ValidationError(field="f", detail="d"),
        ]
        for err in cases:
            msg = str(err)
            _require(
                condition=bool(msg),
                message=f"{type(err).__name__} has empty str()",
            )
            _require(condition=len(msg) > _MIN_STR_LEN, message="Expected non-trivial message")


class TestAuthEntry:
    """Type-shape tests for AuthEntry."""

    def test_auth_entry_shape(self) -> None:
        """AuthEntry supports required keys."""
        entry: AuthEntry = {"type": "api", "key": "sk-test-1234"}
        _require(condition=entry["type"] == "api", message="Expected type")
        _require(condition=entry["key"] == "sk-test-1234", message="Expected key")

    def test_auth_entry_type_hints(self) -> None:
        """AuthEntry has type hints for required fields."""
        hints = get_type_hints(AuthEntry)
        _require(condition="type" in hints, message="Expected type hint")
        _require(condition="key" in hints, message="Expected key hint")


class TestAuthFile:
    """Type-shape tests for AuthFile."""

    def test_auth_file_is_dict_of_auth_entries(self) -> None:
        """AuthFile maps provider IDs to AuthEntry."""
        data: AuthFile = {
            "azure-cognitive-services": {"type": "api", "key": "k1"},
            "other-provider": {"type": "api", "key": "k2"},
        }
        for entry in data.values():
            _check: AuthEntry = entry
            _require(condition=_check["type"] == "api", message="Expected type")


class TestProviderConfig:
    """Type-shape tests for ProviderConfig."""

    def test_provider_config_shape(self) -> None:
        """ProviderConfig supports options and whitelist."""
        cfg: ProviderConfig = {
            "options": {"baseURL": "https://x.cognitiveservices.azure.com/openai"},
            "whitelist": ["gpt-4o", "model-router"],
        }
        _require(condition="options" in cfg, message="Expected options")
        _require(condition="whitelist" in cfg, message="Expected whitelist")

    def test_provider_config_with_models(self) -> None:
        """ProviderConfig may include models mapping."""
        cfg: ProviderConfig = {
            "options": {"baseURL": "https://x.cognitiveservices.azure.com/openai"},
            "whitelist": ["gpt-4o"],
            "models": {"custom": {"name": "Custom (Azure)"}},
        }
        _require(condition=cfg.get("models") is not None, message="Expected models present")


class TestOpenCodeConfig:
    """Type-shape tests for OpenCodeConfig."""

    def test_opencode_config_shape(self) -> None:
        """OpenCodeConfig supports provider mapping."""
        cfg: OpenCodeConfig = {
            "provider": {
                "azure-cognitive-services": {
                    "options": {"baseURL": "https://x.cognitiveservices.azure.com/openai"},
                    "whitelist": ["gpt-4o"],
                },
            },
        }
        _require(condition="provider" in cfg, message="Expected provider")

    def test_opencode_config_with_disabled_providers(self) -> None:
        """OpenCodeConfig may include disabled_providers."""
        cfg: OpenCodeConfig = {
            "disabled_providers": ["azure"],
            "provider": {},
        }
        _require(
            condition=cfg.get("disabled_providers") == ["azure"],
            message="Expected disabled_providers",
        )
