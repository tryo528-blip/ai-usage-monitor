from __future__ import annotations

from abc import ABC, abstractmethod

from ai_usage_monitor.domain.models import UsageSnapshot


class Collector(ABC):
    provider_id: str
    provider_name: str

    @abstractmethod
    def is_configured(self) -> bool:
        """Return whether the collector has required local or credential setup."""

    @abstractmethod
    def collect(self) -> UsageSnapshot:
        """Fetch and normalize a snapshot."""
