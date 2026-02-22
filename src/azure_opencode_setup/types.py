"""Typed domain model for OpenCode configuration and auth files.

These TypedDicts define the exact shape of the JSON files this tool reads and writes.
They are the single source of truth for the merge logic and CLI.
"""

from __future__ import annotations

from typing import TypedDict


class AuthEntry(TypedDict):
    """A single provider auth entry in ``auth.json``."""

    type: str  # Literal["api"] at runtime, str for TypedDict compat
    key: str


# AuthFile is a plain dict mapping provider-id → AuthEntry.
# We use a type alias (not a class) because auth.json is an open dict
# where provider IDs are arbitrary strings.
AuthFile = dict[str, AuthEntry]


class ProviderOptions(TypedDict):
    """Options block inside a provider config."""

    baseURL: str


class ModelEntry(TypedDict):
    """A single custom model entry inside a provider config."""

    name: str


class ProviderConfig(TypedDict, total=False):
    """Configuration for a single provider in ``opencode.json``.

    ``options`` and ``whitelist`` are always present in our output.
    ``models`` is optional (only present when custom models exist).
    """

    options: ProviderOptions
    whitelist: list[str]
    models: dict[str, ModelEntry]


class OpenCodeConfig(TypedDict, total=False):
    """Top-level shape of ``opencode.json`` (fields this tool manages).

    Uses ``total=False`` because existing files may have any subset of keys,
    plus keys we don't manage (which are preserved via merge).
    """

    disabled_providers: list[str]
    provider: dict[str, ProviderConfig]
