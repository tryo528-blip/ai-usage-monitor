from ai_usage_monitor.collectors.manual import ManualCollector
from ai_usage_monitor.domain.enums import ProviderStatus
from ai_usage_monitor.infrastructure.secret_store import FakeSecretStore


def test_manual_collector_reports_missing_key() -> None:
    secret_store = FakeSecretStore()
    collector = ManualCollector(
        "zai",
        "Z.AI",
        secret_store=secret_store,
        secret_key="zai.api_key",
    )

    snapshot = collector.collect()

    assert snapshot.status == ProviderStatus.AUTH_REQUIRED
    assert snapshot.error_code == "NOT_CONFIGURED"
    assert "API 키" in snapshot.message


def test_manual_collector_reports_unconnected_after_key_is_saved() -> None:
    secret_store = FakeSecretStore()
    secret_store.set("zai.api_key", "stored-secret")
    collector = ManualCollector(
        "zai",
        "Z.AI",
        secret_store=secret_store,
        secret_key="zai.api_key",
    )

    snapshot = collector.collect()

    assert snapshot.status == ProviderStatus.MANUAL
    assert snapshot.error_code is None
    assert "수집기는 아직 연결되지 않았습니다" in snapshot.message
