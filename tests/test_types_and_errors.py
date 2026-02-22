"""Tests for typed domain model (types.py) and exceptions (errors.py).

TDD: These tests are written BEFORE the implementation exists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import get_type_hints

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

# ── errors.py tests ──────────────────────────────────────────────────


class TestErrorHierarchy:
    def test_base_error_is_exception(self) -> None:
        assert issubclass(OpenCodeSetupError, Exception)

    def test_invalid_json_error(self) -> None:
        err = InvalidJsonError(path="/fake/bad.json", detail="Unexpected token")
        assert isinstance(err, OpenCodeSetupError)
        assert err.path == "/fake/bad.json"
        assert err.detail == "Unexpected token"
        assert "bad.json" in str(err)

    def test_invalid_schema_error(self) -> None:
        err = InvalidSchemaError(path="/fake/list.json", detail="expected object, got list")
        assert isinstance(err, OpenCodeSetupError)
        assert err.path == "/fake/list.json"
        assert "expected object" in str(err)

    def test_permission_error_wrapped(self) -> None:
        cause = PermissionError("access denied")
        err = PermissionRestrictError(path="/fake/auth.json", cause=cause)
        assert isinstance(err, OpenCodeSetupError)
        assert err.path == "/fake/auth.json"
        assert err.cause is cause
        assert "auth.json" in str(err)

    def test_lock_error(self) -> None:
        err = LockError(path="/fake/auth.json", detail="timed out after 5s")
        assert isinstance(err, OpenCodeSetupError)
        assert "timed out" in str(err)

    def test_validation_error(self) -> None:
        err = ValidationError(field="resource_name", detail="contains invalid chars")
        assert isinstance(err, OpenCodeSetupError)
        assert err.field == "resource_name"
        assert "invalid chars" in str(err)

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
            assert msg, f"{type(err).__name__} has empty str()"
            assert len(msg) > 5


# ── types.py tests ───────────────────────────────────────────────────


class TestAuthEntry:
    def test_auth_entry_shape(self) -> None:
        entry: AuthEntry = {"type": "api", "key": "sk-test-1234"}
        assert entry["type"] == "api"
        assert entry["key"] == "sk-test-1234"

    def test_auth_entry_type_hints(self) -> None:
        hints = get_type_hints(AuthEntry)
        assert "type" in hints
        assert "key" in hints


class TestAuthFile:
    def test_auth_file_is_dict_of_auth_entries(self) -> None:
        data: AuthFile = {
            "azure-cognitive-services": {"type": "api", "key": "k1"},
            "other-provider": {"type": "api", "key": "k2"},
        }
        for entry in data.values():
            _check: AuthEntry = entry
            assert _check["type"] == "api"


class TestProviderConfig:
    def test_provider_config_shape(self) -> None:
        cfg: ProviderConfig = {
            "options": {"baseURL": "https://x.cognitiveservices.azure.com/openai"},
            "whitelist": ["gpt-4o", "model-router"],
        }
        assert "options" in cfg
        assert "whitelist" in cfg

    def test_provider_config_with_models(self) -> None:
        cfg: ProviderConfig = {
            "options": {"baseURL": "https://x.cognitiveservices.azure.com/openai"},
            "whitelist": ["gpt-4o"],
            "models": {"custom": {"name": "Custom (Azure)"}},
        }
        assert cfg.get("models") is not None


class TestOpenCodeConfig:
    def test_opencode_config_shape(self) -> None:
        cfg: OpenCodeConfig = {
            "provider": {
                "azure-cognitive-services": {
                    "options": {"baseURL": "https://x.cognitiveservices.azure.com/openai"},
                    "whitelist": ["gpt-4o"],
                },
            },
        }
        assert "provider" in cfg

    def test_opencode_config_with_disabled_providers(self) -> None:
        cfg: OpenCodeConfig = {
            "disabled_providers": ["azure"],
            "provider": {},
        }
        assert cfg.get("disabled_providers") == ["azure"]
