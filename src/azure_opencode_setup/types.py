"""Typed domain model for OpenCode configuration and auth files.

These TypedDicts define the exact shape of the JSON files this tool reads and writes.
They are the single source of truth for the merge logic and CLI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict


@dataclass(frozen=True, slots=True)
class CognitiveAccount:
    """A discovered Azure Cognitive Services or OpenAI account.

    Attributes:
        name (str): Resource name.
        resource_group (str): Resource group containing the account.
        endpoint (str): OpenAI-compatible endpoint URL.
        location (str): Azure region.
        kind (str): Resource kind ("AIServices" or "OpenAI").
    """

    name: str
    resource_group: str
    endpoint: str
    location: str
    kind: str


@dataclass(frozen=True, slots=True)
class Deployment:
    """A deployed model within a Cognitive Services account.

    Attributes:
        name (str): Deployment name (used as model ID in API calls).
        model (str): Underlying model name (e.g. "gpt-4o").
    """

    name: str
    model: str


class AuthEntry(TypedDict):
    """A single provider auth entry in ``auth.json``.

    Attributes:
        type (str): Auth entry type (OpenCode expects "api").
        key (str): API key string.
    """

    type: str
    key: str


AuthFile = dict[str, AuthEntry]


class ProviderOptions(TypedDict):
    """Options block inside a provider config.

    Attributes:
        baseURL (str): Base URL for the provider's OpenAI-compatible endpoint.
    """

    baseURL: str


class ModelEntry(TypedDict):
    """A single custom model entry inside a provider config.

    Attributes:
        name (str): Display name for the model.
    """

    name: str


class ProviderConfig(TypedDict, total=False):
    """Configuration for a single provider in ``opencode.json``.

    Attributes:
        options (ProviderOptions): Provider options.
        whitelist (list[str]): Model names allowed for this provider.
        models (dict[str, ModelEntry]): Optional custom model mapping.
    """

    options: ProviderOptions
    whitelist: list[str]
    models: dict[str, ModelEntry]


class OpenCodeConfig(TypedDict, total=False):
    """Top-level shape of ``opencode.json`` for fields this tool manages.

    Attributes:
        disabled_providers (list[str]): Provider IDs to disable.
        provider (dict[str, ProviderConfig]): Provider configuration mapping.
    """

    disabled_providers: list[str]
    provider: dict[str, ProviderConfig]
