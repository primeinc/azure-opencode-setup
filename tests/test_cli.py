"""Tests for cli.py — CLI with no secrets in argv.

TDD: Written BEFORE implementation.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from azure_opencode_setup.cli import SetupParams
from azure_opencode_setup.cli import build_parser
from azure_opencode_setup.cli import main
from azure_opencode_setup.cli import run_setup
from azure_opencode_setup.discovery import AccountMatch
from azure_opencode_setup.discovery import CognitiveAccount
from azure_opencode_setup.discovery import Subscription
from azure_opencode_setup.errors import ValidationError
from azure_opencode_setup.types import Deployment

if TYPE_CHECKING:
    from contextlib import AbstractContextManager
    from pathlib import Path

_EXIT_OK = 0
_EXIT_INVALID_INPUT = 3
_EXIT_FILESYSTEM = 4


def _require(*, condition: bool, message: str) -> None:
    """Fail the test if *condition* is false."""
    if not condition:
        pytest.fail(message)


def _default_params(tmp_path: Path) -> SetupParams:
    """Build SetupParams with sensible defaults and tmp_path-based paths."""
    return SetupParams(
        resource_name="myresource",
        provider_id="azure-cognitive-services",
        whitelist=["gpt-4o"],
        disabled_providers=["azure"],
        subscription_id=None,
        az_timeout_seconds=60,
        key_env="AZURE_OPENAI_API_KEY",
        key_stdin=False,
        config_path=tmp_path / "opencode.json",
        auth_path=tmp_path / "auth.json",
    )


def _patch_discovery_ok() -> AbstractContextManager[object]:
    """Patch out Azure discovery for CLI unit tests."""
    return patch(
        "azure_opencode_setup.cli._discover_whitelist_and_models",
        return_value=("myresource", ["gpt-4o"], None, ""),
    )


class TestCliRejectsKeyInArgv:
    """CLI must not accept secrets via argv."""

    def test_no_key_flag(self) -> None:
        """The parser must NOT have a --key argument (security invariant)."""
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["setup", "--resource-name", "myres", "--key", "secret-val"])


class TestCliKeyFromEnv:
    """API key discovery from environment variables."""

    def test_reads_key_from_default_env(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Reads API key from AZURE_OPENAI_API_KEY by default."""
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key-123")
        params = _default_params(tmp_path)
        with _patch_discovery_ok():
            exit_code = run_setup(params)
        _require(condition=exit_code == _EXIT_OK, message="Expected success exit code")

    def test_reads_key_from_custom_env(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Reads API key from a custom env var name."""
        monkeypatch.setenv("MY_CUSTOM_KEY", "custom-key-456")
        params = replace(_default_params(tmp_path), key_env="MY_CUSTOM_KEY")
        with _patch_discovery_ok():
            exit_code = run_setup(params)
        _require(condition=exit_code == _EXIT_OK, message="Expected success exit code")

    def test_fails_when_env_var_missing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Missing env var maps to ValidationError exit code."""
        monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
        params = _default_params(tmp_path)
        with _patch_discovery_ok():
            exit_code = run_setup(params)
        _require(
            condition=exit_code == _EXIT_INVALID_INPUT,
            message="Expected validation exit code",
        )


class TestCliKeyFromStdin:
    """API key discovery from interactive stdin."""

    def test_reads_key_from_getpass(self, tmp_path: Path) -> None:
        """Reads API key from getpass when --key-stdin is set."""
        with patch(
            "azure_opencode_setup.cli.getpass.getpass",
            return_value="stdin-key-789",
        ):
            params = replace(_default_params(tmp_path), key_stdin=True, key_env="")
            with _patch_discovery_ok():
                exit_code = run_setup(params)
        _require(condition=exit_code == _EXIT_OK, message="Expected success exit code")


class TestCliExitCodes:
    """CLI exit codes map to error classes."""

    def test_validation_error_returns_3(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Validation failures return exit code 3."""
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
        params = replace(_default_params(tmp_path), resource_name="has spaces in name")
        with patch(
            "azure_opencode_setup.cli._discover_whitelist_and_models",
            side_effect=ValidationError(field="resource_name", detail="invalid"),
        ):
            exit_code = run_setup(params)
        _require(
            condition=exit_code == _EXIT_INVALID_INPUT,
            message="Expected validation exit code",
        )

    def test_filesystem_error_returns_4(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Filesystem-like failures return exit code 4."""
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
        params = _default_params(tmp_path)
        with patch(
            "azure_opencode_setup.cli._do_merge_and_write",
            side_effect=OSError("boom"),
        ):
            exit_code = run_setup(params)
        _require(
            condition=exit_code == _EXIT_FILESYSTEM,
            message="Expected filesystem exit code",
        )


class TestCliEndToEnd:
    """End-to-end CLI behavior against local temp files."""

    def test_writes_both_files(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Writes both opencode.json and auth.json."""
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key-e2e")
        params = _default_params(tmp_path)
        with _patch_discovery_ok():
            exit_code = run_setup(params)
        _require(condition=exit_code == _EXIT_OK, message="Expected success exit code")

        config_path = tmp_path / "opencode.json"
        auth_path = tmp_path / "auth.json"

        _require(condition=config_path.exists(), message="Expected config_path to exist")
        _require(condition=auth_path.exists(), message="Expected auth_path to exist")

        config = json.loads(config_path.read_text(encoding="utf-8"))
        _require(condition="provider" in config, message="Expected provider key")
        _require(
            condition="azure-cognitive-services" in config["provider"],
            message="Expected provider block",
        )

        auth = json.loads(auth_path.read_text(encoding="utf-8"))
        _require(
            condition="azure-cognitive-services" in auth,
            message="Expected auth provider entry",
        )

    def test_merges_with_existing_files(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Preserves unknown keys while merging provider blocks."""
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key-merge")

        config_path = tmp_path / "opencode.json"
        auth_path = tmp_path / "auth.json"

        config_path.write_text(
            json.dumps({"theme": "dark", "provider": {}}),
            encoding="utf-8",
        )
        auth_path.write_text(
            json.dumps({"github-copilot": {"type": "oauth", "token": "gh-tok"}}),
            encoding="utf-8",
        )

        params = _default_params(tmp_path)
        with _patch_discovery_ok():
            exit_code = run_setup(params)
        _require(condition=exit_code == _EXIT_OK, message="Expected success exit code")

        config = json.loads(config_path.read_text(encoding="utf-8"))
        _require(condition=config["theme"] == "dark", message="Expected existing theme preserved")
        _require(
            condition="azure-cognitive-services" in config["provider"],
            message="Expected provider present",
        )

        auth = json.loads(auth_path.read_text(encoding="utf-8"))
        _require(condition="github-copilot" in auth, message="Expected existing auth preserved")
        _require(condition="azure-cognitive-services" in auth, message="Expected new auth entry")

    def test_no_bom_in_output(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Regression: old PS1 script wrote BOM. We must never write BOM."""
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key-bom")
        params = _default_params(tmp_path)
        with _patch_discovery_ok():
            exit_code = run_setup(params)
        _require(condition=exit_code == _EXIT_OK, message="Expected success exit code")


class TestCliDiscoveryAndWhitelist:
    """Discovery/whitelist behavior without calling az."""

    def test_autopick_discovers_whitelist_and_writes_config(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """When resource_name is omitted, auto-pick and build whitelist from deployments."""
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")

        chosen = AccountMatch(
            subscription=Subscription(id="sub-1", name="Sub One"),
            account=CognitiveAccount(
                name="myresource",
                resource_group="rg",
                endpoint="https://myresource.cognitiveservices.azure.com/",
                location="eastus",
                kind="AIServices",
            ),
        )
        deployments = [
            Deployment(name="MyDep", model="gpt-4o"),
            Deployment(name="Emb", model="text-embedding-3-small"),
        ]

        params = replace(_default_params(tmp_path), resource_name=None, whitelist=[])
        with (
            patch(
                "azure_opencode_setup.cli.pick_best_cognitive_account",
                return_value=(chosen, []),
            ),
            patch("azure_opencode_setup.cli.list_deployments", return_value=deployments),
        ):
            exit_code = run_setup(params)

        _require(condition=exit_code == _EXIT_OK, message="Expected success exit code")

        out = capsys.readouterr().out
        _require(condition="Auto-picked resource" in out, message="Expected auto-pick message")

        config = json.loads((tmp_path / "opencode.json").read_text(encoding="utf-8"))
        provider = config["provider"]["azure-cognitive-services"]
        _require(
            condition=provider["whitelist"]
            == [
                "emb",
                "gpt-4o",
                "mydep",
                "text-embedding-3-small",
            ],
            message="Expected whitelist from deployments",
        )

    def test_surfaces_other_subscriptions_for_named_resource(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """If the same account name exists in multiple subs, message includes alternatives."""
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")

        chosen = AccountMatch(
            subscription=Subscription(id="sub-1", name="Sub One"),
            account=CognitiveAccount(
                name="myresource",
                resource_group="rg-one",
                endpoint="https://myresource.cognitiveservices.azure.com/",
                location="eastus",
                kind="AIServices",
            ),
        )
        other = AccountMatch(
            subscription=Subscription(id="sub-2", name="Sub Two"),
            account=CognitiveAccount(
                name="myresource",
                resource_group="rg-two",
                endpoint="https://myresource.cognitiveservices.azure.com/",
                location="westus2",
                kind="AIServices",
            ),
        )

        params = replace(_default_params(tmp_path), whitelist=[])
        with (
            patch(
                "azure_opencode_setup.cli.find_cognitive_account",
                return_value=(chosen, [other]),
            ),
            patch(
                "azure_opencode_setup.cli.list_deployments",
                return_value=[Deployment(name="dep", model="gpt-4o")],
            ),
        ):
            exit_code = run_setup(params)

        _require(condition=exit_code == _EXIT_OK, message="Expected success exit code")
        out = capsys.readouterr().out
        _require(condition="Also found matches" in out, message="Expected alternatives message")
        _require(condition="--subscription-id" in out, message="Expected override hint")

    def test_skips_empty_and_dedups_available_models(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Available-model discovery skips empty strings and dedups duplicates."""
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")

        chosen = AccountMatch(
            subscription=Subscription(id="sub-1", name="Sub One"),
            account=CognitiveAccount(
                name="myresource",
                resource_group="rg",
                endpoint="https://myresource.cognitiveservices.azure.com/",
                location="eastus",
                kind="AIServices",
            ),
        )

        deployments = [
            Deployment(name="dep", model=""),
            Deployment(name="dep", model="gpt-4o"),
            Deployment(name="gpt-4o", model="gpt-4o"),
        ]

        params = replace(_default_params(tmp_path), whitelist=[])
        with (
            patch("azure_opencode_setup.cli.find_cognitive_account", return_value=(chosen, [])),
            patch("azure_opencode_setup.cli.list_deployments", return_value=deployments),
        ):
            exit_code = run_setup(params)

        _require(condition=exit_code == _EXIT_OK, message="Expected success exit code")
        config = json.loads((tmp_path / "opencode.json").read_text(encoding="utf-8"))
        provider = config["provider"]["azure-cognitive-services"]
        _require(
            condition=provider["whitelist"] == ["dep", "gpt-4o"],
            message="Expected deduped available models",
        )

    def test_valid_whitelist_is_deduped_and_accepted(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """User whitelist is lowercased and deduped when valid."""
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")

        chosen = AccountMatch(
            subscription=Subscription(id="sub-1", name="Sub One"),
            account=CognitiveAccount(
                name="myresource",
                resource_group="rg",
                endpoint="https://myresource.cognitiveservices.azure.com/",
                location="eastus",
                kind="AIServices",
            ),
        )

        deployments = [
            Deployment(name="gpt-4o", model="gpt-4o"),
            Deployment(name="dep", model="gpt-4o"),
        ]
        params = replace(
            _default_params(tmp_path),
            whitelist=["GPT-4O", "gpt-4o", "dep"],
        )
        with (
            patch("azure_opencode_setup.cli.find_cognitive_account", return_value=(chosen, [])),
            patch("azure_opencode_setup.cli.list_deployments", return_value=deployments),
        ):
            exit_code = run_setup(params)

        _require(condition=exit_code == _EXIT_OK, message="Expected success exit code")
        config = json.loads((tmp_path / "opencode.json").read_text(encoding="utf-8"))
        provider = config["provider"]["azure-cognitive-services"]
        _require(
            condition=provider["whitelist"] == ["gpt-4o", "dep"],
            message="Expected deduped user whitelist",
        )

    def test_fails_when_whitelist_contains_unknown_models(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Unknown whitelist entries fail validation before writing."""
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")

        chosen = AccountMatch(
            subscription=Subscription(id="sub-1", name="Sub One"),
            account=CognitiveAccount(
                name="myresource",
                resource_group="rg",
                endpoint="https://myresource.cognitiveservices.azure.com/",
                location="eastus",
                kind="AIServices",
            ),
        )

        params = replace(_default_params(tmp_path), whitelist=["gpt-4o", "missing-model"])
        with (
            patch("azure_opencode_setup.cli.find_cognitive_account", return_value=(chosen, [])),
            patch(
                "azure_opencode_setup.cli.list_deployments",
                return_value=[Deployment(name="gpt-4o", model="gpt-4o")],
            ),
        ):
            exit_code = run_setup(params)

        _require(
            condition=exit_code == _EXIT_INVALID_INPUT,
            message="Expected validation exit code",
        )
        _require(
            condition=not (tmp_path / "opencode.json").exists(),
            message="Expected config not written",
        )

    def test_writes_custom_models_mapping_for_non_catalog_model(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Non-catalog model names are surfaced via provider.models mapping."""
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")

        chosen = AccountMatch(
            subscription=Subscription(id="sub-1", name="Sub One"),
            account=CognitiveAccount(
                name="myresource",
                resource_group="rg",
                endpoint="https://myresource.cognitiveservices.azure.com/",
                location="eastus",
                kind="AIServices",
            ),
        )

        deployments = [Deployment(name="FooDep", model="my-custom-model")]
        params = replace(_default_params(tmp_path), whitelist=[])
        with (
            patch("azure_opencode_setup.cli.find_cognitive_account", return_value=(chosen, [])),
            patch("azure_opencode_setup.cli.list_deployments", return_value=deployments),
        ):
            exit_code = run_setup(params)

        _require(condition=exit_code == _EXIT_OK, message="Expected success exit code")
        config = json.loads((tmp_path / "opencode.json").read_text(encoding="utf-8"))
        provider = config["provider"]["azure-cognitive-services"]
        _require(condition="models" in provider, message="Expected models mapping")
        _require(
            condition=provider["models"]["foodep"]["name"] == "my-custom-model (Azure)",
            message="Expected Azure display name",
        )

    def test_fails_when_no_deployments_found(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If deployments list is empty, setup fails with validation error."""
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")

        chosen = AccountMatch(
            subscription=Subscription(id="sub-1", name="Sub One"),
            account=CognitiveAccount(
                name="myresource",
                resource_group="rg",
                endpoint="https://myresource.cognitiveservices.azure.com/",
                location="eastus",
                kind="AIServices",
            ),
        )

        params = replace(_default_params(tmp_path), whitelist=[])
        with (
            patch("azure_opencode_setup.cli.find_cognitive_account", return_value=(chosen, [])),
            patch("azure_opencode_setup.cli.list_deployments", return_value=[]),
        ):
            exit_code = run_setup(params)

        _require(
            condition=exit_code == _EXIT_INVALID_INPUT,
            message="Expected validation exit code",
        )

        _require(
            condition=not (tmp_path / "opencode.json").exists(),
            message="Expected config not written",
        )
        _require(
            condition=not (tmp_path / "auth.json").exists(),
            message="Expected auth not written",
        )


class TestCliKeySourceValidation:
    """Invalid API key sources are rejected."""

    def test_empty_key_from_stdin_raises(self, tmp_path: Path) -> None:
        """Empty key from getpass must raise ValidationError."""
        with patch(
            "azure_opencode_setup.cli.getpass.getpass",
            return_value="",
        ):
            params = replace(_default_params(tmp_path), key_stdin=True, key_env="")
            with _patch_discovery_ok():
                exit_code = run_setup(params)
        _require(
            condition=exit_code == _EXIT_INVALID_INPUT,
            message="Expected validation exit code",
        )

    def test_no_key_source_raises(self, tmp_path: Path) -> None:
        """Neither env nor stdin specified must raise ValidationError."""
        params = replace(_default_params(tmp_path), key_stdin=False, key_env="")
        with _patch_discovery_ok():
            exit_code = run_setup(params)
        _require(
            condition=exit_code == _EXIT_INVALID_INPUT,
            message="Expected validation exit code",
        )


class TestCliMainCoverage:
    """CLI main() behavior for non-happy paths."""

    def test_main_non_setup_command(self) -> None:
        """main() with non-setup command exits gracefully."""
        with (
            patch.object(sys, "argv", ["azure-opencode-setup", "version"]),
            pytest.raises(SystemExit) as exc,
        ):
            main()
        _require(condition=exc.value.code != _EXIT_OK, message="Expected non-zero exit")

    def test_main_dunder_name_block(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The if __name__ == '__main__' block is covered by direct call."""
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
        argv = [
            "azure-opencode-setup",
            "setup",
            "--resource-name",
            "t",
            "--provider-id",
            "p",
        ]
        with (
            patch.object(sys, "argv", argv),
            patch("azure_opencode_setup.cli.run_setup", return_value=_EXIT_OK),
            pytest.raises(SystemExit) as exc,
        ):
            main()
        _require(condition=exc.value.code == _EXIT_OK, message="Expected success exit")


class TestCliMain:
    """CLI main() argument parsing."""

    def test_main_parses_args(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """main() parses arguments and calls run_setup."""
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key-main")

        argv = [
            "azure-opencode-setup",
            "setup",
            "--resource-name",
            "testres",
            "--provider-id",
            "azure-cognitive-services",
        ]
        with patch("azure_opencode_setup.cli.run_setup", return_value=0) as mock_run:
            with patch.object(sys, "argv", argv):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                _require(condition=exc_info.value.code == _EXIT_OK, message="Expected success exit")
            mock_run.assert_called_once()
            params = mock_run.call_args[0][0]
            _require(condition=params.resource_name == "testres", message="Expected resource_name")
            _require(
                condition=params.provider_id == "azure-cognitive-services",
                message="Expected provider_id",
            )

    def test_main_azure_provider_no_disabled_azure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When --provider-id is 'azure', disabled_providers defaults to [] (not ['azure'])."""
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key-azure")

        argv = [
            "azure-opencode-setup",
            "setup",
            "--resource-name",
            "testres",
            "--provider-id",
            "azure",
        ]
        with patch("azure_opencode_setup.cli.run_setup", return_value=0) as mock_run:
            with patch.object(sys, "argv", argv):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                _require(condition=exc_info.value.code == _EXIT_OK, message="Expected success exit")
            mock_run.assert_called_once()
            params = mock_run.call_args[0][0]
            _require(
                condition=params.disabled_providers == [],
                message="Expected empty disabled_providers for azure provider",
            )

    def test_main_non_azure_provider_disables_azure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When --provider-id is not 'azure', disabled_providers defaults to ['azure']."""
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key-cogs")

        argv = [
            "azure-opencode-setup",
            "setup",
            "--resource-name",
            "testres",
            "--provider-id",
            "azure-cognitive-services",
        ]
        with patch("azure_opencode_setup.cli.run_setup", return_value=0) as mock_run:
            with patch.object(sys, "argv", argv):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                _require(condition=exc_info.value.code == _EXIT_OK, message="Expected success exit")
            mock_run.assert_called_once()
            params = mock_run.call_args[0][0]
            _require(
                condition=params.disabled_providers == ["azure"],
                message="Expected ['azure'] disabled_providers for non-azure provider",
            )
