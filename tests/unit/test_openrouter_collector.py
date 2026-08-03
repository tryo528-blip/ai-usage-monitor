from __future__ import annotations

import respx

from ai_usage_monitor.collectors.openrouter import OpenRouterCollector
from ai_usage_monitor.domain.enums import ProviderStatus
from ai_usage_monitor.infrastructure.secret_store import FakeSecretStore


def test_openrouter_collector_reads_key_and_credits() -> None:
    secret_store = FakeSecretStore()
    secret_store.set("openrouter.api_key", "test-api-key")
    secret_store.set("openrouter.management_key", "test-management-key")
    collector = OpenRouterCollector(secret_store=secret_store)

    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://openrouter.ai/api/v1/key").respond(
            200,
            json={
                "data": {
                    "usage": {
                        "daily": {"used": 10, "limit": 100, "remaining": 90, "unit": "tokens"},
                        "weekly": {"used": 40, "limit": 100, "remaining": 60, "unit": "tokens"},
                        "monthly": {"used": 30, "limit": 100, "remaining": 70, "unit": "tokens"},
                    }
                }
            },
        )
        mock.get("https://openrouter.ai/api/v1/credits").respond(
            200,
            json={"data": {"currency": "USD", "total": 100, "remaining": 7.84, "used": 92.16}},
        )

        snapshot = collector.collect()

    assert snapshot.status == ProviderStatus.OK
    assert len(snapshot.quota_windows) == 3
    assert len(snapshot.balances) == 1


def test_openrouter_collector_handles_auth_required() -> None:
    secret_store = FakeSecretStore()
    secret_store.set("openrouter.api_key", "test-api-key")
    collector = OpenRouterCollector(secret_store=secret_store)

    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://openrouter.ai/api/v1/key").respond(401)
        snapshot = collector.collect()

    assert snapshot.status == ProviderStatus.AUTH_REQUIRED
    assert snapshot.error_code == "AUTH_FAILED"
