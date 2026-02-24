"""Tests for merge.py — pure merge functions for auth and config.

TDD: Written BEFORE implementation.
"""

from __future__ import annotations

from typing import cast

import pytest

from azure_opencode_setup.errors import InvalidSchemaError
from azure_opencode_setup.errors import ValidationError
from azure_opencode_setup.merge import merge_auth
from azure_opencode_setup.merge import merge_config
from azure_opencode_setup.merge import validate_resource_name

_EXTRA_VALUE = 42


def _require(*, condition: bool, message: str) -> None:
    """Fail the test if *condition* is false."""
    if not condition:
        pytest.fail(message)


class TestMergeAuth:
    """Behavior tests for merge_auth."""

    def test_inserts_new_provider(self) -> None:
        """Inserts a new provider entry."""
        result = merge_auth({}, provider_id="azure-cog", api_key="sk-123")
        entry = result["azure-cog"]
        _require(condition=isinstance(entry, dict), message="Expected provider entry dict")
        typed = cast("dict[str, object]", entry)
        _require(condition=typed["type"] == "api", message="Expected type=api")
        _require(condition=typed["key"] == "sk-123", message="Expected key preserved")

    def test_updates_existing_provider(self) -> None:
        """Updates an existing provider entry."""
        existing: dict[str, object] = {
            "azure-cog": {"type": "api", "key": "old-key"},
        }
        result = merge_auth(existing, provider_id="azure-cog", api_key="new-key")
        entry = result["azure-cog"]
        _require(condition=isinstance(entry, dict), message="Expected provider entry dict")
        typed = cast("dict[str, object]", entry)
        _require(condition=typed["key"] == "new-key", message="Expected key updated")

    def test_preserves_other_providers(self) -> None:
        """Does not remove unknown auth providers."""
        existing: dict[str, object] = {
            "github-copilot": {"type": "oauth", "token": "gh-tok"},
        }
        result = merge_auth(existing, provider_id="azure-cog", api_key="sk-1")
        _require(
            condition="github-copilot" in result,
            message="Expected existing provider preserved",
        )
        _require(condition="azure-cog" in result, message="Expected new provider inserted")

    def test_rejects_empty_provider_id(self) -> None:
        """Rejects empty provider_id."""
        with pytest.raises(ValidationError):
            merge_auth({}, provider_id="", api_key="sk-123")

    def test_rejects_empty_api_key(self) -> None:
        """Rejects empty api_key."""
        with pytest.raises(ValidationError):
            merge_auth({}, provider_id="azure-cog", api_key="")

    def test_does_not_mutate_input(self) -> None:
        """Does not mutate the input dict."""
        existing: dict[str, object] = {"old": {"type": "api", "key": "k"}}
        original_keys = set(existing.keys())
        _ = merge_auth(existing, provider_id="new", api_key="k2")
        _require(
            condition=set(existing.keys()) == original_keys,
            message="Expected input dict not mutated",
        )


