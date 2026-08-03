from __future__ import annotations

from datetime import datetime, timezone
from threading import Event
from time import monotonic

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


class BlockingCollector(Collector):
    provider_id = "blocking"
    provider_name = "Blocking"

    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()
        self.calls = 0

    def is_configured(self) -> bool:
        return True

    def collect(self) -> UsageSnapshot:
        self.calls += 1
        self.started.set()
        self.release.wait(timeout=5)
        return UsageSnapshot(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            source_type=SourceType.OFFICIAL_API,
            status=ProviderStatus.OK,
            collected_at=datetime.now(timezone.utc),
        )


class RetryCollector(Collector):
    provider_id = "retry"
    provider_name = "Retry"

    def __init__(self) -> None:
        self.calls = 0

    def is_configured(self) -> bool:
        return True

    def collect(self) -> UsageSnapshot:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("first attempt failed")
        return UsageSnapshot(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            source_type=SourceType.OFFICIAL_API,
            status=ProviderStatus.OK,
            collected_at=datetime.now(timezone.utc),
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
        results.append(result)

    manager.register_callback(callback)
    manager.refresh()

    qtbot.waitUntil(lambda: len(results) == 2, timeout=5000)
    results_by_provider = {result.provider_id: result.snapshot for result in results}
    assert set(results_by_provider) == {"failing", "working"}
    assert results_by_provider["failing"].status == ProviderStatus.ERROR
    assert results_by_provider["working"].status == ProviderStatus.OK


def test_collector_manager_refresh_returns_immediately_and_blocks_duplicates(qtbot) -> None:
    QApplication.instance() or QApplication([])
    collector = BlockingCollector()
    manager = CollectorManager([collector])
    results = []
    manager.register_callback(lambda result: results.append(result.provider_id))

    started_at = monotonic()
    manager.refresh()
    elapsed = monotonic() - started_at

    assert elapsed < 0.2
    assert collector.started.wait(timeout=1)
    manager.refresh()
    assert collector.calls == 1

    collector.release.set()
    qtbot.waitUntil(lambda: results == ["blocking"], timeout=5000)
    qtbot.waitUntil(lambda: not manager._inflight, timeout=5000)


def test_collector_manager_releases_inflight_after_failure_and_allows_retry(qtbot) -> None:
    QApplication.instance() or QApplication([])
    collector = RetryCollector()
    manager = CollectorManager([collector])
    results = []
    manager.register_callback(lambda result: results.append(result.snapshot))

    manager.refresh()
    qtbot.waitUntil(lambda: len(results) == 1, timeout=5000)
    qtbot.waitUntil(lambda: not manager._inflight, timeout=5000)
    assert results[0].status == ProviderStatus.ERROR

    manager.refresh()
    qtbot.waitUntil(lambda: len(results) == 2, timeout=5000)
    assert results[1].status == ProviderStatus.OK
    assert collector.calls == 2
