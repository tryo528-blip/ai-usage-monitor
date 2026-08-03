from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QCoreApplication, QObject, QThreadPool

from ai_usage_monitor.collectors.base import Collector
from ai_usage_monitor.domain.models import UsageSnapshot
from ai_usage_monitor.workers.collector_worker import CollectorWorker


@dataclass
class CollectionResult:
    provider_id: str
    snapshot: UsageSnapshot


class CollectorManager(QObject):
    def __init__(self, collectors: list[Collector]) -> None:
        super().__init__()
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

        if QCoreApplication.instance() is None:
            for collector in selected:
                if collector.provider_id in self._inflight:
                    continue
                self._inflight.add(collector.provider_id)
                try:
                    snapshot = collector.collect()
                except Exception as exc:
                    snapshot = self._build_error_snapshot(collector, exc)
                self._handle_result(collector.provider_id, snapshot)
                self._inflight.discard(collector.provider_id)
            return

        for collector in selected:
            if collector.provider_id in self._inflight:
                continue
            self._inflight.add(collector.provider_id)
            worker = CollectorWorker(collector)
            worker.signals.success.connect(self._handle_success)
            worker.signals.failure.connect(self._handle_failure)
            worker.signals.completed.connect(self._handle_completed)
            self._thread_pool.start(worker)

    def _handle_success(self, provider_id: str, snapshot: UsageSnapshot) -> None:
        self._handle_result(provider_id, snapshot)

    def _handle_failure(self, provider_id: str, snapshot: UsageSnapshot) -> None:
        self._handle_result(provider_id, snapshot)

    def _handle_completed(self, provider_id: str) -> None:
        self._inflight.discard(provider_id)

    def _handle_result(self, provider_id: str, snapshot: UsageSnapshot) -> None:
        for callback in self._callbacks:
            callback(CollectionResult(provider_id=provider_id, snapshot=snapshot))

    @staticmethod
    def _build_error_snapshot(collector: Collector, exc: Exception) -> UsageSnapshot:
        from datetime import datetime, timezone

        from ai_usage_monitor.domain.enums import ProviderStatus, SourceType

        return UsageSnapshot(
            provider_id=collector.provider_id,
            provider_name=collector.provider_name,
            source_type=SourceType.OFFICIAL_API,
            status=ProviderStatus.ERROR,
            collected_at=datetime.now(timezone.utc),
            message=f"수집 중 오류: {exc}",
            error_code="UNKNOWN_ERROR",
        )
