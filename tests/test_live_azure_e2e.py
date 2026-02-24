"""Optional live Azure e2e tests.

These are skipped by default. Enable with AZURE_LIVE_E2E=1 and provide the
required environment variables.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from typing import cast

import pytest

from azure_opencode_setup.cli import SetupParams
from azure_opencode_setup.cli import run_setup
from azure_opencode_setup.discovery import find_cognitive_account
from azure_opencode_setup.discovery import list_deployments
from azure_opencode_setup.io import read_json_object

if TYPE_CHECKING:
    from pathlib import Path


def _require(*, condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _live_enabled() -> bool:
    return os.environ.get("AZURE_LIVE_E2E") == "1"


@pytest.mark.skipif(not _live_enabled(), reason="Set AZURE_LIVE_E2E=1 to run live Azure tests")
def test_live_whitelist_matches_deployments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live: whitelist equals deployed Azure deployment names.

    This catches cases where we accidentally whitelist catalog model IDs that do not
    correspond to an actual Azure deployment.
    """
    resource = os.environ.get("AZURE_COGNITIVE_SERVICES_RESOURCE_NAME")
    if not resource:
        pytest.skip("AZURE_COGNITIVE_SERVICES_RESOURCE_NAME is not set")

    key = os.environ.get("AZURE_AI_KEY") or os.environ.get("AZURE_OPENAI_API_KEY")
    if not key:
        pytest.skip("AZURE_AI_KEY or AZURE_OPENAI_API_KEY must be set")

    monkeypatch.setenv("AZURE_OPENAI_API_KEY", key)

    timeout = int(os.environ.get("AZURE_AZ_TIMEOUT_SECONDS", "60"))

    chosen, _others = find_cognitive_account(resource, timeout_seconds=timeout)
    acct = chosen.account
    sub = chosen.subscription
    deployments = list_deployments(
        acct.resource_group,
        acct.name,
        subscription_id=sub.id,
        timeout_seconds=timeout,
    )
    if not deployments:
        pytest.skip("No deployments found")

    expected = sorted({d.name.lower() for d in deployments if d.name})

    config_path = tmp_path / "opencode.json"
    auth_path = tmp_path / "auth.json"
    config_path.write_text("{}", encoding="utf-8")
    auth_path.write_text("{}", encoding="utf-8")

    params = SetupParams(
        resource_name=resource,
        provider_id="azure-cognitive-services",
        whitelist=[],
        disabled_providers=["azure"],
        subscription_id=None,
        az_timeout_seconds=timeout,
        key_env="AZURE_OPENAI_API_KEY",
        key_stdin=False,
        config_path=config_path,
        auth_path=auth_path,
    )

    exit_code = run_setup(params)
    _require(condition=exit_code == 0, message="Expected exit code 0")

    config = read_json_object(config_path)
    provider_section = config.get("provider")
    _require(condition=isinstance(provider_section, dict), message="Expected provider object")
    provider_section_t = cast("dict[str, object]", provider_section)
    provider = provider_section_t.get("azure-cognitive-services")
    _require(condition=isinstance(provider, dict), message="Expected provider entry")
    provider_t = cast("dict[str, object]", provider)
    _require(condition=provider_t.get("whitelist") == expected, message="Whitelist mismatch")
