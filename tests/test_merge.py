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


# ---------------------------------------------------------------------------
# merge_auth
# ---------------------------------------------------------------------------
class TestMergeAuth:
    def test_inserts_new_provider(self) -> None:
        result = merge_auth({}, provider_id="azure-cog", api_key="sk-123")
        entry = result["azure-cog"]
        assert isinstance(entry, dict)
        typed = cast("dict[str, object]", entry)
        assert typed["type"] == "api"
        assert typed["key"] == "sk-123"

    def test_updates_existing_provider(self) -> None:
        existing: dict[str, object] = {
            "azure-cog": {"type": "api", "key": "old-key"},
        }
        result = merge_auth(existing, provider_id="azure-cog", api_key="new-key")
        entry = result["azure-cog"]
        assert isinstance(entry, dict)
        typed = cast("dict[str, object]", entry)
        assert typed["key"] == "new-key"

    def test_preserves_other_providers(self) -> None:
        existing: dict[str, object] = {
            "github-copilot": {"type": "oauth", "token": "gh-tok"},
        }
        result = merge_auth(existing, provider_id="azure-cog", api_key="sk-1")
        assert "github-copilot" in result
        assert "azure-cog" in result

    def test_rejects_empty_provider_id(self) -> None:
        with pytest.raises(ValidationError):
            merge_auth({}, provider_id="", api_key="sk-123")

    def test_rejects_empty_api_key(self) -> None:
        with pytest.raises(ValidationError):
            merge_auth({}, provider_id="azure-cog", api_key="")

    def test_does_not_mutate_input(self) -> None:
        existing: dict[str, object] = {"old": {"type": "api", "key": "k"}}
        original_keys = set(existing.keys())
        _ = merge_auth(existing, provider_id="new", api_key="k2")
        assert set(existing.keys()) == original_keys


# ---------------------------------------------------------------------------
# merge_config
# ---------------------------------------------------------------------------
class TestMergeConfig:
    def test_inserts_new_provider_block(self) -> None:
        result = merge_config(
            {},
            provider_id="azure-cognitive-services",
            resource_name="myres",
            whitelist=["gpt-4o"],
            disabled_providers=["azure"],
        )
        assert "provider" in result
        providers = result["provider"]
        assert isinstance(providers, dict)
        typed_providers = cast("dict[str, object]", providers)
        assert "azure-cognitive-services" in typed_providers

    def test_sets_base_url_correctly(self) -> None:
        result = merge_config(
            {},
            provider_id="azure-cognitive-services",
            resource_name="myres",
            whitelist=["gpt-4o"],
            disabled_providers=[],
        )
        providers = result["provider"]
        assert isinstance(providers, dict)
        typed_providers = cast("dict[str, object]", providers)
        block = typed_providers["azure-cognitive-services"]
        assert isinstance(block, dict)
        typed_block = cast("dict[str, object]", block)
        options = typed_block["options"]
        assert isinstance(options, dict)
        typed_options = cast("dict[str, object]", options)
        base_url = str(typed_options["baseURL"])
        assert base_url.endswith("/openai")
        assert "myres.cognitiveservices.azure.com" in base_url

    def test_preserves_existing_config_keys(self) -> None:
        existing: dict[str, object] = {"theme": "dark", "extra": 42}
        result = merge_config(
            existing,
            provider_id="azure-cognitive-services",
            resource_name="myres",
            whitelist=["gpt-4o"],
            disabled_providers=[],
        )
        assert result["theme"] == "dark"
        assert result["extra"] == 42

    def test_merges_disabled_providers_union(self) -> None:
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
        assert isinstance(dp, list)
        typed_dp = cast("list[str]", dp)
        assert "openai" in typed_dp
        assert "azure" in typed_dp

    def test_dedup_disabled_providers(self) -> None:
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
        assert isinstance(dp, list)
        typed_dp = cast("list[str]", dp)
        # Should be deduplicated
        assert len(typed_dp) == len(set(typed_dp))

    def test_disabled_providers_preserves_order(self) -> None:
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
        assert isinstance(dp, list)
        typed_dp = cast("list[str]", dp)
        # z-provider should come before a-provider (preserved insertion order)
        assert typed_dp.index("z-provider") < typed_dp.index("a-provider")

    def test_rejects_string_disabled_providers(self) -> None:
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
            assert "provider" in result

    def test_rejects_empty_provider_id(self) -> None:
        with pytest.raises(ValidationError):
            merge_config(
                {},
                provider_id="",
                resource_name="myres",
                whitelist=[],
                disabled_providers=[],
            )

    def test_whitelist_dedup_preserves_order(self) -> None:
        result = merge_config(
            {},
            provider_id="p",
            resource_name="myres",
            whitelist=["model-b", "model-a", "model-b"],
            disabled_providers=[],
        )
        providers = result["provider"]
        assert isinstance(providers, dict)
        typed_providers = cast("dict[str, object]", providers)
        block = typed_providers["p"]
        assert isinstance(block, dict)
        typed_block = cast("dict[str, object]", block)
        wl = typed_block["whitelist"]
        assert isinstance(wl, list)
        typed_wl = cast("list[str]", wl)
        assert typed_wl == ["model-b", "model-a"]

    def test_does_not_mutate_input(self) -> None:
        existing: dict[str, object] = {"disabled_providers": ["azure"]}
        original_dp = list(cast("list[str]", existing["disabled_providers"]))
        _ = merge_config(
            existing,
            provider_id="p",
            resource_name="myres",
            whitelist=[],
            disabled_providers=["openai"],
        )
        assert cast("list[str]", existing["disabled_providers"]) == original_dp

    def test_preserves_existing_provider_entries(self) -> None:
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
        assert isinstance(providers, dict)
        typed_providers = cast("dict[str, object]", providers)
        assert "other-provider" in typed_providers
        assert "azure-cognitive-services" in typed_providers


# ---------------------------------------------------------------------------
# validate_resource_name - standalone
# ---------------------------------------------------------------------------
class TestValidateResourceName:
    def test_azure_naming_regex(self) -> None:
        # These should all pass without raising
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
