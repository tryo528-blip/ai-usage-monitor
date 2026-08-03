from __future__ import annotations

from ai_usage_monitor.collectors.mock import MockCollector
from ai_usage_monitor.services.collector_manager import CollectorManager


def test_collector_manager_refreshes_each_provider_once() -> None:
    manager = CollectorManager([MockCollector()])
    results = []

    def callback(result) -> None:
        results.append(result.snapshot.provider_id)

    manager.register_callback(callback)
    manager.refresh()

    assert results
