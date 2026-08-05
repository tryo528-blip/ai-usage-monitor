from __future__ import annotations

from decimal import Decimal

import respx

from ai_usage_monitor.collectors.openrouter import OpenRouterCollector
from ai_usage_monitor.domain.enums import ProviderStatus
from ai_usage_monitor.infrastructure.secret_store import FakeSecretStore


def test_openrouter_collector_uses_management_key_for_balance() -> None:
    secret_store = FakeSecretStore()
    secret_store.set("openrouter.management_key", "test-management-key")
    collector = OpenRouterCollector(secret_store=secret_store)

    with respx.mock(assert_all_called=True) as mock:
        mock.get("https://openrouter.ai/api/v1/credits").respond(
            200,
            json={"data": {"total_credits": 100.5, "total_usage": 25.75}},
        )
        snapshot = collector.collect()

    assert snapshot.status == ProviderStatus.OK
    assert len(snapshot.balances) == 1
    assert snapshot.balances[0].total == Decimal("100.5")
    assert snapshot.balances[0].used == Decimal("25.75")
    assert snapshot.balances[0].remaining == Decimal("74.75")
    assert snapshot.quota_windows == []


def test_openrouter_collector_requires_management_key() -> None:
    collector = OpenRouterCollector(secret_store=FakeSecretStore())

    snapshot = collector.collect()

    assert snapshot.status == ProviderStatus.AUTH_REQUIRED
    assert snapshot.error_code == "MANAGEMENT_KEY_NOT_CONFIGURED"
    assert snapshot.message == "OpenRouter Management Key가 설정되지 않았습니다."


def test_openrouter_collector_handles_management_key_auth_failure() -> None:
    secret_store = FakeSecretStore()
    secret_store.set("openrouter.management_key", "invalid-management-key")
    collector = OpenRouterCollector(secret_store=secret_store)

    with respx.mock(assert_all_called=True) as mock:
        mock.get("https://openrouter.ai/api/v1/credits").respond(401)
        snapshot = collector.collect()

    assert snapshot.status == ProviderStatus.AUTH_REQUIRED
    assert snapshot.error_code == "AUTH_FAILED"
