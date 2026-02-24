"""Azure resource discovery via az CLI.

Wraps az CLI commands to discover Cognitive Services resources, deployments,
and API keys. All inputs are validated to prevent command injection.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Any
from typing import cast

from azure_opencode_setup.errors import DiscoveryError
from azure_opencode_setup.errors import ValidationError
from azure_opencode_setup.types import CognitiveAccount
from azure_opencode_setup.types import Deployment

# Pattern for valid Azure resource names: alphanumeric, hyphens, underscores
# This is intentionally restrictive to prevent command injection
_VALID_AZURE_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

_DEFAULT_AZ_TIMEOUT_SECONDS = 60


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


def _run_az_command(
    args: list[str],
    *,
    timeout_seconds: int = _DEFAULT_AZ_TIMEOUT_SECONDS,
) -> str:
    """Execute an az CLI command and return stdout.

    Args:
        args (list[str]): Command arguments (without 'az' prefix).
        timeout_seconds (int): Timeout per az command in seconds.

    Returns:
        str: The command's stdout.

    Raises:
        DiscoveryError: If az CLI is not found or command fails.
    """
    if sys.platform == "win32":
        # On Windows, Azure CLI is typically an az.cmd shim which can't be executed
        # directly via CreateProcess; invoke it via cmd.exe.
        cmd = ["cmd.exe", "/c", "az", *args]
    else:
        cmd = ["az", *args]
    try:
        result = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise DiscoveryError(detail="az CLI command timed out.") from exc
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
        parsed: object = json.loads(output)
    except json.JSONDecodeError as exc:
        raise DiscoveryError(detail="Failed to parse az CLI output as JSON.") from exc

    if not isinstance(parsed, list):
        raise DiscoveryError(detail="Unexpected response format: expected a list.")

    for i, item in enumerate(cast("list[object]", parsed)):
        if not isinstance(item, dict):
            raise DiscoveryError(
                detail=f"Unexpected item at index {i}: expected object, got {type(item).__name__}.",
            )

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


@dataclass(frozen=True, slots=True)
class Subscription:
    """Azure subscription identifier and friendly name."""

    id: str
    name: str


@dataclass(frozen=True, slots=True)
class AccountMatch:
    """A CognitiveAccount found within a specific subscription."""

    subscription: Subscription
    account: CognitiveAccount


def pick_best_cognitive_account(
    *,
    subscription_id: str | None = None,
    timeout_seconds: int = _DEFAULT_AZ_TIMEOUT_SECONDS,
) -> tuple[AccountMatch, list[AccountMatch]]:
    """Pick the Cognitive Services account with the most deployments.

    This mirrors the repo's setup scripts: when the user does not specify a
    resource name, pick the account that appears most likely to be "active"
    (highest deployment count).

    Returns:
        tuple[AccountMatch, list[AccountMatch]]: Chosen match and other candidates.
    """
    subs: list[Subscription]
    if subscription_id is not None:
        _validate_azure_name(subscription_id, "subscription_id")
        subs = [Subscription(id=subscription_id, name=subscription_id)]
    else:
        subs = list_subscriptions_detailed(timeout_seconds=timeout_seconds)

    candidates: list[AccountMatch] = []
    for sub in subs:
        candidates.extend(
            AccountMatch(subscription=sub, account=acct)
            for acct in list_cognitive_accounts(sub.id, timeout_seconds=timeout_seconds)
        )

    if not candidates:
        raise DiscoveryError(
            detail="No Cognitive Services accounts found in accessible subscriptions.",
        )

    scored: list[tuple[int, AccountMatch]] = []
    for m in candidates:
        try:
            deployments: list[Deployment] = list_deployments(
                m.account.resource_group,
                m.account.name,
                subscription_id=m.subscription.id,
                timeout_seconds=timeout_seconds,
            )
        except DiscoveryError:
            deployments = []
        scored.append((len(deployments), m))

    scored.sort(key=lambda x: x[0], reverse=True)
    chosen = scored[0][1]
    others = [m for _count, m in scored[1:]]
    return chosen, others


def list_subscriptions(*, timeout_seconds: int = _DEFAULT_AZ_TIMEOUT_SECONDS) -> list[str]:
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
        timeout_seconds=timeout_seconds,
    )

    # Parse TSV output, filtering empty lines and stripping whitespace
    return [line.strip() for line in output.strip().split("\n") if line.strip()]


def list_subscriptions_detailed(
    *,
    timeout_seconds: int = _DEFAULT_AZ_TIMEOUT_SECONDS,
) -> list[Subscription]:
    """List all Azure subscriptions accessible to the current user.

    Returns both ID and friendly name to support user-facing selection.
    """
    output = _run_az_command(
        [
            "account",
            "list",
            "--query",
            "[].{id:id, name:name}",
            "-o",
            "json",
        ],
        timeout_seconds=timeout_seconds,
    )

    items = _parse_json_list(output)
    try:
        return [Subscription(id=str(i["id"]), name=str(i["name"])) for i in items]
    except KeyError as exc:
        raise DiscoveryError(detail=f"Malformed response: missing field {exc}") from exc


def _choose_by_deployment_count(
    matches: list[AccountMatch],
    *,
    timeout_seconds: int,
) -> tuple[AccountMatch, list[AccountMatch]]:
    scored: list[tuple[int, AccountMatch]] = []
    for m in matches:
        try:
            deployments: list[Deployment] = list_deployments(
                m.account.resource_group,
                m.account.name,
                subscription_id=m.subscription.id,
                timeout_seconds=timeout_seconds,
            )
        except DiscoveryError:
            deployments = []
        scored.append((len(deployments), m))

    scored.sort(key=lambda x: x[0], reverse=True)
    chosen = scored[0][1]
    others = [m for _count, m in scored[1:]]
    return chosen, others


def _matches_in_subscription(
    account_name: str,
    *,
    subscription: Subscription,
    timeout_seconds: int,
) -> list[AccountMatch]:
    output = _run_az_command(
        [
            "cognitiveservices",
            "account",
            "list",
            "--subscription",
            subscription.id,
            "--query",
            f"[?name=='{account_name}']."
            "{name:name, kind:kind, endpoint:properties.endpoint, "
            "rg:resourceGroup, location:location}",
            "-o",
            "json",
        ],
        timeout_seconds=timeout_seconds,
    )
    items = _parse_json_list(output)

    matches: list[AccountMatch] = []
    for item in items:
        try:
            acct = CognitiveAccount(
                name=item["name"],
                resource_group=item["rg"],
                endpoint=item["endpoint"],
                location=item["location"],
                kind=item["kind"],
            )
        except KeyError as exc:
            raise DiscoveryError(detail=f"Malformed response: missing field {exc}") from exc
        matches.append(AccountMatch(subscription=subscription, account=acct))

    return matches


def find_cognitive_account(
    account_name: str,
    *,
    subscription_id: str | None = None,
    timeout_seconds: int = _DEFAULT_AZ_TIMEOUT_SECONDS,
) -> tuple[AccountMatch, list[AccountMatch]]:
    """Find a Cognitive Services account by name across subscriptions.

    Args:
        account_name (str): Name of the Cognitive Services account.
        subscription_id (str | None): Optional subscription ID to scope discovery.
        timeout_seconds (int): Timeout per az command in seconds.

    Returns:
        tuple[AccountMatch, list[AccountMatch]]: The chosen match and any other matches.

    Raises:
        ValidationError: If inputs contain invalid characters.
        DiscoveryError: If az CLI fails or account is not found.
    """
    _validate_azure_name(account_name, "account_name")

    subs: list[Subscription]
    if subscription_id is not None:
        _validate_azure_name(subscription_id, "subscription_id")
        subs = [Subscription(id=subscription_id, name=subscription_id)]
    else:
        subs = list_subscriptions_detailed(timeout_seconds=timeout_seconds)

    matches: list[AccountMatch] = []
    for sub in subs:
        matches.extend(
            _matches_in_subscription(
                account_name,
                subscription=sub,
                timeout_seconds=timeout_seconds,
            ),
        )

    if not matches:
        raise DiscoveryError(
            detail=f"No Cognitive Services account found with name '{account_name}'",
        )

    if len(matches) == 1:
        return matches[0], []

    return _choose_by_deployment_count(matches, timeout_seconds=timeout_seconds)


def list_cognitive_accounts(
    subscription_id: str,
    *,
    timeout_seconds: int = _DEFAULT_AZ_TIMEOUT_SECONDS,
) -> list[CognitiveAccount]:
    """List Cognitive Services accounts (AIServices or OpenAI) in a subscription.

    Args:
        subscription_id (str): Azure subscription ID.
        timeout_seconds (int): Timeout per az command in seconds.

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
        timeout_seconds=timeout_seconds,
    )

    items = _parse_json_list(output)

    try:
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
    except KeyError as exc:
        raise DiscoveryError(detail=f"Malformed response: missing field {exc}") from exc


