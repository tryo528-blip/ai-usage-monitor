from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import QObject, QRunnable, Signal

from ai_usage_monitor.collectors.base import Collector
from ai_usage_monitor.domain.enums import ProviderStatus, SourceType
from ai_usage_monitor.domain.models import UsageSnapshot


class CollectorWorkerSignals(QObject):
    success = Signal(str, object)
    failure = Signal(str, object)
    completed = Signal(str)


class CollectorWorker(QRunnable):
    def __init__(self, collector: Collector) -> None:
        super().__init__()
        self.collector = collector
        self.signals = CollectorWorkerSignals()

    def run(self) -> None:
        try:
            snapshot = self.collector.collect()
        except Exception as exc:
            snapshot = UsageSnapshot(
                provider_id=self.collector.provider_id,
                provider_name=self.collector.provider_name,
                source_type=SourceType.OFFICIAL_API,
                status=ProviderStatus.ERROR,
                collected_at=datetime.now(timezone.utc),
                message=f"수집 중 오류: {exc}",
                error_code="UNKNOWN_ERROR",
            )
            self.signals.failure.emit(self.collector.provider_id, snapshot)
        else:
            self.signals.success.emit(self.collector.provider_id, snapshot)
        finally:
            self.signals.completed.emit(self.collector.provider_id)
