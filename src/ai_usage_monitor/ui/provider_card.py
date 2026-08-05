from __future__ import annotations

from datetime import timedelta, timezone
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

from ai_usage_monitor.domain.enums import ProviderStatus
from ai_usage_monitor.domain.models import QuotaWindow, UsageSnapshot


class ProviderCard(QFrame):
    def __init__(
        self,
        title: str,
        *,
        summary_type: str,
        quota_fields: tuple[tuple[str, str], ...] = (),
    ) -> None:
        super().__init__()
        self.summary_type = summary_type
        self.quota_fields = quota_fields
        self.setFrameStyle(QFrame.Shape.StyledPanel)
        self.setFixedHeight(28)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(8)

        self.title_label = QLabel(title)
        self.title_label.setFixedWidth(72)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.value_label = QLabel("조회 중")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label, 1)
        self._set_font_10()

    def set_loading(self) -> None:
        self.value_label.setText("조회 중")
        self._apply_status_style(ProviderStatus.OK)

    def set_snapshot(self, snapshot: UsageSnapshot) -> None:
        if snapshot.status in {
            ProviderStatus.AUTH_REQUIRED,
            ProviderStatus.ERROR,
            ProviderStatus.STALE,
            ProviderStatus.UNAVAILABLE,
        }:
            if self.summary_type == "quota" and snapshot.quota_windows:
                summary = self._format_quota(snapshot)
                if summary is not None:
                    self.value_label.setText(summary)
                    self._apply_status_style(snapshot.status)
                    return
            self.set_error(self._reason(snapshot))
            return

        if self.summary_type == "balance":
            summary = self._format_balance(snapshot)
        else:
            summary = self._format_quota(snapshot)

        if summary is None:
            self.set_error(self._reason(snapshot))
            return

        self.value_label.setText(summary)
        self._apply_status_style(snapshot.status)

    def set_error(self, message: str) -> None:
        self.value_label.setText(message)
        self._apply_status_style(ProviderStatus.ERROR)

    def _format_quota(self, snapshot: UsageSnapshot) -> str | None:
        parts: list[str] = []
        for key, label in self.quota_fields:
            quota = self._find_quota(snapshot, key)
            if quota is None:
                parts.append(self._format_missing_quota(snapshot, key, label))
                continue
            value = self._format_quota_value(quota, label)
            if value is None:
                parts.append(self._format_missing_quota(snapshot, key, label))
                continue
            parts.append(value)
        return " / ".join(parts) if parts else None

    @staticmethod
    def _format_missing_quota(snapshot: UsageSnapshot, key: str, label: str) -> str:
        if snapshot.error_code == "ACTIVE_BLOCK_MISSING" and key == "five_hour":
            return f"{label}: 활성 블록 없음"
        return f"{label}: 조회 불가"

    @classmethod
    def _format_quota_value(cls, quota: QuotaWindow, label: str) -> str | None:
        if quota.used_percent is not None:
            value = f"{label}: {cls._format_percent(quota.used_percent)}% 사용"
        elif quota.used_value is not None and quota.limit_value is not None:
            value = (
                f"{label}: {cls._format_amount(quota.used_value, quota.unit)}"
                f"/{cls._format_amount(quota.limit_value, quota.unit)} 사용"
            )
        elif quota.remaining_value is not None and quota.limit_value is not None:
            value = (
                f"{label}: 잔여 {cls._format_amount(quota.remaining_value, quota.unit)}"
                f"/{cls._format_amount(quota.limit_value, quota.unit)}"
            )
        elif quota.limit_value is not None:
            value = f"{label}: {cls._format_amount(quota.limit_value, quota.unit)}"
        elif quota.remaining_value is not None:
            value = f"{label}: 잔여 {cls._format_amount(quota.remaining_value, quota.unit)}"
        elif quota.used_value is not None:
            value = f"{label}: {cls._format_amount(quota.used_value, quota.unit)} 사용"
        else:
            return None

        if quota.resets_at is not None:
            seoul_time = quota.resets_at.astimezone(timezone(timedelta(hours=9)))
            value += f" (리셋 {seoul_time.strftime('%m-%d %H:%M')} KST)"
        return value

    @classmethod
    def _format_balance(cls, snapshot: UsageSnapshot) -> str | None:
        if not snapshot.balances:
            return None
        values = []
        for balance in snapshot.balances:
            amount = balance.remaining if balance.remaining is not None else balance.total
            if amount is None:
                continue
            values.append(f"{cls._format_number(amount)} {balance.currency}")
        return f"잔액: {', '.join(values)}" if values else None

    @staticmethod
    def _find_quota(snapshot: UsageSnapshot, key: str) -> QuotaWindow | None:
        normalized_key = key.lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "weekly": {"weekly", "week", "7day", "7_day"},
            "five_hour": {"five_hour", "5h", "5_hour", "5-hour"},
        }
        candidates = aliases.get(normalized_key, {normalized_key})
        for quota in snapshot.quota_windows:
            quota_key = quota.key.lower().replace("-", "_").replace(" ", "_")
            quota_label = quota.label.lower()
            if quota_key in candidates or any(candidate in quota_label for candidate in candidates):
                return quota
        return None

    def _reason(self, snapshot: UsageSnapshot) -> str:
        if snapshot.message and snapshot.message != "정상 조회":
            return snapshot.message
        if self.summary_type == "balance":
            return "잔액 조회 불가"
        labels = " / ".join(label for _, label in self.quota_fields)
        return f"{labels} 조회 불가"

    @staticmethod
    def _format_number(value: Decimal) -> str:
        text = format(value, "f")
        fraction = ""
        if "." in text:
            text, fraction = text.split(".", 1)
            fraction = fraction.rstrip("0")
        whole = f"{int(text or '0'):,}"
        return f"{whole}.{fraction}" if fraction else whole

    @classmethod
    def _format_amount(cls, value: Decimal, unit: str | None) -> str:
        number = cls._format_number(value)
        return f"{number} {unit}" if unit else number

    @staticmethod
    def _format_percent(value: float) -> str:
        text = f"{value:.1f}".rstrip("0").rstrip(".")
        return text or "0"

    def _set_font_10(self) -> None:
        font = QFont(self.font())
        font.setPointSize(10)
        self.setFont(font)
        self.title_label.setFont(font)
        self.value_label.setFont(font)

    def _apply_status_style(self, status: ProviderStatus) -> None:
        palette = {
            ProviderStatus.OK: "#2e7d32",
            ProviderStatus.WARNING: "#f9a825",
            ProviderStatus.CRITICAL: "#c62828",
            ProviderStatus.AUTH_REQUIRED: "#ef6c00",
            ProviderStatus.UNAVAILABLE: "#616161",
            ProviderStatus.ERROR: "#b71c1c",
            ProviderStatus.STALE: "#6d4c41",
            ProviderStatus.MANUAL: "#1565c0",
        }
        color = palette.get(status, "#000000")
        self.value_label.setStyleSheet(f"color: {color};")