def list_deployments(
    resource_group: str,
    account_name: str,
    *,
    subscription_id: str | None = None,
    timeout_seconds: int = _DEFAULT_AZ_TIMEOUT_SECONDS,
) -> list[Deployment]:
    """List model deployments for a Cognitive Services account.

    Args:
        resource_group (str): Azure resource group name.
        account_name (str): Cognitive Services account name.
        subscription_id (str | None): Optional subscription ID for the account.
        timeout_seconds (int): Timeout per az command in seconds.

    Returns:
        list[Deployment]: List of deployments with name and model.

    Raises:
        ValidationError: If resource_group or account_name contain invalid characters.
        DiscoveryError: If az CLI is not found, command fails, or output is malformed.
    """
    _validate_azure_name(resource_group, "resource_group")
    _validate_azure_name(account_name, "account_name")

    args: list[str] = [
        "cognitiveservices",
        "account",
        "deployment",
        "list",
    ]
    if subscription_id is not None:
        _validate_azure_name(subscription_id, "subscription_id")
        args.extend(["--subscription", subscription_id])
    args.extend(
        [
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
    output = _run_az_command(args, timeout_seconds=timeout_seconds)

    items = _parse_json_list(output)

    try:
        return [Deployment(name=item["name"], model=item.get("model") or "") for item in items]
    except KeyError as exc:
        raise DiscoveryError(detail=f"Malformed response: missing field {exc}") from exc


def get_api_key(
    resource_group: str,
    account_name: str,
    *,
    subscription_id: str | None = None,
    timeout_seconds: int = _DEFAULT_AZ_TIMEOUT_SECONDS,
) -> str:
    """Get the primary API key for a Cognitive Services account.

    Args:
        resource_group (str): Azure resource group name.
        account_name (str): Cognitive Services account name.
        subscription_id (str | None): Optional subscription ID for the account.
        timeout_seconds (int): Timeout per az command in seconds.

    Returns:
        str: The primary API key (key1).

    Raises:
        ValidationError: If resource_group or account_name contain invalid characters.
        DiscoveryError: If az CLI is not found, command fails, output is malformed,
            or key1 is not present in the response.
    """
    _validate_azure_name(resource_group, "resource_group")
    _validate_azure_name(account_name, "account_name")

    args: list[str] = [
        "cognitiveservices",
        "account",
        "keys",
        "list",
    ]
    if subscription_id is not None:
        _validate_azure_name(subscription_id, "subscription_id")
        args.extend(["--subscription", subscription_id])
    args.extend(
        [
            "-g",
            resource_group,
            "-n",
            account_name,
            "-o",
            "json",
        ],
    )
    output = _run_az_command(args, timeout_seconds=timeout_seconds)

    keys = _parse_json_object(output)

    if "key1" not in keys:
        raise DiscoveryError(detail="key1 not found in response.")

    return str(keys["key1"])
