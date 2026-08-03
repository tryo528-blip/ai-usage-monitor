from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Signal

from ai_usage_monitor.collectors.base import Collector


class CollectorWorkerSignals(QObject):
    finished = Signal(str, object)


class CollectorWorker(QRunnable):
    def __init__(self, collector: Collector) -> None:
        super().__init__()
        self.collector = collector
        self.signals = CollectorWorkerSignals()

    def run(self) -> None:
        snapshot = self.collector.collect()
        self.signals.finished.emit(self.collector.provider_id, snapshot)
