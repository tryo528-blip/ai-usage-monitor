from __future__ import annotations

from decimal import Decimal

import respx

from ai_usage_monitor.collectors.deepseek import DeepSeekCollector
from ai_usage_monitor.domain.enums import ProviderStatus
from ai_usage_monitor.infrastructure.secret_store import FakeSecretStore


def test_deepseek_collector_parses_balance_infos() -> None:
    secret_store = FakeSecretStore()
    secret_store.set("deepseek.api_key", "test-key")
    collector = DeepSeekCollector(secret_store=secret_store)

    with respx.mock(assert_all_called=True) as mock:
        mock.get("https://api.deepseek.com/user/balance").respond(
            200,
            json={
                "is_available": True,
                "balance_infos": [
                    {
                        "currency": "USD",
                        "total_balance": "110.00",
                        "granted_balance": "10.00",
                        "topped_up_balance": "100.00",
                    }
                ],
            },
        )
        snapshot = collector.collect()

    assert snapshot.status == ProviderStatus.OK
    assert len(snapshot.balances) == 1
    assert snapshot.balances[0].currency == "USD"
    assert snapshot.balances[0].total == Decimal("110.00")
    assert snapshot.balances[0].granted == Decimal("10.00")
    assert snapshot.balances[0].topped_up == Decimal("100.00")


def test_deepseek_collector_marks_unavailable_as_critical() -> None:
    secret_store = FakeSecretStore()
    secret_store.set("deepseek.api_key", "test-key")
    collector = DeepSeekCollector(secret_store=secret_store)

    with respx.mock(assert_all_called=True) as mock:
        mock.get("https://api.deepseek.com/user/balance").respond(
            200,
            json={
                "is_available": False,
                "balance_infos": [],
            },
        )
        snapshot = collector.collect()

    assert snapshot.status == ProviderStatus.CRITICAL


def test_deepseek_collector_handles_auth_required() -> None:
    secret_store = FakeSecretStore()
    secret_store.set("deepseek.api_key", "test-key")
    collector = DeepSeekCollector(secret_store=secret_store)

    with respx.mock(assert_all_called=True) as mock:
        mock.get("https://api.deepseek.com/user/balance").respond(401)
        snapshot = collector.collect()

    assert snapshot.status == ProviderStatus.AUTH_REQUIRED
    assert snapshot.error_code == "AUTH_FAILED"
