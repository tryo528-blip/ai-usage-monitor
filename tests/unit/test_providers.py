from ai_usage_monitor.domain.providers import (
    PROVIDER_CARD_SCHEMA_SETTING,
    PROVIDER_CARD_SCHEMA_VERSION,
    get_visible_provider_ids,
)


def test_legacy_provider_selection_expands_to_adjacent_window_pairs() -> None:
    selected = get_visible_provider_ids({"visible_providers": ["codex", "claude_5h", "antyg"]})

    assert selected == (
        "codex_5h",
        "codex",
        "claude_5h",
        "claude",
        "antyg_5h",
        "antyg",
        "openrouter",
    )


def test_current_provider_schema_preserves_exact_window_choices() -> None:
    selected = get_visible_provider_ids(
        {
            PROVIDER_CARD_SCHEMA_SETTING: PROVIDER_CARD_SCHEMA_VERSION,
            "visible_providers": ["codex", "claude_5h", "antyg"],
        }
    )

    assert selected == ("codex", "claude_5h", "antyg")


def test_schema_v2_selection_adds_openrouter_without_reexpanding_pairs() -> None:
    selected = get_visible_provider_ids(
        {
            PROVIDER_CARD_SCHEMA_SETTING: 2,
            "visible_providers": ["codex", "grok"],
        }
    )

    assert selected == ("codex", "grok", "openrouter")
