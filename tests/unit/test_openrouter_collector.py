from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

import respx

from ai_usage_monitor.collectors.openrouter import OpenRouterCollector
from ai_usage_monitor.domain.enums import ProviderStatus
from ai_usage_monitor.infrastructure.secret_store import FakeSecretStore


def test_openrouter_collector_parses_official_response_and_credits() -> None:
    secret_store = FakeSecretStore()
    secret_store.set("openrouter.api_key", "test-api-key")
    secret_store.set("openrouter.management_key", "test-management-key")
    collector = OpenRouterCollector(secret_store=secret_store)

    with respx.mock(assert_all_called=True) as mock:
        mock.get("https://openrouter.ai/api/v1/key").respond(
            200,
            json={
                "data": {
                    "usage": 12.5,
                    "usage_daily": 10.0,
                    "usage_weekly": 40.0,
                    "usage_monthly": 30.0,
                    "limit": 100.5,
                    "limit_remaining": 74.75,
                    "limit_reset": "weekly",
                    "expires_at": "2026-08-03T12:00:00Z",
                }
            },
        )
        mock.get("https://openrouter.ai/api/v1/credits").respond(
            200,
            json={"data": {"total_credits": 100.5, "total_usage": 25.75}},
        )

        snapshot = collector.collect()

    assert snapshot.status == ProviderStatus.OK
    assert len(snapshot.quota_windows) == 1
    assert snapshot.quota_windows[0].key == "weekly"
    assert snapshot.quota_windows[0].label == "주간 사용량"
    assert snapshot.quota_windows[0].used_value == Decimal("25.75")
    assert snapshot.quota_windows[0].limit_value == Decimal("100.5")
    assert snapshot.quota_windows[0].remaining_value == Decimal("74.75")
    assert snapshot.quota_windows[0].used_percent is not None
    assert abs(snapshot.quota_windows[0].used_percent - 25.621890547263682) < 0.001
    assert snapshot.balances[0].remaining == Decimal("74.75")
    assert snapshot.metadata["usage_daily"] == 10.0


def test_openrouter_collector_handles_limit_null_without_fake_percentage() -> None:
    secret_store = FakeSecretStore()
    secret_store.set("openrouter.api_key", "test-api-key")
    collector = OpenRouterCollector(secret_store=secret_store)

    with respx.mock(assert_all_called=True) as mock:
        mock.get("https://openrouter.ai/api/v1/key").respond(
            200,
            json={
                "data": {
                    "usage": 12.5,
                    "usage_daily": 10.0,
                    "usage_weekly": 40.0,
                    "usage_monthly": 30.0,
                    "limit": None,
                    "limit_remaining": None,
                    "limit_reset": None,
                }
            },
        )

        snapshot = collector.collect()

    assert snapshot.status == ProviderStatus.OK
    assert snapshot.quota_windows == []


def test_openrouter_collector_sets_reset_labels_and_timestamps() -> None:
    collector = OpenRouterCollector(secret_store=FakeSecretStore())

    assert collector._quota_key_from_reset("daily") == "daily"
    assert collector._quota_key_from_reset("weekly") == "weekly"
    assert collector._quota_key_from_reset("monthly") == "monthly"
    assert collector._quota_key_from_reset(None) == "lifetime"
    assert collector._label_from_reset("daily") == "일간"
    assert collector._label_from_reset("weekly") == "주간"
    assert collector._label_from_reset("monthly") == "월간"
    assert collector._label_from_reset(None) == "누적"

    current = datetime.now(timezone.utc)
    daily_reset = collector._resets_at("daily")
    assert daily_reset is not None
    assert daily_reset.tzinfo == timezone.utc
    assert daily_reset.time() == time.min
    assert daily_reset.date() == (current.date() + timedelta(days=1))

    weekly_reset = collector._resets_at("weekly")
    assert weekly_reset is not None
    assert weekly_reset.tzinfo == timezone.utc
    assert weekly_reset.time() == time.min
    assert weekly_reset.weekday() == 0

    monthly_reset = collector._resets_at("monthly")
    assert monthly_reset is not None
    assert monthly_reset.tzinfo == timezone.utc
    assert monthly_reset.time() == time.min
    assert monthly_reset.day == 1


def test_openrouter_collector_handles_auth_required() -> None:
    secret_store = FakeSecretStore()
    secret_store.set("openrouter.api_key", "test-api-key")
    collector = OpenRouterCollector(secret_store=secret_store)

    with respx.mock(assert_all_called=True) as mock:
        mock.get("https://openrouter.ai/api/v1/key").respond(401)
        snapshot = collector.collect()

    assert snapshot.status == ProviderStatus.AUTH_REQUIRED
    assert snapshot.error_code == "AUTH_FAILED"
