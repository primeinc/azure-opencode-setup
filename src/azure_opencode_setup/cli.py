"""CLI entry point for azure-opencode-setup.

Security invariants:
  - No API key via ``--key`` CLI argument (process list leakage).
  - Key only from env var (``--key-env``) or stdin prompt (``--key-stdin``).

Exit codes:
  - 0: Success
  - 2: Usage error (argparse default)
  - 3: Validation / security error
  - 4: Filesystem / permissions error
"""

from __future__ import annotations

import argparse
import dataclasses
import getpass
import os
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from azure_opencode_setup.discovery import find_cognitive_account
from azure_opencode_setup.discovery import list_deployments
from azure_opencode_setup.discovery import pick_best_cognitive_account
from azure_opencode_setup.errors import InvalidJsonError
from azure_opencode_setup.errors import InvalidSchemaError
from azure_opencode_setup.errors import LockError
from azure_opencode_setup.errors import PermissionRestrictError
from azure_opencode_setup.errors import ValidationError
from azure_opencode_setup.io import atomic_write_json
from azure_opencode_setup.io import read_json_object
from azure_opencode_setup.locking import file_lock
from azure_opencode_setup.merge import ProviderMergeSpec
from azure_opencode_setup.merge import merge_auth
from azure_opencode_setup.merge import merge_config
from azure_opencode_setup.paths import opencode_auth_path
from azure_opencode_setup.paths import opencode_config_path

if TYPE_CHECKING:
    from azure_opencode_setup.discovery import AccountMatch
    from azure_opencode_setup.types import Deployment
    from azure_opencode_setup.types import ModelEntry

_EXIT_OK = 0
_EXIT_VALIDATION = 3
_EXIT_FILESYSTEM = 4


@dataclasses.dataclass(frozen=True, slots=True)
class SetupParams:
    """Grouped parameters for the setup workflow.

    Attributes:
        resource_name (str | None): Azure Cognitive Services resource name. If omitted,
            the tool auto-picks the account with the most deployments.
        provider_id (str): OpenCode provider identifier to configure.
        whitelist (list[str]): Model names to whitelist for this provider.
        disabled_providers (list[str]): Provider IDs to append to ``disabled_providers``.
        subscription_id (str | None): Optional Azure subscription ID to scope discovery.
        az_timeout_seconds (int): az CLI timeout in seconds per command.
        key_env (str): Environment variable name holding the API key.
        key_stdin (bool): If ``True``, prompt for the API key via stdin instead of env.
        config_path (Path | None, default=None): Override for the OpenCode config file path.
        auth_path (Path | None, default=None): Override for the OpenCode auth file path.
    """

    resource_name: str | None
    provider_id: str
    whitelist: list[str]
    disabled_providers: list[str]
    subscription_id: str | None
    az_timeout_seconds: int
    key_env: str
    key_stdin: bool
    config_path: Path | None = None
    auth_path: Path | None = None


