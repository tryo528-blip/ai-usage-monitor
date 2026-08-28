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


# Keep the existing short labels for the providers that were already visible.
# The requested Claude five-hour card is represented by the existing Claude
# bridge and is intentionally separate from the weekly Claude card.
PROVIDER_DEFINITIONS: tuple[ProviderDefinition, ...] = (
    ProviderDefinition(
        provider_id="codex",
        title="CDX",
        summary_type="quota",
        full_name="Codex",
        quota_fields=(("weekly", "주간 사용량"),),
    ),
    ProviderDefinition(
        provider_id="grok",
        title="Grok",
        summary_type="quota",
        full_name="xAI Grok",
        quota_fields=(("weekly", "주간 사용량"),),
    ),
    ProviderDefinition(
        provider_id="deepseek",
        title="DSeek",
        summary_type="balance",
        full_name="DeepSeek",
    ),
    ProviderDefinition(
        provider_id="zai",
        title="Z.AI",
        summary_type="manual",
        full_name="Z.AI",
    ),
    ProviderDefinition(
        provider_id="kimi3",
        title="KIMI3",
        summary_type="manual",
        full_name="Kimi 3",
    ),
    ProviderDefinition(
        provider_id="claude_5h",
        title="CLD5H",
        summary_type="quota",
        full_name="Claude",
        quota_fields=(("five_hour", "5시간 사용량"),),
        collector_id="claude",
    ),
    ProviderDefinition(
        provider_id="antyg",
        title="AntyG",
        summary_type="quota",
        full_name="Google Antigravity (Gemini)",
        quota_fields=(
            ("five_hour", "5시간 사용량"),
            ("weekly", "주간 사용량"),
        ),
        collector_id="antyg",
        omit_missing_quota=True,
    ),
    # Keep the existing weekly Claude card available as an opt-in choice.
    ProviderDefinition(
        provider_id="claude",
        title="CLD-W",
        summary_type="quota",
        full_name="Claude Weekly",
        quota_fields=(("weekly", "주간 사용량"),),
        collector_id="claude",
    ),
)

PROVIDER_DEFINITION_BY_ID = {item.provider_id: item for item in PROVIDER_DEFINITIONS}

# Existing settings files do not have a provider-selection key. This default
# removes OpenRouter while adding the requested cards on first launch.
DEFAULT_VISIBLE_PROVIDER_IDS: tuple[str, ...] = (
    "codex",
    "grok",
    "deepseek",
    "zai",
    "kimi3",
    "claude_5h",
    "antyg",
)

VISIBLE_PROVIDERS_SETTING = "visible_providers"


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
    return tuple(
        definition.provider_id
        for definition in PROVIDER_DEFINITIONS
        if definition.provider_id in requested
    )
