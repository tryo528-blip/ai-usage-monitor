from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class ProviderDefinition:
    """A selectable card and the collector that feeds it, if available."""

    provider_id: str
    title: str
    summary_type: str
    full_name: str | None = None
    quota_fields: tuple[tuple[str, str], ...] = ()
    collector_id: str | None = None
    omit_missing_quota: bool = False
    balance_display: str = "percent"


# Every card is a two-character code: provider letter + window (5 = five hours,
# W = weekly). Codex is "G" for GPT, Antigravity is "A". Full names remain
# available to settings screens and tooltips.
PROVIDER_DEFINITIONS: tuple[ProviderDefinition, ...] = (
    ProviderDefinition(
        provider_id="claude_5h",
        title="C5",
        summary_type="quota",
        full_name="Claude 5h",
        quota_fields=(("five_hour", "5시간 사용량"),),
        collector_id="claude",
        omit_missing_quota=True,
    ),
    ProviderDefinition(
        provider_id="claude",
        title="CW",
        summary_type="quota",
        full_name="Claude Weekly",
        quota_fields=(("weekly", "주간 사용량"),),
        collector_id="claude",
        omit_missing_quota=True,
    ),
    ProviderDefinition(
        provider_id="claude_fable",
        title="FW",
        summary_type="quota",
        full_name="Fable Weekly",
        quota_fields=(("weekly_fable", "Fable 주간 사용량"),),
        collector_id="claude",
        omit_missing_quota=True,
    ),
    ProviderDefinition(
        provider_id="codex_5h",
        title="G5",
        summary_type="quota",
        full_name="Codex 5h",
        quota_fields=(("five_hour", "5시간 사용량"),),
        collector_id="codex",
        omit_missing_quota=True,
    ),
    ProviderDefinition(
        provider_id="codex",
        title="GW",
        summary_type="quota",
        full_name="Codex Weekly",
        quota_fields=(("weekly", "주간 사용량"),),
        collector_id="codex",
        omit_missing_quota=True,
    ),
    ProviderDefinition(
        provider_id="grok",
        title="GR",
        summary_type="quota",
        full_name="xAI Grok Weekly",
        quota_fields=(("weekly", "주간 사용량"),),
    ),
    ProviderDefinition(
        provider_id="antyg_5h",
        title="A5",
        summary_type="quota",
        full_name="Antigravity 5h",
        quota_fields=(("five_hour", "5시간 사용량"),),
        collector_id="antyg",
        omit_missing_quota=True,
    ),
    ProviderDefinition(
        provider_id="antyg",
        title="AW",
        summary_type="quota",
        full_name="Antigravity Weekly",
        quota_fields=(("weekly", "주간 사용량"),),
        collector_id="antyg",
        omit_missing_quota=True,
    ),
    ProviderDefinition(
        provider_id="openrouter",
        title="OR",
        summary_type="balance",
        full_name="OpenRouter",
        balance_display="amount",
    ),
)

PROVIDER_DEFINITION_BY_ID = {item.provider_id: item for item in PROVIDER_DEFINITIONS}

# Existing settings files do not have a provider-selection key. This default
# shows every supported card on first launch.
DEFAULT_VISIBLE_PROVIDER_IDS: tuple[str, ...] = tuple(
    definition.provider_id for definition in PROVIDER_DEFINITIONS
)

VISIBLE_PROVIDERS_SETTING = "visible_providers"
PROVIDER_CARD_SCHEMA_SETTING = "provider_card_schema"
PROVIDER_CARD_SCHEMA_VERSION = 4


def get_visible_provider_ids(settings: Mapping[str, object]) -> tuple[str, ...]:
    """Read selected providers, preserving catalog order and allowing none."""

    raw = settings.get(VISIBLE_PROVIDERS_SETTING)
    if raw is None:
        # Accept the earlier descriptive name if a user already tried a local
        # build with it, while keeping the persisted key canonical.
        raw = settings.get("selected_providers")
    if raw is None:
        return DEFAULT_VISIBLE_PROVIDER_IDS
    if not isinstance(raw, (list, tuple)):
        return DEFAULT_VISIBLE_PROVIDER_IDS

    requested = {item for item in raw if isinstance(item, str)}
    schema_version = settings.get(PROVIDER_CARD_SCHEMA_SETTING)
    if schema_version not in {2, 3, PROVIDER_CARD_SCHEMA_VERSION}:
        # Older settings only knew one Codex card, one Antigravity card, and
        # defaulted to Claude 5h. Expand those selections to the new adjacent
        # 5H/WEEK card pairs once. Schema-v2 and newer settings preserve exact
        # checkbox choices.
        if "codex" in requested:
            requested.add("codex_5h")
        if requested & {"claude", "claude_5h"}:
            requested.update({"claude", "claude_5h"})
        if "antyg" in requested:
            requested.add("antyg_5h")
    if schema_version not in {3, PROVIDER_CARD_SCHEMA_VERSION}:
        # OpenRouter was absent from the schema-v2 catalog, so enable it once
        # when upgrading. After saving schema v3, the checkbox is fully
        # user-controlled like every other provider.
        requested.add("openrouter")
    if schema_version != PROVIDER_CARD_SCHEMA_VERSION and requested & {"claude", "claude_5h"}:
        # Schema v4 added the Fable weekly bucket next to the Claude cards.
        requested.add("claude_fable")
    return tuple(
        definition.provider_id
        for definition in PROVIDER_DEFINITIONS
        if definition.provider_id in requested
    )


TRAY_PROVIDERS_SETTING = "tray_providers"
MAX_TRAY_PROVIDERS = 3


DEFAULT_TRAY_PROVIDER_IDS: tuple[str, ...] = ("claude_5h", "claude", "claude_fable")


def get_tray_provider_ids(settings: Mapping[str, object]) -> tuple[str, ...]:
    """Read the providers pinned to the Windows taskbar tray, at most three.

    Without a saved choice the tray shows Claude 5h, Claude weekly and Fable
    weekly. An explicitly saved empty list keeps the tray empty.
    """

    raw = settings.get(TRAY_PROVIDERS_SETTING)
    if not isinstance(raw, (list, tuple)):
        return DEFAULT_TRAY_PROVIDER_IDS

    selected: list[str] = []
    for item in raw:
        if item in PROVIDER_DEFINITION_BY_ID and item not in selected:
            selected.append(item)
    return tuple(selected[:MAX_TRAY_PROVIDERS])