_CUSTOM_MODEL_RE = re.compile(r"^(gpt|o[0-9]|text-)")
_SAFE_MODEL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser.

    Returns:
        argparse.ArgumentParser: The configured argument parser.
    """
    parser = argparse.ArgumentParser(
        prog="azure-opencode-setup",
        description="Configure OpenCode CLI to talk to Azure AI Services.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    setup = sub.add_parser("setup", help="Write auth + config for an Azure provider")
    setup.add_argument(
        "--resource-name",
        default=None,
        help=(
            "Azure Cognitive Services resource name. If omitted, auto-picks the account "
            "with the most deployments."
        ),
    )
    setup.add_argument(
        "--subscription-id",
        default=None,
        help="Optional subscription ID to scope discovery.",
    )
    setup.add_argument(
        "--az-timeout-seconds",
        type=int,
        default=60,
        help="az CLI timeout in seconds per command (default: 60).",
    )
    setup.add_argument(
        "--config-path",
        type=Path,
        default=None,
        help="Override path to opencode.json.",
    )
    setup.add_argument(
        "--auth-path",
        type=Path,
        default=None,
        help="Override path to auth.json.",
    )
    setup.add_argument(
        "--provider-id",
        default="azure-cognitive-services",
        help="Provider ID (default: azure-cognitive-services).",
    )
    setup.add_argument(
        "--whitelist",
        nargs="*",
        default=[],
        help="Model names to whitelist.",
    )
    setup.add_argument(
        "--disabled-providers",
        nargs="*",
        default=None,
        help="Provider IDs to disable (default: ['azure'] unless --provider-id is 'azure').",
    )
    setup.add_argument(
        "--key-env",
        default="AZURE_OPENAI_API_KEY",
        help="Environment variable name for the API key (default: AZURE_OPENAI_API_KEY).",
    )
    setup.add_argument(
        "--key-stdin",
        action="store_true",
        help="Read API key from stdin (no echo) instead of env var.",
    )

    return parser


def run_setup(params: SetupParams) -> int:
    """Execute the setup workflow. Returns an exit code.

    Args:
        params (SetupParams): Grouped setup parameters.

    Returns:
        int: Exit code (0, 3, or 4).
    """
    return _execute_setup(params)


def _execute_setup(params: SetupParams) -> int:
    """Execute the setup workflow with resolved paths.

    Args:
        params (SetupParams): Grouped setup parameters.

    Returns:
        int: Exit code (0, 3, or 4).
    """
    resolved_config = (
        params.config_path if params.config_path is not None else opencode_config_path()
    )
    resolved_auth = params.auth_path if params.auth_path is not None else opencode_auth_path()

    try:
        api_key = _obtain_api_key(key_env=params.key_env, key_stdin=params.key_stdin)
    except ValidationError as exc:
        _err(str(exc))
        return _EXIT_VALIDATION

    try:
        _do_merge_and_write(
            params=params,
            config_path=resolved_config,
            auth_path=resolved_auth,
            api_key=api_key,
        )
    except (ValidationError, InvalidSchemaError) as exc:
        _err(str(exc))
        return _EXIT_VALIDATION
    except (InvalidJsonError, PermissionRestrictError, LockError, OSError) as exc:
        _err(str(exc))
        return _EXIT_FILESYSTEM

    _out(f"Configured {params.provider_id} for {params.resource_name}")
    _out(f"  Config: {resolved_config}")
    _out(f"  Auth:   {resolved_auth}")
    return _EXIT_OK


def _obtain_api_key(*, key_env: str, key_stdin: bool) -> str:
    """Read the API key from env or stdin.

    Args:
        key_env (str): Environment variable name for the API key.
        key_stdin (bool): If ``True``, read the key from a no-echo stdin prompt.

    Returns:
        str: The API key string.

    Raises:
        ValidationError: If no key source is configured or the key is empty.
    """
    if key_stdin:
        key = getpass.getpass("Enter API key: ")
        if not key:
            raise ValidationError(field="api_key", detail="Empty key from stdin")
        return key

    if not key_env:
        raise ValidationError(field="key_env", detail="No key source specified")

    value = os.environ.get(key_env)
    if not value:
        raise ValidationError(
            field="api_key",
            detail=f"Environment variable {key_env!r} is not set or empty",
        )
    return value


def _do_merge_and_write(
    *,
    params: SetupParams,
    config_path: Path,
    auth_path: Path,
    api_key: str,
) -> None:
    """Read existing files, merge, and write atomically.

    Args:
        params (SetupParams): Grouped setup parameters.
        config_path (Path): Destination path for ``opencode.json``.
        auth_path (Path): Destination path for ``auth.json``.
        api_key (str): API key to store in ``auth.json``.

    Returns:
        None: Writes files as a side effect.
    """
    resolved_resource_name, effective_whitelist, effective_models, account_msg = (
        _discover_whitelist_and_models(params)
    )

    if account_msg:
        _out(account_msg)

    with file_lock(config_path), file_lock(auth_path):
        existing_config = read_json_object(config_path)
        existing_auth = read_json_object(auth_path)

        new_config = merge_config(
            existing_config,
            spec=ProviderMergeSpec(
                provider_id=params.provider_id,
                resource_name=resolved_resource_name,
                whitelist=effective_whitelist,
                disabled_providers=params.disabled_providers,
                models=effective_models,
            ),
        )
        new_auth = merge_auth(
            existing_auth,
            provider_id=params.provider_id,
            api_key=api_key,
        )

        atomic_write_json(config_path, new_config)
        atomic_write_json(auth_path, new_auth, secure=True)


def _select_account(params: SetupParams) -> tuple[AccountMatch, list[AccountMatch], str]:
    if params.resource_name:
        chosen, others = find_cognitive_account(
            params.resource_name,
            subscription_id=params.subscription_id,
            timeout_seconds=params.az_timeout_seconds,
        )
        return chosen, others, "specified"

    chosen, others = pick_best_cognitive_account(
        subscription_id=params.subscription_id,
        timeout_seconds=params.az_timeout_seconds,
    )
    return chosen, others, "auto-picked"


def _available_models_from_deployments(
    deployments: list[Deployment],
) -> tuple[list[str], set[str]]:
    seen: set[str] = set()
    models: list[str] = []
    for d in deployments:
        # OpenCode model IDs are lowercase (models.dev). Azure deployment names
        # can differ in casing and can also differ from the catalog ID.
        for raw in (d.name, d.model):
            if not raw:
                continue
            v = raw.lower()
            if not _SAFE_MODEL_ID_RE.match(v):
                continue
            if v in seen:
                continue
            seen.add(v)
            models.append(v)

    models.sort()
    return models, seen


def _normalize_and_validate_whitelist(
    desired_raw: list[str],
    *,
    available_sorted: list[str],
    available_set: set[str],
) -> list[str]:
    if not desired_raw:
        return available_sorted

    whitelist: list[str] = []
    seen: set[str] = set()
    for w in desired_raw:
        v = w.lower()
        if v in seen:
            continue
        seen.add(v)
        whitelist.append(v)

    missing = [w for w in whitelist if w not in available_set]
    if missing:
        deployed_preview = ", ".join(available_sorted[:10])
        raise ValidationError(
            field="whitelist",
            detail=(
                f"Unknown model(s): {', '.join(missing)}. Deployed (first 10): {deployed_preview}"
            ),
        )

    return whitelist


def _models_overrides_from_deployments(
    deployments: list[Deployment],
) -> dict[str, ModelEntry] | None:
    models: dict[str, ModelEntry] = {}
    for d in deployments:
        dep_raw = d.name
        dep_id = dep_raw.lower()

        dep_entry: ModelEntry | None = None

        # Case-sensitive routing fix for OpenCode's /openai/v1/responses path:
        # override api.id to the exact Azure deployment name.
        if _SAFE_MODEL_ID_RE.match(dep_id):
            dep_entry = models.setdefault(
                dep_id,
                {
                    "name": f"{dep_raw} (Azure)",
                    "api": {"id": dep_raw, "npm": "@ai-sdk/azure"},
                },
            )

        model_raw = d.model
        model_id = model_raw.lower()
        if model_raw and _SAFE_MODEL_ID_RE.match(model_id):
            # Prefer model display name over deployment name when available.
            if dep_entry is not None:
                dep_entry["name"] = f"{model_raw} (Azure)"

            # Map catalog model ID -> deployment name when they differ
            if model_id != dep_id:
                models.setdefault(
                    model_id,
                    {
                        "name": f"{model_raw} (Azure)",
                        "api": {"id": dep_raw, "npm": "@ai-sdk/azure"},
                    },
                )
    return models or None


def _account_message(
    selection_reason: str,
    *,
    chosen: AccountMatch,
    others: list[AccountMatch],
) -> str:
    acct = chosen.account
    sub = chosen.subscription
    if selection_reason == "auto-picked":
        msg = f"Auto-picked resource {acct.name} in subscription {sub.name} ({sub.id})"
    else:
        msg = f"Using resource {acct.name} in subscription {sub.name} ({sub.id})"

    if not others:
        return msg

    other_names = ", ".join(f"{m.subscription.name} ({m.subscription.id})" for m in others[:5])
    return f"{msg}. Also found matches in: {other_names}. Use --subscription-id to override."


def _discover_whitelist_and_models(
    params: SetupParams,
) -> tuple[str, list[str], dict[str, ModelEntry] | None, str]:
    """Resolve target account, deployments, whitelist, and optional models mapping."""
    chosen, others, selection_reason = _select_account(params)

    acct = chosen.account
    deployments = list_deployments(
        acct.resource_group,
        acct.name,
        subscription_id=chosen.subscription.id,
        timeout_seconds=params.az_timeout_seconds,
    )
    if not deployments:
        raise ValidationError(
            field="deployments",
            detail=(
                f"No deployments found on resource {acct.name!r} "
                f"(subscription {chosen.subscription.id})."
            ),
        )

    available_sorted, available_set = _available_models_from_deployments(deployments)
    whitelist = _normalize_and_validate_whitelist(
        params.whitelist,
        available_sorted=available_sorted,
        available_set=available_set,
    )
    models = _models_overrides_from_deployments(deployments)
    msg = _account_message(selection_reason, chosen=chosen, others=others)
    return acct.name, whitelist, models, msg


def _err(msg: str) -> None:
    """Write an error message to stderr.

    Args:
        msg (str): Message to write.

    Returns:
        None: Writes to stderr as a side effect.
    """
    sys.stderr.write(f"error: {msg}\n")


def _out(msg: str) -> None:
    """Write a message to stdout.

    Args:
        msg (str): Message to write.

    Returns:
        None: Writes to stdout as a side effect.
    """
    sys.stdout.write(f"{msg}\n")


def main() -> None:
    """CLI entry point.

    Returns:
        None: Always raises ``SystemExit``.

    Raises:
        SystemExit: Always raised with the command's exit code.
    """
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "setup":
        # Derive disabled_providers: if user specified --provider-id azure, don't disable azure
        disabled = args.disabled_providers
        if disabled is None:
            disabled = [] if args.provider_id == "azure" else ["azure"]

        params = SetupParams(
            resource_name=args.resource_name,
            provider_id=args.provider_id,
            whitelist=args.whitelist,
            disabled_providers=disabled,
            subscription_id=args.subscription_id,
            az_timeout_seconds=args.az_timeout_seconds,
            key_env="" if args.key_stdin else args.key_env,
            key_stdin=args.key_stdin,
            config_path=args.config_path,
            auth_path=args.auth_path,
        )
        raise SystemExit(run_setup(params))


if __name__ == "__main__":
    main()
