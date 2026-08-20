from __future__ import annotations

from datetime import timedelta, timezone
from decimal import Decimal

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from ai_usage_monitor.domain.enums import ProviderStatus
from ai_usage_monitor.domain.models import QuotaWindow, UsageSnapshot


class VerticalUsageBar(QWidget):
    def __init__(self, *, color: str, light_color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.color = QColor(color)
        self.light_color = QColor(light_color)
        self.remaining = 0.0
        self.setFixedSize(26, 88)

    def set_remaining(self, value: float | None) -> None:
        self.remaining = max(0.0, min(100.0, value or 0.0))
        self.update()

    def clear(self) -> None:
        self.remaining = 0.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(6, 3, 16, self.height() - 6)
        painter.setPen(QPen(self.light_color.darker(120), 1))
        painter.setBrush(self.light_color)
        painter.drawRoundedRect(track, 8, 8)

        fill_height = track.height() * self.remaining / 100
        if fill_height <= 0:
            return
        fill = QRectF(track.left(), track.bottom() - fill_height, track.width(), fill_height)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.color)
        painter.save()
        painter.setClipRect(track)
        painter.drawRoundedRect(fill, 8, 8)
        painter.restore()


class ProviderCard(QFrame):
    def __init__(
        self,
        title: str,
        *,
        summary_type: str,
        quota_fields: tuple[tuple[str, str], ...] = (),
        bar_color: str = "#1565c0",
        bar_light_color: str = "#bbdefb",
    ) -> None:
        super().__init__()
        self.summary_type = summary_type
        self.quota_fields = quota_fields
        self.setFixedSize(38, 148)
        self.setFrameStyle(QFrame.Shape.NoFrame)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.title_label = QLabel(title)
        self.title_label.setFixedHeight(21)
        self.title_label.setWordWrap(True)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.time_label = QLabel("", self)
        self.time_label.setFixedHeight(14)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)

        self.bar = VerticalUsageBar(
            color=bar_color,
            light_color=bar_light_color,
            parent=self,
        )
        self.value_label = QLabel("조회 중", self)
        self.value_label.setFixedHeight(18)
        self.value_label.setContentsMargins(0, 2, 0, 0)
        self.value_label.setWordWrap(True)
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        layout.addWidget(self.time_label)
        layout.addWidget(self.bar, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.value_label)
        layout.addSpacing(-3)
        layout.addWidget(self.title_label)
        layout.addStretch(0)
        self._set_font_10()

    def set_loading(self) -> None:
        self.time_label.clear()
        self.bar.clear()
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
                if self._render_quota(snapshot):
                    self._apply_status_style(snapshot.status)
                    return
            self.set_error(self._reason(snapshot))
            return

        if self.summary_type == "balance":
            if not self._render_balance(snapshot):
                self.set_error(self._reason(snapshot))
                return
        elif not self._render_quota(snapshot):
            self.set_error(self._reason(snapshot))
            return
        self._apply_status_style(snapshot.status)

    def set_error(self, message: str) -> None:
        self.time_label.clear()
        self.bar.clear()
        self.value_label.setText(message)
        self.value_label.setToolTip(message)
        self._apply_status_style(ProviderStatus.ERROR)

    def _render_quota(self, snapshot: UsageSnapshot) -> bool:
        if not self.quota_fields:
            return False
        summary = self._format_quota(snapshot)
        if summary is None:
            return False
        self.value_label.setText(summary)
        self.value_label.setToolTip(summary)
        has_five_hour_window = any(key == "five_hour" for key, _ in self.quota_fields)
        reset_time = self._format_reset_time(snapshot) if has_five_hour_window else None
        self.time_label.setText(reset_time or "")
        quota = self._find_quota(snapshot, self.quota_fields[0][0])
        if quota is not None and quota.used_percent is not None:
            self.bar.set_remaining(100.0 - quota.used_percent)
        else:
            self.bar.clear()
        return True

    def _render_balance(self, snapshot: UsageSnapshot) -> bool:
        if not snapshot.balances:
            return False
        balance = snapshot.balances[0]
        amount = balance.remaining if balance.remaining is not None else balance.total
        if amount is None:
            return False
        percent = max(0.0, min(100.0, float(amount) / 20 * 100))
        text = f"{self._format_percent(percent)}%"
        self.time_label.clear()
        self.value_label.setText(text)
        self.value_label.setToolTip(text.replace("\n", " "))
        self.bar.set_remaining(float(amount) / 20 * 100)
        return True

    def _format_quota(self, snapshot: UsageSnapshot) -> str | None:
        quotas = {key: self._find_quota(snapshot, key) for key, _ in self.quota_fields}
        parts: list[str] = []
        for key, label in self.quota_fields:
            quota = quotas[key]
            if quota is None:
                parts.append(self._format_missing_quota(snapshot, key, label))
                continue
            if quota.used_percent is not None:
                parts.append(f"{self._format_remaining_percent(quota.used_percent)}%")
                continue
            value = self._format_quota_value(quota, label)
            if value is None:
                parts.append(self._format_missing_quota(snapshot, key, label))
                continue
            parts.append(value.replace(" \ub0a8\uc74c", "").replace("5H ", ""))
        return " / ".join(parts) if parts else None

    @staticmethod
    def _format_missing_quota(snapshot: UsageSnapshot, key: str, label: str) -> str:
        if snapshot.error_code == "ACTIVE_BLOCK_MISSING" and key == "five_hour":
            return "5H 없음"
        return f"{label}: 조회 불가"

    @classmethod
    def _format_quota_value(cls, quota: QuotaWindow, label: str) -> str | None:
        if quota.used_percent is not None:
            value = f"{cls._format_remaining_percent(quota.used_percent)}% 남음"
        elif quota.used_value is not None and quota.limit_value is not None:
            value = (
                f"{cls._format_amount(quota.used_value, quota.unit)}"
                f"/{cls._format_amount(quota.limit_value, quota.unit)} 사용"
            )
        elif quota.remaining_value is not None and quota.limit_value is not None:
            value = (
                f"잔여 {cls._format_amount(quota.remaining_value, quota.unit)}"
                f"/{cls._format_amount(quota.limit_value, quota.unit)}"
            )
        elif quota.limit_value is not None:
            value = cls._format_amount(quota.limit_value, quota.unit)
        elif quota.remaining_value is not None:
            value = f"잔여 {cls._format_amount(quota.remaining_value, quota.unit)}"
        elif quota.used_value is not None:
            value = f"{cls._format_amount(quota.used_value, quota.unit)} 사용"
        else:
            return None

        return value

    @classmethod
    def _format_reset_time(cls, snapshot: UsageSnapshot) -> str | None:
        quota = cls._find_quota(snapshot, "five_hour")
        if quota is None or quota.resets_at is None:
            return None
        seoul_time = quota.resets_at.astimezone(timezone(timedelta(hours=9)))
        return seoul_time.strftime("%H:%M")

    @classmethod
    def _format_balance(cls, snapshot: UsageSnapshot) -> str | None:
        values = []
        for balance in snapshot.balances:
            amount = balance.remaining if balance.remaining is not None else balance.total
            if amount is not None:
                values.append(f"{cls._format_balance_amount(amount)} {balance.currency}")
        return ", ".join(values) if values else None

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
        return "조회 불가"

    @staticmethod
    def _format_number(value: Decimal) -> str:
        text = format(value, "f")
        fraction = ""
        if "." in text:
            text, fraction = text.split(".", 1)
            fraction = fraction.rstrip("0")
        whole = f"{int(text or '0'):,}"
        return f"{whole}.{fraction}" if fraction else whole

    @staticmethod
    def _format_balance_amount(value: Decimal) -> str:
        return f"{value:.2f}".rstrip("0").rstrip(".")

    @classmethod
    def _format_amount(cls, value: Decimal, unit: str | None) -> str:
        number = cls._format_number(value)
        return f"{number} {unit}" if unit else number

    @staticmethod
    def _format_percent(value: float) -> str:
        text = f"{value:.1f}".rstrip("0").rstrip(".")
        return text or "0"

    @classmethod
    def _format_remaining_percent(cls, used_percent: float) -> str:
        return cls._format_percent(max(0.0, min(100.0, 100.0 - used_percent)))

    def _set_font_10(self) -> None:
        font = QFont(self.font())
        font.setPointSize(10)
        self.setFont(font)
        card_font = QFont(font)
        card_font.setPointSize(8)
        self.title_label.setFont(card_font)
        self.time_label.setFont(card_font)
        self.value_label.setFont(card_font)

    def _apply_status_style(self, status: ProviderStatus) -> None:
        palette = {
            ProviderStatus.OK: "#202124",
            ProviderStatus.WARNING: "#f9a825",
            ProviderStatus.CRITICAL: "#c62828",
            ProviderStatus.AUTH_REQUIRED: "#ef6c00",
            ProviderStatus.UNAVAILABLE: "#616161",
            ProviderStatus.ERROR: "#b71c1c",
            ProviderStatus.STALE: "#6d4c41",
            ProviderStatus.MANUAL: "#1565c0",
        }
        color = palette.get(status, "#000000")
        self.time_label.setStyleSheet(f"color: {color};")
        self.value_label.setStyleSheet(f"color: {color};")
