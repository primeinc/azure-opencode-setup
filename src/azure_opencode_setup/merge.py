"""Pure merge functions for auth.json and opencode.json.

These functions are deterministic and side-effect-free: they take an
existing dict and return a new merged dict.  The I/O layer (``io.py``)
handles reading/writing.

Design invariants:
  - Never mutate the input dict.
  - Preserve all keys not owned by this tool.
  - Validate inputs strictly (no SSRF, no empty IDs).
  - Dedup lists while preserving insertion order.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from typing import cast

from azure_opencode_setup.errors import InvalidSchemaError
from azure_opencode_setup.errors import ValidationError

if TYPE_CHECKING:
    from collections.abc import Sequence

# Azure Cognitive Services resource name: 2-64 chars, alphanumeric + hyphens,
# must start/end with alphanumeric.  No dots, slashes, spaces, or specials.
_RESOURCE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-]{0,62}[a-zA-Z0-9]$|^[a-zA-Z0-9]$")

_COGS_ENDPOINT_TEMPLATE = "https://{name}.cognitiveservices.azure.com/openai"


def validate_resource_name(name: str) -> None:
    """Validate an Azure resource name against naming rules.

    Raises:
        ValidationError: If *name* is empty, too long, or contains invalid chars.
    """
    if not name or not _RESOURCE_NAME_RE.match(name):
        raise ValidationError(
            field="resource_name",
            detail=(
                f"Invalid Azure resource name {name!r}. "
                "Must be 1-64 alphanumeric characters and hyphens, "
                "starting and ending with alphanumeric."
            ),
        )


def merge_auth(
    existing: dict[str, object],
    *,
    provider_id: str,
    api_key: str,
) -> dict[str, object]:
    """Merge a single provider auth entry into an existing auth dict.

    Args:
        existing: The current contents of ``auth.json`` (or ``{}``).
        provider_id: The provider ID to insert/update.
        api_key: The API key value.

    Returns:
        A new dict with the provider entry upserted and all other entries preserved.

    Raises:
        ValidationError: If *provider_id* or *api_key* is empty.
    """
    if not provider_id:
        raise ValidationError(field="provider_id", detail="Must not be empty")
    if not api_key:
        raise ValidationError(field="api_key", detail="Must not be empty")

    result = dict(existing)
    result[provider_id] = {"type": "api", "key": api_key}
    return result


def merge_config(
    existing: dict[str, object],
    *,
    provider_id: str,
    resource_name: str,
    whitelist: Sequence[str],
    disabled_providers: Sequence[str],
) -> dict[str, object]:
    """Merge provider config into an existing opencode.json dict.

    Args:
        existing: The current contents of ``opencode.json`` (or ``{}``).
        provider_id: The provider ID to configure.
        resource_name: The Azure resource name (used to construct baseURL).
        whitelist: Model names to whitelist.
        disabled_providers: Provider IDs to disable.

    Returns:
        A new dict with the provider block merged and all other keys preserved.

    Raises:
        ValidationError: If inputs fail validation.
        InvalidSchemaError: If existing ``disabled_providers`` has wrong type.
    """
    if not provider_id:
        raise ValidationError(field="provider_id", detail="Must not be empty")
    validate_resource_name(resource_name)

    result = dict(existing)

    # --- disabled_providers: union + dedup ---
    merged_dp = _merge_disabled_providers(result.get("disabled_providers"), disabled_providers)
    result["disabled_providers"] = merged_dp

    # --- provider block ---
    existing_providers = result.get("provider")
    if isinstance(existing_providers, dict):
        typed_providers = cast("dict[str, object]", existing_providers)
        providers: dict[str, object] = dict(typed_providers)
    else:
        providers = {}

    base_url = _COGS_ENDPOINT_TEMPLATE.format(name=resource_name)
    deduped_whitelist = _dedup_preserve_order(list(whitelist))

    providers[provider_id] = {
        "options": {"baseURL": base_url},
        "whitelist": deduped_whitelist,
    }
    result["provider"] = providers

    return result


def _merge_disabled_providers(
    existing_dp: object,
    new_providers: Sequence[str],
) -> list[str]:
    """Extract, validate, and merge disabled_providers lists.

    Args:
        existing_dp: The raw ``disabled_providers`` value from existing config.
        new_providers: New provider IDs to add to the list.

    Returns:
        Deduplicated, order-preserving merged list.

    Raises:
        InvalidSchemaError: If *existing_dp* is not None/list.
    """
    if existing_dp is None:
        existing_list: list[str] = []
    elif isinstance(existing_dp, list):
        typed_dp = cast("list[object]", existing_dp)
        _validate_string_list(typed_dp)
        existing_list = [str(x) for x in typed_dp]
    else:
        raise InvalidSchemaError(
            path="opencode.json",
            detail=(
                f"disabled_providers must be a list, got {type(existing_dp).__name__}. "
                "This may indicate a hand-edited or corrupt config file."
            ),
        )

    return _dedup_preserve_order([*existing_list, *new_providers])


def _validate_string_list(items: list[object]) -> None:
    """Raise if any item in *items* is not a string."""
    for item in items:
        if not isinstance(item, str):
            raise InvalidSchemaError(
                path="opencode.json",
                detail=f"disabled_providers contains non-string: {type(item).__name__}",
            )


def _dedup_preserve_order(items: list[str]) -> list[str]:
    """Remove duplicates from *items* while preserving first-occurrence order."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
