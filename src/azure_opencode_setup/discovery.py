"""Azure resource discovery via az CLI.

Wraps az CLI commands to discover Cognitive Services resources, deployments,
and API keys. All inputs are validated to prevent command injection.
"""

from __future__ import annotations

import json
import re
import subprocess
from typing import Any
from typing import cast

from azure_opencode_setup.errors import DiscoveryError
from azure_opencode_setup.errors import ValidationError
from azure_opencode_setup.types import CognitiveAccount
from azure_opencode_setup.types import Deployment

# Pattern for valid Azure resource names: alphanumeric, hyphens, underscores
# This is intentionally restrictive to prevent command injection
_VALID_AZURE_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


def _validate_azure_name(value: str, field: str) -> None:
    """Validate that a value is a safe Azure resource name.

    Args:
        value (str): The value to validate.
        field (str): Field name for error messages.

    Raises:
        ValidationError: If the value is empty or contains invalid characters.
    """
    if not value:
        raise ValidationError(field=field, detail="cannot be empty")
    if not _VALID_AZURE_NAME_PATTERN.match(value):
        raise ValidationError(
            field=field,
            detail="must contain only alphanumeric characters, hyphens, and underscores",
        )


def _run_az_command(args: list[str]) -> str:
    """Execute an az CLI command and return stdout.

    Args:
        args (list[str]): Command arguments (without 'az' prefix).

    Returns:
        str: The command's stdout.

    Raises:
        DiscoveryError: If az CLI is not found or command fails.
    """
    cmd = ["az", *args]
    try:
        result = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise DiscoveryError(detail="az CLI not found. Please install Azure CLI.") from exc

    if result.returncode != 0:
        # Sanitize error message - don't include raw stderr which could contain secrets
        raise DiscoveryError(detail="az CLI command failed. Run 'az login' and try again.")

    return result.stdout


def _parse_json_list(output: str) -> list[dict[str, Any]]:
    """Parse JSON output expecting a list of objects.

    Args:
        output (str): JSON string to parse.

    Returns:
        list[dict[str, Any]]: Parsed list of dictionaries.

    Raises:
        DiscoveryError: If JSON is invalid or not a list.
    """
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError as exc:
        raise DiscoveryError(detail="Failed to parse az CLI output as JSON.") from exc

    if not isinstance(parsed, list):
        raise DiscoveryError(detail="Unexpected response format: expected a list.")

    return cast("list[dict[str, Any]]", parsed)


def _parse_json_object(output: str) -> dict[str, Any]:
    """Parse JSON output expecting an object.

    Args:
        output (str): JSON string to parse.

    Returns:
        dict[str, Any]: Parsed dictionary.

    Raises:
        DiscoveryError: If JSON is invalid or not an object.
    """
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError as exc:
        raise DiscoveryError(detail="Failed to parse az CLI output as JSON.") from exc

    if not isinstance(parsed, dict):
        raise DiscoveryError(detail="Unexpected response format: expected an object.")

    return cast("dict[str, Any]", parsed)


def list_subscriptions() -> list[str]:
    """List all Azure subscription IDs accessible to the current user.

    Returns:
        list[str]: List of subscription ID strings.

    Raises:
        DiscoveryError: If az CLI is not found or command fails.
    """
    output = _run_az_command(
        [
            "account",
            "list",
            "--query",
            "[].id",
            "-o",
            "tsv",
        ],
    )

    # Parse TSV output, filtering empty lines and stripping whitespace
    return [line.strip() for line in output.strip().split("\n") if line.strip()]


def list_cognitive_accounts(subscription_id: str) -> list[CognitiveAccount]:
    """List Cognitive Services accounts (AIServices or OpenAI) in a subscription.

    Args:
        subscription_id (str): Azure subscription ID.

    Returns:
        list[CognitiveAccount]: List of discovered accounts.

    Raises:
        ValidationError: If subscription_id contains invalid characters.
        DiscoveryError: If az CLI is not found, command fails, or output is malformed.
    """
    _validate_azure_name(subscription_id, "subscription_id")

    output = _run_az_command(
        [
            "cognitiveservices",
            "account",
            "list",
            "--subscription",
            subscription_id,
            "--query",
            "[?kind=='AIServices' || kind=='OpenAI']."
            "{name:name, kind:kind, endpoint:properties.endpoint, "
            "rg:resourceGroup, location:location}",
            "-o",
            "json",
        ],
    )

    items = _parse_json_list(output)

    return [
        CognitiveAccount(
            name=item["name"],
            resource_group=item["rg"],
            endpoint=item["endpoint"],
            location=item["location"],
            kind=item["kind"],
        )
        for item in items
    ]


def list_deployments(resource_group: str, account_name: str) -> list[Deployment]:
    """List model deployments for a Cognitive Services account.

    Args:
        resource_group (str): Azure resource group name.
        account_name (str): Cognitive Services account name.

    Returns:
        list[Deployment]: List of deployments with name and model.

    Raises:
        ValidationError: If resource_group or account_name contain invalid characters.
        DiscoveryError: If az CLI is not found, command fails, or output is malformed.
    """
    _validate_azure_name(resource_group, "resource_group")
    _validate_azure_name(account_name, "account_name")

    output = _run_az_command(
        [
            "cognitiveservices",
            "account",
            "deployment",
            "list",
            "-g",
            resource_group,
            "-n",
            account_name,
            "--query",
            "[].{name:name, model:properties.model.name}",
            "-o",
            "json",
        ],
    )

    items = _parse_json_list(output)

    return [Deployment(name=item["name"], model=item["model"]) for item in items]


def get_api_key(resource_group: str, account_name: str) -> str:
    """Get the primary API key for a Cognitive Services account.

    Args:
        resource_group (str): Azure resource group name.
        account_name (str): Cognitive Services account name.

    Returns:
        str: The primary API key (key1).

    Raises:
        ValidationError: If resource_group or account_name contain invalid characters.
        DiscoveryError: If az CLI is not found, command fails, output is malformed,
            or key1 is not present in the response.
    """
    _validate_azure_name(resource_group, "resource_group")
    _validate_azure_name(account_name, "account_name")

    output = _run_az_command(
        [
            "cognitiveservices",
            "account",
            "keys",
            "list",
            "-g",
            resource_group,
            "-n",
            account_name,
            "-o",
            "json",
        ],
    )

    keys = _parse_json_object(output)

    if "key1" not in keys:
        raise DiscoveryError(detail="key1 not found in response.")

    return str(keys["key1"])
