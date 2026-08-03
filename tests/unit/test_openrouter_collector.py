from __future__ import annotations

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
                    "usage_daily": {"used": 10, "limit": 100, "remaining": 90},
                    "usage_weekly": {"used": 40, "limit": 100, "remaining": 60},
                    "usage_monthly": {"used": 30, "limit": 100, "remaining": 70},
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
    assert snapshot.quota_windows[0].used_value == Decimal("25.75")
    assert snapshot.quota_windows[0].limit_value == Decimal("100.5")
    assert snapshot.quota_windows[0].remaining_value == Decimal("74.75")
    assert abs(snapshot.quota_windows[0].used_percent - 25.621890547263682) < 0.001
    assert snapshot.balances[0].remaining == Decimal("74.75")
    assert snapshot.metadata["usage_daily"]["used"] == 10


def test_openrouter_collector_handles_limit_null_without_fake_percentage() -> None:
    secret_store = FakeSecretStore()
    secret_store.set("openrouter.api_key", "test-api-key")
    collector = OpenRouterCollector(secret_store=secret_store)

    with respx.mock(assert_all_called=True) as mock:
        mock.get("https://openrouter.ai/api/v1/key").respond(
            200,
            json={
                "data": {
                    "usage_daily": {"used": 10, "limit": 100, "remaining": 90},
                    "usage_weekly": {"used": 40, "limit": 100, "remaining": 60},
                    "usage_monthly": {"used": 30, "limit": 100, "remaining": 70},
                    "limit": None,
                    "limit_remaining": None,
                }
            },
        )

        snapshot = collector.collect()

    assert snapshot.status == ProviderStatus.OK
    assert snapshot.quota_windows == []


def test_openrouter_collector_handles_auth_required() -> None:
    secret_store = FakeSecretStore()
    secret_store.set("openrouter.api_key", "test-api-key")
    collector = OpenRouterCollector(secret_store=secret_store)

    with respx.mock(assert_all_called=True) as mock:
        mock.get("https://openrouter.ai/api/v1/key").respond(401)
        snapshot = collector.collect()

    assert snapshot.status == ProviderStatus.AUTH_REQUIRED
    assert snapshot.error_code == "AUTH_FAILED"
