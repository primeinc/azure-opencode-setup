"""Tests for config.py — merge logic, atomic writes, no BOM."""

from __future__ import annotations

import json
from pathlib import Path

from azure_opencode_setup.config import write_auth, write_config


class TestNoBOM:
    """The bug that crashed OpenCode: UTF-8 BOM in JSON files."""

    def test_auth_json_no_bom(self, tmp_path: Path) -> None:
        auth_path = tmp_path / "auth.json"
        write_auth(auth_path, "azure-cognitive-services", "fake-key-123")
        raw = auth_path.read_bytes()
        assert raw[:3] != b"\xef\xbb\xbf", "auth.json must not have a UTF-8 BOM"
        json.loads(raw)

    def test_config_json_no_bom(self, tmp_path: Path) -> None:
        config_path = tmp_path / "opencode.json"
        write_config(
            config_path,
            provider_id="azure-cognitive-services",
            resource_name="my-resource",
            whitelist=["gpt-4o", "gpt-4o-mini"],
            disabled_providers=["azure"],
        )
        raw = config_path.read_bytes()
        assert raw[:3] != b"\xef\xbb\xbf", "opencode.json must not have a UTF-8 BOM"
        json.loads(raw)


class TestAuthMerge:
    """The bug that nuked existing auth entries."""

    def test_preserves_existing_provider(self, tmp_path: Path) -> None:
        auth_path = tmp_path / "auth.json"
        existing = {"github-copilot": {"type": "oauth", "token": "ghp_xxx"}}
        auth_path.write_text(json.dumps(existing), encoding="utf-8")

        write_auth(auth_path, "azure-cognitive-services", "fake-key-123")

        result = json.loads(auth_path.read_text(encoding="utf-8"))
        assert "github-copilot" in result, "existing providers must survive merge"
        assert result["github-copilot"]["type"] == "oauth"
        assert "azure-cognitive-services" in result
        assert result["azure-cognitive-services"]["key"] == "fake-key-123"

    def test_creates_fresh_when_missing(self, tmp_path: Path) -> None:
        auth_path = tmp_path / "auth.json"
        write_auth(auth_path, "azure-cognitive-services", "fake-key-123")

        result = json.loads(auth_path.read_text(encoding="utf-8"))
        assert "azure-cognitive-services" in result

    def test_upserts_without_duplicating(self, tmp_path: Path) -> None:
        auth_path = tmp_path / "auth.json"
        write_auth(auth_path, "azure-cognitive-services", "old-key")
        write_auth(auth_path, "azure-cognitive-services", "new-key")

        result = json.loads(auth_path.read_text(encoding="utf-8"))
        assert result["azure-cognitive-services"]["key"] == "new-key"


class TestConfigMerge:
    """Existing opencode.json keys must survive merge."""

    def test_preserves_existing_keys(self, tmp_path: Path) -> None:
        config_path = tmp_path / "opencode.json"
        existing = {"model": "gpt-4o", "small_model": "gpt-4o-mini", "theme": "dark"}
        config_path.write_text(json.dumps(existing), encoding="utf-8")

        write_config(
            config_path,
            provider_id="azure-cognitive-services",
            resource_name="my-resource",
            whitelist=["gpt-4o"],
            disabled_providers=["azure"],
        )

        result = json.loads(config_path.read_text(encoding="utf-8"))
        assert result["model"] == "gpt-4o", "existing 'model' key must survive"
        assert result["small_model"] == "gpt-4o-mini"
        assert result["theme"] == "dark"
        assert "azure-cognitive-services" in result.get("providers", {})
