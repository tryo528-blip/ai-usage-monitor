from __future__ import annotations

import respx

from ai_usage_monitor.collectors.deepseek import DeepSeekCollector
from ai_usage_monitor.domain.enums import ProviderStatus
from ai_usage_monitor.infrastructure.secret_store import FakeSecretStore


def test_deepseek_collector_reads_balances() -> None:
    secret_store = FakeSecretStore()
    secret_store.set("deepseek.api_key", "test-key")
    collector = DeepSeekCollector(secret_store=secret_store)

    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://api.deepseek.com/user/balance").respond(
            200,
            json={
                "data": [
                    {"currency": "USD", "total": "100", "remaining": "16.32", "used": "83.68"},
                    {"currency": "CNY", "total": "200", "remaining": "150", "used": "50"},
                ]
            },
        )
        snapshot = collector.collect()

    assert snapshot.status == ProviderStatus.OK
    assert len(snapshot.balances) == 2


def test_deepseek_collector_handles_auth_required() -> None:
    secret_store = FakeSecretStore()
    secret_store.set("deepseek.api_key", "test-key")
    collector = DeepSeekCollector(secret_store=secret_store)

    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://api.deepseek.com/user/balance").respond(401)
        snapshot = collector.collect()

    assert snapshot.status == ProviderStatus.AUTH_REQUIRED
    assert snapshot.error_code == "AUTH_FAILED"
