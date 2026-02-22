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

if TYPE_CHECKING:
    from pathlib import Path

_EXIT_OK = 0
_EXIT_INVALID_INPUT = 3
_MIN_BACKUPS = 2


def _require(condition: bool, message: str) -> None:
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
        key_env="AZURE_OPENAI_API_KEY",
        key_stdin=False,
        config_path=tmp_path / "opencode.json",
        auth_path=tmp_path / "auth.json",
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
        exit_code = run_setup(params)
        _require(exit_code == _EXIT_OK, "Expected success exit code")

    def test_reads_key_from_custom_env(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Reads API key from a custom env var name."""
        monkeypatch.setenv("MY_CUSTOM_KEY", "custom-key-456")
        params = replace(_default_params(tmp_path), key_env="MY_CUSTOM_KEY")
        exit_code = run_setup(params)
        _require(exit_code == _EXIT_OK, "Expected success exit code")

    def test_fails_when_env_var_missing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Missing env var maps to ValidationError exit code."""
        monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
        params = _default_params(tmp_path)
        exit_code = run_setup(params)
        _require(exit_code == _EXIT_INVALID_INPUT, "Expected validation exit code")


class TestCliKeyFromStdin:
    """API key discovery from interactive stdin."""

    def test_reads_key_from_getpass(self, tmp_path: Path) -> None:
        """Reads API key from getpass when --key-stdin is set."""
        with patch(
            "azure_opencode_setup.cli.getpass.getpass",
            return_value="stdin-key-789",
        ):
            params = replace(_default_params(tmp_path), key_stdin=True, key_env="")
            exit_code = run_setup(params)
        _require(exit_code == _EXIT_OK, "Expected success exit code")


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
        exit_code = run_setup(params)
        _require(exit_code == _EXIT_INVALID_INPUT, "Expected validation exit code")


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
        exit_code = run_setup(params)
        _require(exit_code == _EXIT_OK, "Expected success exit code")

        config_path = tmp_path / "opencode.json"
        auth_path = tmp_path / "auth.json"

        _require(config_path.exists(), "Expected config_path to exist")
        _require(auth_path.exists(), "Expected auth_path to exist")

        config = json.loads(config_path.read_text(encoding="utf-8"))
        _require("provider" in config, "Expected provider key")
        _require(
            "azure-cognitive-services" in config["provider"],
            "Expected provider block",
        )

        auth = json.loads(auth_path.read_text(encoding="utf-8"))
        _require("azure-cognitive-services" in auth, "Expected auth provider entry")

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
        exit_code = run_setup(params)
        _require(exit_code == _EXIT_OK, "Expected success exit code")

        config = json.loads(config_path.read_text(encoding="utf-8"))
        _require(config["theme"] == "dark", "Expected existing theme preserved")
        _require(
            "azure-cognitive-services" in config["provider"],
            "Expected provider present",
        )

        auth = json.loads(auth_path.read_text(encoding="utf-8"))
        _require("github-copilot" in auth, "Expected existing auth preserved")
        _require("azure-cognitive-services" in auth, "Expected new auth entry")

    def test_creates_backup_of_existing_files(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Existing files are backed up before overwrite."""
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key-backup")

        config_path = tmp_path / "opencode.json"
        auth_path = tmp_path / "auth.json"

        config_path.write_text("{}", encoding="utf-8")
        auth_path.write_text("{}", encoding="utf-8")

        params = _default_params(tmp_path)
        exit_code = run_setup(params)
        _require(exit_code == _EXIT_OK, "Expected success exit code")

        bak_files = list(tmp_path.glob("*.bak"))
        _require(len(bak_files) >= _MIN_BACKUPS, "Expected backups")

    def test_no_bom_in_output(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Regression: old PS1 script wrote BOM. We must never write BOM."""
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key-bom")
        params = _default_params(tmp_path)
        exit_code = run_setup(params)
        _require(exit_code == _EXIT_OK, "Expected success exit code")

        for name in ("opencode.json", "auth.json"):
            raw = (tmp_path / name).read_bytes()
            _require(raw[:3] != b"\xef\xbb\xbf", "BOM must not be written")


class TestCliKeySourceValidation:
    """Invalid API key sources are rejected."""

    def test_empty_key_from_stdin_raises(self, tmp_path: Path) -> None:
        """Empty key from getpass must raise ValidationError."""
        with patch(
            "azure_opencode_setup.cli.getpass.getpass",
            return_value="",
        ):
            params = replace(_default_params(tmp_path), key_stdin=True, key_env="")
            exit_code = run_setup(params)
        _require(exit_code == _EXIT_INVALID_INPUT, "Expected validation exit code")

    def test_no_key_source_raises(self, tmp_path: Path) -> None:
        """Neither env nor stdin specified must raise ValidationError."""
        params = replace(_default_params(tmp_path), key_stdin=False, key_env="")
        exit_code = run_setup(params)
        _require(exit_code == _EXIT_INVALID_INPUT, "Expected validation exit code")


class TestCliMainCoverage:
    """CLI main() behavior for non-happy paths."""

    def test_main_non_setup_command(self) -> None:
        """main() with non-setup command exits gracefully."""
        with (
            patch.object(sys, "argv", ["azure-opencode-setup", "version"]),
            pytest.raises(SystemExit) as exc,
        ):
            main()
        _require(exc.value.code != _EXIT_OK, "Expected non-zero exit")

    def test_main_dunder_name_block(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The if __name__ == '__main__' block is covered by direct call."""
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
        argv = [
            "azure-opencode-setup", "setup",
            "--resource-name", "t", "--provider-id", "p",
        ]
        with (
            patch.object(sys, "argv", argv),
            patch("azure_opencode_setup.cli.run_setup", return_value=_EXIT_OK),
            pytest.raises(SystemExit) as exc,
        ):
            main()
        _require(exc.value.code == _EXIT_OK, "Expected success exit")


class TestCliMain:
    """CLI main() argument parsing."""

    def test_main_parses_args(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """main() parses arguments and calls run_setup."""
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key-main")

        argv = [
            "azure-opencode-setup", "setup",
            "--resource-name", "testres",
            "--provider-id", "azure-cognitive-services",
        ]
        with patch("azure_opencode_setup.cli.run_setup", return_value=0) as mock_run:
            with patch.object(sys, "argv", argv):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                _require(exc_info.value.code == _EXIT_OK, "Expected success exit")
            mock_run.assert_called_once()
            params = mock_run.call_args[0][0]
            _require(params.resource_name == "testres", "Expected resource_name")
            _require(params.provider_id == "azure-cognitive-services", "Expected provider_id")
