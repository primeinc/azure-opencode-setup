"""Tests for discovery.py — az CLI wrapper for Azure resource discovery.

TDD: Written BEFORE implementation.
"""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from azure_opencode_setup.discovery import get_api_key
from azure_opencode_setup.discovery import list_cognitive_accounts
from azure_opencode_setup.discovery import list_deployments
from azure_opencode_setup.discovery import list_subscriptions
from azure_opencode_setup.errors import DiscoveryError
from azure_opencode_setup.errors import ValidationError
from azure_opencode_setup.types import CognitiveAccount
from azure_opencode_setup.types import Deployment


def _require(*, condition: bool, message: str) -> None:
    """Fail the test if *condition* is false."""
    if not condition:
        pytest.fail(message)


def _mock_subprocess_result(
    *,
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> MagicMock:
    """Create a mock subprocess.CompletedProcess result."""
    result = MagicMock(spec=subprocess.CompletedProcess)
    result.stdout = stdout
    result.stderr = stderr
    result.returncode = returncode
    return result


class TestListSubscriptions:
    """Behavior tests for list_subscriptions."""

    def test_returns_subscription_ids(self) -> None:
        """Returns list of subscription IDs from az CLI output."""
        mock_result = _mock_subprocess_result(
            stdout="sub-id-1\nsub-id-2\nsub-id-3\n",
            returncode=0,
        )
        with patch("azure_opencode_setup.discovery.subprocess.run", return_value=mock_result):
            result = list_subscriptions()
        _require(
            condition=result == ["sub-id-1", "sub-id-2", "sub-id-3"],
            message="Expected subscription IDs",
        )

    def test_returns_empty_list_when_no_subscriptions(self) -> None:
        """Returns empty list when no subscriptions found."""
        mock_result = _mock_subprocess_result(stdout="", returncode=0)
        with patch("azure_opencode_setup.discovery.subprocess.run", return_value=mock_result):
            result = list_subscriptions()
        _require(condition=result == [], message="Expected empty list")

    def test_raises_discovery_error_on_cli_not_found(self) -> None:
        """Raises DiscoveryError when az CLI is not found."""
        with (
            patch(
                "azure_opencode_setup.discovery.subprocess.run",
                side_effect=FileNotFoundError("az not found"),
            ),
            pytest.raises(DiscoveryError, match="az CLI not found"),
        ):
            list_subscriptions()

    def test_raises_discovery_error_on_nonzero_exit(self) -> None:
        """Raises DiscoveryError when az CLI returns non-zero exit code."""
        mock_result = _mock_subprocess_result(
            stdout="",
            stderr="some error",
            returncode=1,
        )
        with (
            patch("azure_opencode_setup.discovery.subprocess.run", return_value=mock_result),
            pytest.raises(DiscoveryError, match="az CLI command failed"),
        ):
            list_subscriptions()

    def test_handles_whitespace_in_output(self) -> None:
        """Handles extra whitespace and blank lines in output."""
        mock_result = _mock_subprocess_result(
            stdout="  sub-1  \n\n  sub-2  \n",
            returncode=0,
        )
        with patch("azure_opencode_setup.discovery.subprocess.run", return_value=mock_result):
            result = list_subscriptions()
        _require(condition=result == ["sub-1", "sub-2"], message="Expected trimmed IDs")

    def test_calls_correct_az_command(self) -> None:
        """Calls the correct az CLI command."""
        mock_result = _mock_subprocess_result(stdout="sub-1\n", returncode=0)
        with patch(
            "azure_opencode_setup.discovery.subprocess.run",
            return_value=mock_result,
        ) as mock_run:
            list_subscriptions()
            mock_run.assert_called_once()
            call_args = mock_run.call_args
            cmd = call_args[0][0]
            _require(condition=cmd[0] == "az", message="Expected az command")
            _require(condition="account" in cmd, message="Expected account subcommand")
            _require(condition="list" in cmd, message="Expected list subcommand")


class TestListCognitiveAccounts:
    """Behavior tests for list_cognitive_accounts."""

    def test_returns_cognitive_accounts(self) -> None:
        """Returns list of CognitiveAccount from az CLI output."""
        json_output = json.dumps(
            [
                {
                    "name": "my-ai-services",
                    "kind": "AIServices",
                    "endpoint": "https://my-ai.cognitiveservices.azure.com/",
                    "rg": "my-resource-group",
                    "location": "eastus",
                },
                {
                    "name": "my-openai",
                    "kind": "OpenAI",
                    "endpoint": "https://my-openai.openai.azure.com/",
                    "rg": "another-rg",
                    "location": "westus2",
                },
            ],
        )
        mock_result = _mock_subprocess_result(stdout=json_output, returncode=0)
        with patch("azure_opencode_setup.discovery.subprocess.run", return_value=mock_result):
            result = list_cognitive_accounts("valid-sub-id")

        _require(condition=len(result) == 2, message="Expected 2 accounts")  # noqa: PLR2004
        _require(condition=isinstance(result[0], CognitiveAccount), message="Expected dataclass")
        _require(condition=result[0].name == "my-ai-services", message="Expected name")
        _require(condition=result[0].kind == "AIServices", message="Expected kind")
        _require(condition=result[0].resource_group == "my-resource-group", message="Expected rg")
        _require(
            condition=result[0].endpoint == "https://my-ai.cognitiveservices.azure.com/",
            message="Expected endpoint",
        )
        _require(condition=result[0].location == "eastus", message="Expected location")

    def test_returns_empty_list_when_no_accounts(self) -> None:
        """Returns empty list when no cognitive accounts found."""
        mock_result = _mock_subprocess_result(stdout="[]", returncode=0)
        with patch("azure_opencode_setup.discovery.subprocess.run", return_value=mock_result):
            result = list_cognitive_accounts("valid-sub-id")
        _require(condition=result == [], message="Expected empty list")

    def test_raises_validation_error_on_invalid_subscription_id(self) -> None:
        """Raises ValidationError on invalid subscription ID."""
        with pytest.raises(ValidationError, match="subscription_id"):
            list_cognitive_accounts("invalid; rm -rf /")

    def test_raises_validation_error_on_empty_subscription_id(self) -> None:
        """Raises ValidationError on empty subscription ID."""
        with pytest.raises(ValidationError, match="subscription_id"):
            list_cognitive_accounts("")

    def test_raises_discovery_error_on_cli_not_found(self) -> None:
        """Raises DiscoveryError when az CLI is not found."""
        with (
            patch(
                "azure_opencode_setup.discovery.subprocess.run",
                side_effect=FileNotFoundError("az not found"),
            ),
            pytest.raises(DiscoveryError, match="az CLI not found"),
        ):
            list_cognitive_accounts("valid-sub-id")

    def test_raises_discovery_error_on_nonzero_exit(self) -> None:
        """Raises DiscoveryError when az CLI returns non-zero exit code."""
        mock_result = _mock_subprocess_result(
            stdout="",
            stderr="some error",
            returncode=1,
        )
        with (
            patch("azure_opencode_setup.discovery.subprocess.run", return_value=mock_result),
            pytest.raises(DiscoveryError, match="az CLI command failed"),
        ):
            list_cognitive_accounts("valid-sub-id")

    def test_raises_discovery_error_on_malformed_json(self) -> None:
        """Raises DiscoveryError when az CLI returns malformed JSON."""
        mock_result = _mock_subprocess_result(stdout="not valid json", returncode=0)
        with (
            patch("azure_opencode_setup.discovery.subprocess.run", return_value=mock_result),
            pytest.raises(DiscoveryError, match="Failed to parse"),
        ):
            list_cognitive_accounts("valid-sub-id")

    def test_raises_discovery_error_on_unexpected_json_shape(self) -> None:
        """Raises DiscoveryError when JSON is not a list."""
        mock_result = _mock_subprocess_result(stdout='{"not": "a list"}', returncode=0)
        with (
            patch("azure_opencode_setup.discovery.subprocess.run", return_value=mock_result),
            pytest.raises(DiscoveryError, match="Unexpected response format"),
        ):
            list_cognitive_accounts("valid-sub-id")

    def test_calls_correct_az_command(self) -> None:
        """Calls the correct az CLI command with subscription."""
        mock_result = _mock_subprocess_result(stdout="[]", returncode=0)
        with patch(
            "azure_opencode_setup.discovery.subprocess.run",
            return_value=mock_result,
        ) as mock_run:
            list_cognitive_accounts("my-subscription-123")
            mock_run.assert_called_once()
            call_args = mock_run.call_args
            cmd = call_args[0][0]
            _require(condition="cognitiveservices" in cmd, message="Expected cognitiveservices")
            _require(condition="account" in cmd, message="Expected account")
            _require(condition="list" in cmd, message="Expected list")
            _require(
                condition="--subscription" in cmd or any("my-subscription-123" in c for c in cmd),
                message="Expected subscription parameter",
            )


class TestListDeployments:
    """Behavior tests for list_deployments."""

    def test_returns_deployments(self) -> None:
        """Returns list of Deployment from az CLI output."""
        json_output = json.dumps(
            [
                {"name": "gpt-4o-deployment", "model": "gpt-4o"},
                {"name": "gpt-35-turbo", "model": "gpt-35-turbo"},
            ],
        )
        mock_result = _mock_subprocess_result(stdout=json_output, returncode=0)
        with patch("azure_opencode_setup.discovery.subprocess.run", return_value=mock_result):
            result = list_deployments("my-rg", "my-account")

        _require(condition=len(result) == 2, message="Expected 2 deployments")  # noqa: PLR2004
        _require(condition=isinstance(result[0], Deployment), message="Expected dataclass")
        _require(condition=result[0].name == "gpt-4o-deployment", message="Expected name")
        _require(condition=result[0].model == "gpt-4o", message="Expected model")

    def test_returns_empty_list_when_no_deployments(self) -> None:
        """Returns empty list when no deployments found."""
        mock_result = _mock_subprocess_result(stdout="[]", returncode=0)
        with patch("azure_opencode_setup.discovery.subprocess.run", return_value=mock_result):
            result = list_deployments("my-rg", "my-account")
        _require(condition=result == [], message="Expected empty list")

    def test_raises_validation_error_on_invalid_resource_group(self) -> None:
        """Raises ValidationError on invalid resource group name."""
        with pytest.raises(ValidationError, match="resource_group"):
            list_deployments("invalid; drop table", "my-account")

    def test_raises_validation_error_on_invalid_account_name(self) -> None:
        """Raises ValidationError on invalid account name."""
        with pytest.raises(ValidationError, match="account_name"):
            list_deployments("my-rg", "invalid$(whoami)")

    def test_raises_validation_error_on_empty_resource_group(self) -> None:
        """Raises ValidationError on empty resource group."""
        with pytest.raises(ValidationError, match="resource_group"):
            list_deployments("", "my-account")

    def test_raises_validation_error_on_empty_account_name(self) -> None:
        """Raises ValidationError on empty account name."""
        with pytest.raises(ValidationError, match="account_name"):
            list_deployments("my-rg", "")

    def test_raises_discovery_error_on_cli_not_found(self) -> None:
        """Raises DiscoveryError when az CLI is not found."""
        with (
            patch(
                "azure_opencode_setup.discovery.subprocess.run",
                side_effect=FileNotFoundError("az not found"),
            ),
            pytest.raises(DiscoveryError, match="az CLI not found"),
        ):
            list_deployments("my-rg", "my-account")

    def test_raises_discovery_error_on_nonzero_exit(self) -> None:
        """Raises DiscoveryError when az CLI returns non-zero exit code."""
        mock_result = _mock_subprocess_result(
            stdout="",
            stderr="some error",
            returncode=1,
        )
        with (
            patch("azure_opencode_setup.discovery.subprocess.run", return_value=mock_result),
            pytest.raises(DiscoveryError, match="az CLI command failed"),
        ):
            list_deployments("my-rg", "my-account")

    def test_raises_discovery_error_on_malformed_json(self) -> None:
        """Raises DiscoveryError when az CLI returns malformed JSON."""
        mock_result = _mock_subprocess_result(stdout="{invalid", returncode=0)
        with (
            patch("azure_opencode_setup.discovery.subprocess.run", return_value=mock_result),
            pytest.raises(DiscoveryError, match="Failed to parse"),
        ):
            list_deployments("my-rg", "my-account")

    def test_raises_discovery_error_on_unexpected_json_shape(self) -> None:
        """Raises DiscoveryError when JSON is not a list."""
        mock_result = _mock_subprocess_result(stdout='"just a string"', returncode=0)
        with (
            patch("azure_opencode_setup.discovery.subprocess.run", return_value=mock_result),
            pytest.raises(DiscoveryError, match="Unexpected response format"),
        ):
            list_deployments("my-rg", "my-account")

    def test_calls_correct_az_command(self) -> None:
        """Calls the correct az CLI command with resource group and name."""
        mock_result = _mock_subprocess_result(stdout="[]", returncode=0)
        with patch(
            "azure_opencode_setup.discovery.subprocess.run",
            return_value=mock_result,
        ) as mock_run:
            list_deployments("test-rg", "test-account")
            mock_run.assert_called_once()
            call_args = mock_run.call_args
            cmd = call_args[0][0]
            _require(condition="deployment" in cmd, message="Expected deployment")
            _require(condition="list" in cmd, message="Expected list")
            _require(condition="-g" in cmd or "--resource-group" in cmd, message="Expected -g")
            _require(condition="-n" in cmd or "--name" in cmd, message="Expected -n")


class TestGetApiKey:
    """Behavior tests for get_api_key."""

    def test_returns_key1(self) -> None:
        """Returns key1 from az CLI output."""
        json_output = json.dumps({"key1": "secret-key-123", "key2": "backup-key-456"})
        mock_result = _mock_subprocess_result(stdout=json_output, returncode=0)
        with patch("azure_opencode_setup.discovery.subprocess.run", return_value=mock_result):
            result = get_api_key("my-rg", "my-account")
        _require(condition=result == "secret-key-123", message="Expected key1 value")

    def test_raises_validation_error_on_invalid_resource_group(self) -> None:
        """Raises ValidationError on invalid resource group name."""
        with pytest.raises(ValidationError, match="resource_group"):
            get_api_key("invalid; rm -rf", "my-account")

    def test_raises_validation_error_on_invalid_account_name(self) -> None:
        """Raises ValidationError on invalid account name."""
        with pytest.raises(ValidationError, match="account_name"):
            get_api_key("my-rg", "invalid`id`")

    def test_raises_validation_error_on_empty_resource_group(self) -> None:
        """Raises ValidationError on empty resource group."""
        with pytest.raises(ValidationError, match="resource_group"):
            get_api_key("", "my-account")

    def test_raises_validation_error_on_empty_account_name(self) -> None:
        """Raises ValidationError on empty account name."""
        with pytest.raises(ValidationError, match="account_name"):
            get_api_key("my-rg", "")

    def test_raises_discovery_error_on_cli_not_found(self) -> None:
        """Raises DiscoveryError when az CLI is not found."""
        with (
            patch(
                "azure_opencode_setup.discovery.subprocess.run",
                side_effect=FileNotFoundError("az not found"),
            ),
            pytest.raises(DiscoveryError, match="az CLI not found"),
        ):
            get_api_key("my-rg", "my-account")

    def test_raises_discovery_error_on_nonzero_exit(self) -> None:
        """Raises DiscoveryError when az CLI returns non-zero exit code."""
        mock_result = _mock_subprocess_result(
            stdout="",
            stderr="some error",
            returncode=1,
        )
        with (
            patch("azure_opencode_setup.discovery.subprocess.run", return_value=mock_result),
            pytest.raises(DiscoveryError, match="az CLI command failed"),
        ):
            get_api_key("my-rg", "my-account")

    def test_raises_discovery_error_on_malformed_json(self) -> None:
        """Raises DiscoveryError when az CLI returns malformed JSON."""
        mock_result = _mock_subprocess_result(stdout="not json", returncode=0)
        with (
            patch("azure_opencode_setup.discovery.subprocess.run", return_value=mock_result),
            pytest.raises(DiscoveryError, match="Failed to parse"),
        ):
            get_api_key("my-rg", "my-account")

    def test_raises_discovery_error_on_missing_key1(self) -> None:
        """Raises DiscoveryError when key1 is missing from response."""
        json_output = json.dumps({"key2": "only-backup"})
        mock_result = _mock_subprocess_result(stdout=json_output, returncode=0)
        with (
            patch("azure_opencode_setup.discovery.subprocess.run", return_value=mock_result),
            pytest.raises(DiscoveryError, match="key1 not found"),
        ):
            get_api_key("my-rg", "my-account")

    def test_raises_discovery_error_on_unexpected_json_shape(self) -> None:
        """Raises DiscoveryError when JSON is not an object."""
        mock_result = _mock_subprocess_result(stdout="[]", returncode=0)
        with (
            patch("azure_opencode_setup.discovery.subprocess.run", return_value=mock_result),
            pytest.raises(DiscoveryError, match="Unexpected response format"),
        ):
            get_api_key("my-rg", "my-account")

    def test_error_message_does_not_contain_key(self) -> None:
        """DiscoveryError message must not leak API keys."""
        mock_result = _mock_subprocess_result(
            stdout='{"key1": "SUPER_SECRET_KEY", "key2": "ALSO_SECRET"}',
            stderr="SUPER_SECRET_KEY",  # Simulating key in stderr
            returncode=1,
        )
        with (
            patch("azure_opencode_setup.discovery.subprocess.run", return_value=mock_result),
            pytest.raises(DiscoveryError) as exc_info,
        ):
            get_api_key("my-rg", "my-account")
        error_message = str(exc_info.value)
        _require(
            condition="SUPER_SECRET_KEY" not in error_message,
            message="API key leaked in error message",
        )
        _require(
            condition="ALSO_SECRET" not in error_message,
            message="API key leaked in error message",
        )

    def test_calls_correct_az_command(self) -> None:
        """Calls the correct az CLI command for keys."""
        json_output = json.dumps({"key1": "key", "key2": "key2"})
        mock_result = _mock_subprocess_result(stdout=json_output, returncode=0)
        with patch(
            "azure_opencode_setup.discovery.subprocess.run",
            return_value=mock_result,
        ) as mock_run:
            get_api_key("test-rg", "test-account")
            mock_run.assert_called_once()
            call_args = mock_run.call_args
            cmd = call_args[0][0]
            _require(condition="keys" in cmd, message="Expected keys")
            _require(condition="list" in cmd, message="Expected list")


class TestInputValidation:
    """Security tests for input validation."""

    @pytest.mark.parametrize(
        "invalid_input",
        [
            "name; rm -rf /",
            "name && whoami",
            "name | cat /etc/passwd",
            "name$(id)",
            "name`id`",
            "name\necho pwned",
            "name\recho pwned",
            "../../../etc/passwd",
            "name with spaces",
            "name\twith\ttabs",
        ],
    )
    def test_list_cognitive_accounts_rejects_injection(self, invalid_input: str) -> None:
        """list_cognitive_accounts rejects command injection attempts."""
        with pytest.raises(ValidationError):
            list_cognitive_accounts(invalid_input)

    @pytest.mark.parametrize(
        "invalid_input",
        [
            "name; rm -rf /",
            "name && whoami",
            "name | cat /etc/passwd",
            "name$(id)",
            "name`id`",
            "name\necho pwned",
            "../../../etc/passwd",
        ],
    )
    def test_list_deployments_rejects_injection(self, invalid_input: str) -> None:
        """list_deployments rejects command injection attempts."""
        with pytest.raises(ValidationError):
            list_deployments(invalid_input, "valid-name")
        with pytest.raises(ValidationError):
            list_deployments("valid-name", invalid_input)

    @pytest.mark.parametrize(
        "invalid_input",
        [
            "name; rm -rf /",
            "name && whoami",
            "name$(id)",
            "name`id`",
        ],
    )
    def test_get_api_key_rejects_injection(self, invalid_input: str) -> None:
        """get_api_key rejects command injection attempts."""
        with pytest.raises(ValidationError):
            get_api_key(invalid_input, "valid-name")
        with pytest.raises(ValidationError):
            get_api_key("valid-name", invalid_input)

    @pytest.mark.parametrize(
        "valid_input",
        [
            "my-resource-group",
            "myResourceGroup123",
            "my_resource_group",
            "rg-123",
            "RG_TEST",
            "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        ],
    )
    def test_accepts_valid_azure_names(self, valid_input: str) -> None:
        """Functions accept valid Azure resource names."""
        mock_result = _mock_subprocess_result(stdout="[]", returncode=0)
        with patch("azure_opencode_setup.discovery.subprocess.run", return_value=mock_result):
            # Should not raise ValidationError
            list_cognitive_accounts(valid_input)
            list_deployments(valid_input, valid_input)

        json_output = json.dumps({"key1": "test", "key2": "test2"})
        mock_result_keys = _mock_subprocess_result(stdout=json_output, returncode=0)
        with patch(
            "azure_opencode_setup.discovery.subprocess.run",
            return_value=mock_result_keys,
        ):
            get_api_key(valid_input, valid_input)


class TestSubprocessSecurity:
    """Security tests for subprocess handling."""

    def test_no_shell_true_in_list_subscriptions(self) -> None:
        """list_subscriptions must not use shell=True."""
        mock_result = _mock_subprocess_result(stdout="sub-1\n", returncode=0)
        with patch(
            "azure_opencode_setup.discovery.subprocess.run",
            return_value=mock_result,
        ) as mock_run:
            list_subscriptions()
            call_kwargs = mock_run.call_args[1]
            _require(
                condition=call_kwargs.get("shell") is not True,
                message="shell=True is forbidden",
            )

    def test_no_shell_true_in_list_cognitive_accounts(self) -> None:
        """list_cognitive_accounts must not use shell=True."""
        mock_result = _mock_subprocess_result(stdout="[]", returncode=0)
        with patch(
            "azure_opencode_setup.discovery.subprocess.run",
            return_value=mock_result,
        ) as mock_run:
            list_cognitive_accounts("valid-sub")
            call_kwargs = mock_run.call_args[1]
            _require(
                condition=call_kwargs.get("shell") is not True,
                message="shell=True is forbidden",
            )

    def test_no_shell_true_in_list_deployments(self) -> None:
        """list_deployments must not use shell=True."""
        mock_result = _mock_subprocess_result(stdout="[]", returncode=0)
        with patch(
            "azure_opencode_setup.discovery.subprocess.run",
            return_value=mock_result,
        ) as mock_run:
            list_deployments("valid-rg", "valid-name")
            call_kwargs = mock_run.call_args[1]
            _require(
                condition=call_kwargs.get("shell") is not True,
                message="shell=True is forbidden",
            )

    def test_no_shell_true_in_get_api_key(self) -> None:
        """get_api_key must not use shell=True."""
        json_output = json.dumps({"key1": "test", "key2": "test2"})
        mock_result = _mock_subprocess_result(stdout=json_output, returncode=0)
        with patch(
            "azure_opencode_setup.discovery.subprocess.run",
            return_value=mock_result,
        ) as mock_run:
            get_api_key("valid-rg", "valid-name")
            call_kwargs = mock_run.call_args[1]
            _require(
                condition=call_kwargs.get("shell") is not True,
                message="shell=True is forbidden",
            )


class TestDataClasses:
    """Tests for data class behavior."""

    def test_cognitive_account_is_frozen(self) -> None:
        """CognitiveAccount instances are immutable."""
        account = CognitiveAccount(
            name="test",
            resource_group="rg",
            endpoint="https://test.azure.com",
            location="eastus",
            kind="AIServices",
        )
        with pytest.raises(AttributeError):
            account.name = "changed"  # type: ignore[misc]

    def test_deployment_is_frozen(self) -> None:
        """Deployment instances are immutable."""
        deployment = Deployment(name="test", model="gpt-4o")
        with pytest.raises(AttributeError):
            deployment.name = "changed"  # type: ignore[misc]

    def test_cognitive_account_equality(self) -> None:
        """CognitiveAccount supports equality comparison."""
        account1 = CognitiveAccount(
            name="test",
            resource_group="rg",
            endpoint="https://test.azure.com",
            location="eastus",
            kind="AIServices",
        )
        account2 = CognitiveAccount(
            name="test",
            resource_group="rg",
            endpoint="https://test.azure.com",
            location="eastus",
            kind="AIServices",
        )
        _require(condition=account1 == account2, message="Expected equality")

    def test_deployment_equality(self) -> None:
        """Deployment supports equality comparison."""
        dep1 = Deployment(name="test", model="gpt-4o")
        dep2 = Deployment(name="test", model="gpt-4o")
        _require(condition=dep1 == dep2, message="Expected equality")
