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
import sys
from typing import TYPE_CHECKING

from azure_opencode_setup.errors import InvalidJsonError
from azure_opencode_setup.errors import InvalidSchemaError
from azure_opencode_setup.errors import LockError
from azure_opencode_setup.errors import PermissionRestrictError
from azure_opencode_setup.errors import ValidationError
from azure_opencode_setup.io import atomic_write_json
from azure_opencode_setup.io import read_json_object
from azure_opencode_setup.locking import backup_file
from azure_opencode_setup.locking import file_lock
from azure_opencode_setup.merge import merge_auth
from azure_opencode_setup.merge import merge_config
from azure_opencode_setup.paths import opencode_auth_path
from azure_opencode_setup.paths import opencode_config_path

if TYPE_CHECKING:
    from pathlib import Path

_EXIT_OK = 0
_EXIT_VALIDATION = 3
_EXIT_FILESYSTEM = 4


@dataclasses.dataclass(frozen=True, slots=True)
class SetupParams:
    """Grouped parameters for the setup workflow.

    Attributes:
        resource_name (str): Azure Cognitive Services resource name used to build the endpoint.
        provider_id (str): OpenCode provider identifier to configure.
        whitelist (list[str]): Model names to whitelist for this provider.
        disabled_providers (list[str]): Provider IDs to append to ``disabled_providers``.
        key_env (str): Environment variable name holding the API key.
        key_stdin (bool): If ``True``, prompt for the API key via stdin instead of env.
        config_path (Path | None, default=None): Override for the OpenCode config file path.
        auth_path (Path | None, default=None): Override for the OpenCode auth file path.
    """

    resource_name: str
    provider_id: str
    whitelist: list[str]
    disabled_providers: list[str]
    key_env: str
    key_stdin: bool
    config_path: Path | None = None
    auth_path: Path | None = None


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
        required=True,
        help="Azure Cognitive Services resource name.",
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
    """Read existing files, merge, back up, and write atomically.

    Args:
        params (SetupParams): Grouped setup parameters.
        config_path (Path): Destination path for ``opencode.json``.
        auth_path (Path): Destination path for ``auth.json``.
        api_key (str): API key to store in ``auth.json``.

    Returns:
        None: Writes files as a side effect.
    """
    with file_lock(config_path), file_lock(auth_path):
        existing_config = read_json_object(config_path)
        existing_auth = read_json_object(auth_path)

        new_config = merge_config(
            existing_config,
            provider_id=params.provider_id,
            resource_name=params.resource_name,
            whitelist=params.whitelist,
            disabled_providers=params.disabled_providers,
        )
        new_auth = merge_auth(
            existing_auth,
            provider_id=params.provider_id,
            api_key=api_key,
        )

        if config_path.exists():
            backup_file(config_path)
        if auth_path.exists():
            backup_file(auth_path)

        atomic_write_json(config_path, new_config)
        atomic_write_json(auth_path, new_auth, secure=True)


def _err(msg: str) -> None:
    """Write an error message to stderr.

    Args:
        msg (str): Message to write.

    Returns:
        None: Writes to stderr as a side effect.
    """
    sys.stderr.write(f"error: {msg}\n")


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
            key_env="" if args.key_stdin else args.key_env,
            key_stdin=args.key_stdin,
        )
        raise SystemExit(run_setup(params))


if __name__ == "__main__":
    main()
