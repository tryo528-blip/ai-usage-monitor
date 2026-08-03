from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtWidgets import QApplication

from ai_usage_monitor.collectors.base import Collector
from ai_usage_monitor.collectors.mock import MockCollector
from ai_usage_monitor.domain.enums import ProviderStatus, SourceType
from ai_usage_monitor.domain.models import UsageSnapshot
from ai_usage_monitor.services.collector_manager import CollectorManager


class FailingCollector(Collector):
    provider_id = "failing"
    provider_name = "Failing"

    def is_configured(self) -> bool:
        return True

    def collect(self) -> UsageSnapshot:
        raise RuntimeError("boom")


class WorkingCollector(Collector):
    provider_id = "working"
    provider_name = "Working"

    def is_configured(self) -> bool:
        return True

    def collect(self) -> UsageSnapshot:
        return UsageSnapshot(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            source_type=SourceType.OFFICIAL_API,
            status=ProviderStatus.OK,
            collected_at=datetime.now(timezone.utc),
            message="정상 조회",
        )


def test_collector_manager_refreshes_each_provider_once(qtbot) -> None:
    QApplication.instance() or QApplication([])
    manager = CollectorManager([MockCollector()])
    results = []

    def callback(result) -> None:
        results.append(result.snapshot.provider_id)

    manager.register_callback(callback)
    manager.refresh()

    qtbot.waitUntil(lambda: len(results) == 1, timeout=5000)
    assert results == ["mock"]


def test_collector_manager_handles_one_failure_without_blocking_others(qtbot) -> None:
    QApplication.instance() or QApplication([])
    manager = CollectorManager([FailingCollector(), WorkingCollector()])
    results = []

    def callback(result) -> None:
        results.append(result.provider_id)

    manager.register_callback(callback)
    manager.refresh()

    qtbot.waitUntil(lambda: len(results) == 2, timeout=5000)
    assert set(results) == {"failing", "working"}
    assert "failing" in set(results)
    assert "working" in set(results)
