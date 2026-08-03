from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QCoreApplication, QThreadPool

from ai_usage_monitor.collectors.base import Collector
from ai_usage_monitor.domain.models import UsageSnapshot
from ai_usage_monitor.workers.collector_worker import CollectorWorker


@dataclass
class CollectionResult:
    provider_id: str
    snapshot: UsageSnapshot


class CollectorManager:
    def __init__(self, collectors: list[Collector]) -> None:
        self.collectors = collectors
        self._inflight: set[str] = set()
        self._callbacks: list[Callable[[CollectionResult], None]] = []
        self._thread_pool = QThreadPool.globalInstance()

    def register_callback(self, callback: Callable[[CollectionResult], None]) -> None:
        self._callbacks.append(callback)

    def refresh(self, provider_id: str | None = None) -> None:
        selected = self.collectors
        if provider_id is not None:
            selected = [
                collector for collector in self.collectors if collector.provider_id == provider_id
            ]

        app = QCoreApplication.instance()
        if app is None:
            for collector in selected:
                snapshot = collector.collect()
                self._handle_finished(collector.provider_id, snapshot)
            return

        for collector in selected:
            if collector.provider_id in self._inflight:
                continue
            self._inflight.add(collector.provider_id)
            worker = CollectorWorker(collector)
            worker.signals.finished.connect(self._handle_finished)
            self._thread_pool.start(worker)
        self._thread_pool.waitForDone()

    def _handle_finished(self, provider_id: str, snapshot: UsageSnapshot) -> None:
        self._inflight.discard(provider_id)
        for callback in self._callbacks:
            callback(CollectionResult(provider_id=provider_id, snapshot=snapshot))