class TestMergeConfig:
    """Behavior tests for merge_config."""

    def test_inserts_new_provider_block(self) -> None:
        """Inserts provider block into config."""
        result = merge_config(
            {},
            provider_id="azure-cognitive-services",
            resource_name="myres",
            whitelist=["gpt-4o"],
            disabled_providers=["azure"],
        )
        _require(condition="provider" in result, message="Expected provider key")
        providers = result["provider"]
        _require(condition=isinstance(providers, dict), message="Expected provider map")
        typed_providers = cast("dict[str, object]", providers)
        _require(
            condition="azure-cognitive-services" in typed_providers,
            message="Expected provider entry",
        )

    def test_sets_base_url_correctly(self) -> None:
        """Constructs baseURL from resource name."""
        result = merge_config(
            {},
            provider_id="azure-cognitive-services",
            resource_name="myres",
            whitelist=["gpt-4o"],
            disabled_providers=[],
        )
        providers = result["provider"]
        _require(condition=isinstance(providers, dict), message="Expected provider map")
        typed_providers = cast("dict[str, object]", providers)
        block = typed_providers["azure-cognitive-services"]
        _require(condition=isinstance(block, dict), message="Expected provider block")
        typed_block = cast("dict[str, object]", block)
        options = typed_block["options"]
        _require(condition=isinstance(options, dict), message="Expected options dict")
        typed_options = cast("dict[str, object]", options)
        base_url = str(typed_options["baseURL"])
        _require(condition=base_url.endswith("/openai"), message="Expected /openai suffix")
        _require(
            condition="myres.cognitiveservices.azure.com" in base_url,
            message="Expected cognitiveservices host",
        )

    def test_preserves_existing_config_keys(self) -> None:
        """Preserves unknown top-level keys."""
        existing: dict[str, object] = {"theme": "dark", "extra": _EXTRA_VALUE}
        result = merge_config(
            existing,
            provider_id="azure-cognitive-services",
            resource_name="myres",
            whitelist=["gpt-4o"],
            disabled_providers=[],
        )
        _require(condition=result["theme"] == "dark", message="Expected theme preserved")
        _require(condition=result["extra"] == _EXTRA_VALUE, message="Expected extra preserved")

    def test_merges_disabled_providers_union(self) -> None:
        """Disabled providers are unioned with existing list."""
        existing: dict[str, object] = {
            "disabled_providers": ["openai"],
        }
        result = merge_config(
            existing,
            provider_id="azure-cognitive-services",
            resource_name="myres",
            whitelist=["gpt-4o"],
            disabled_providers=["azure"],
        )
        dp = result["disabled_providers"]
        _require(condition=isinstance(dp, list), message="Expected list")
        typed_dp = cast("list[str]", dp)
        _require(condition="openai" in typed_dp, message="Expected existing value preserved")
        _require(condition="azure" in typed_dp, message="Expected new value added")

    def test_dedup_disabled_providers(self) -> None:
        """Disabled providers list is deduplicated."""
        existing: dict[str, object] = {
            "disabled_providers": ["azure", "openai"],
        }
        result = merge_config(
            existing,
            provider_id="azure-cognitive-services",
            resource_name="myres",
            whitelist=["gpt-4o"],
            disabled_providers=["azure", "anthropic"],
        )
        dp = result["disabled_providers"]
        _require(condition=isinstance(dp, list), message="Expected list")
        typed_dp = cast("list[str]", dp)
        _require(condition=len(typed_dp) == len(set(typed_dp)), message="Expected dedup")

    def test_disabled_providers_preserves_order(self) -> None:
        """Disabled providers preserve insertion order."""
        existing: dict[str, object] = {
            "disabled_providers": ["z-provider", "a-provider"],
        }
        result = merge_config(
            existing,
            provider_id="azure-cognitive-services",
            resource_name="myres",
            whitelist=["gpt-4o"],
            disabled_providers=["m-provider"],
        )
        dp = result["disabled_providers"]
        _require(condition=isinstance(dp, list), message="Expected list")
        typed_dp = cast("list[str]", dp)
        _require(
            condition=typed_dp.index("z-provider") < typed_dp.index("a-provider"),
            message="Expected existing order preserved",
        )

    def test_rejects_string_disabled_providers(self) -> None:
        """Rejects non-list disabled_providers."""
        existing: dict[str, object] = {"disabled_providers": "not-a-list"}
        with pytest.raises(InvalidSchemaError):
            merge_config(
                existing,
                provider_id="azure-cognitive-services",
                resource_name="myres",
                whitelist=["gpt-4o"],
                disabled_providers=[],
            )

    def test_rejects_non_string_item_in_disabled_providers(self) -> None:
        """Rejects list items that are not strings."""
        existing: dict[str, object] = {
            "disabled_providers": ["azure", 123],
        }
        with pytest.raises(InvalidSchemaError, match="non-string"):
            merge_config(
                existing,
                provider_id="azure-cognitive-services",
                resource_name="myres",
                whitelist=[],
                disabled_providers=[],
            )

    def test_rejects_invalid_resource_name(self) -> None:
        """Rejects invalid resource names."""
        bad_names = [
            "",
            "has spaces",
            "has.dot",
            "has/slash",
            "-starts-with-hyphen",
            "ends-with-hyphen-",
            "a" * 65,
            "has@special",
        ]
        for name in bad_names:
            with pytest.raises(ValidationError, match="resource_name"):
                merge_config(
                    {},
                    provider_id="p",
                    resource_name=name,
                    whitelist=[],
                    disabled_providers=[],
                )

    def test_accepts_valid_resource_names(self) -> None:
        """Accepts valid Azure resource names."""
        valid_names = [
            "a",
            "myresource",
            "my-resource-123",
            "A1",
            "a" * 64,
            "Resource-Name-2024",
        ]
        for name in valid_names:
            result = merge_config(
                {},
                provider_id="p",
                resource_name=name,
                whitelist=[],
                disabled_providers=[],
            )
            _require(condition="provider" in result, message="Expected provider key")

    def test_rejects_empty_provider_id(self) -> None:
        """Rejects empty provider_id."""
        with pytest.raises(ValidationError):
            merge_config(
                {},
                provider_id="",
                resource_name="myres",
                whitelist=[],
                disabled_providers=[],
            )

    def test_whitelist_dedup_preserves_order(self) -> None:
        """Whitelist list is deduped while preserving order."""
        result = merge_config(
            {},
            provider_id="p",
            resource_name="myres",
            whitelist=["model-b", "model-a", "model-b"],
            disabled_providers=[],
        )
        providers = result["provider"]
        _require(condition=isinstance(providers, dict), message="Expected provider map")
        typed_providers = cast("dict[str, object]", providers)
        block = typed_providers["p"]
        _require(condition=isinstance(block, dict), message="Expected provider block")
        typed_block = cast("dict[str, object]", block)
        wl = typed_block["whitelist"]
        _require(condition=isinstance(wl, list), message="Expected whitelist list")
        typed_wl = cast("list[str]", wl)
        _require(condition=typed_wl == ["model-b", "model-a"], message="Expected deduped whitelist")

    def test_does_not_mutate_input(self) -> None:
        """Does not mutate the input dict."""
        existing: dict[str, object] = {"disabled_providers": ["azure"]}
        original_dp = list(cast("list[str]", existing["disabled_providers"]))
        _ = merge_config(
            existing,
            provider_id="p",
            resource_name="myres",
            whitelist=[],
            disabled_providers=["openai"],
        )
        _require(
            condition=cast("list[str]", existing["disabled_providers"]) == original_dp,
            message="Expected input dict not mutated",
        )

    def test_preserves_existing_provider_entries(self) -> None:
        """Preserves unrelated provider entries."""
        existing: dict[str, object] = {
            "provider": {
                "other-provider": {"options": {"baseURL": "https://other.com"}},
            },
        }
        result = merge_config(
            existing,
            provider_id="azure-cognitive-services",
            resource_name="myres",
            whitelist=["gpt-4o"],
            disabled_providers=[],
        )
        providers = result["provider"]
        _require(condition=isinstance(providers, dict), message="Expected provider map")
        typed_providers = cast("dict[str, object]", providers)
        _require(
            condition="other-provider" in typed_providers,
            message="Expected existing provider preserved",
        )
        _require(
            condition="azure-cognitive-services" in typed_providers,
            message="Expected new provider inserted",
        )


class TestValidateResourceName:
    """Behavior tests for validate_resource_name."""

    def test_azure_naming_regex(self) -> None:
        """Accepts common valid Azure resource names."""
        for name in ["a", "myres", "my-res-123", "A1", "a" * 64]:
            validate_resource_name(name)

    def test_rejects_injection(self) -> None:
        """Prevent SSRF / host injection via resource name."""
        attacks = [
            "evil.com/",
            "foo/../bar",
            "foo\nbar",
            "foo bar",
            "foo@bar",
            "foo:8080",
        ]
        for name in attacks:
            with pytest.raises(ValidationError):
                validate_resource_name(name)
