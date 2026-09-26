from __future__ import annotations

from datetime import timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ai_usage_monitor.domain.enums import ProviderStatus
from ai_usage_monitor.domain.models import QuotaWindow, UsageSnapshot

from . import theme
from .fonts import pretendard_regular
from .theme import AlertLevel

CARD_WIDTH = 68
CARD_HEIGHT = 108
_RING_SIZE = 54
_RING_WIDTH = 4.5

_MISSING_KEY_ERROR_CODES = {
    "NOT_CONFIGURED",
    "API_KEY_NOT_CONFIGURED",
    "KEY_NOT_CONFIGURED",
    "MANAGEMENT_KEY_NOT_CONFIGURED",
}


class RingMode(StrEnum):
    ARC = "arc"
    AMOUNT = "amount"
    UNKNOWN = "unknown"


class RingGauge(QWidget):
    """A circular gauge whose arc length is the remaining share of a quota."""

    def __init__(self, accent: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.accent = accent
        self.fraction: float | None = None
        self.mode = RingMode.UNKNOWN
        self.setFixedSize(_RING_SIZE, _RING_SIZE)

    def set_state(self, mode: RingMode, fraction: float | None = None) -> None:
        self.mode = mode
        self.fraction = fraction
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        rect = QRectF(self.rect())
        if self.mode == RingMode.ARC:
            theme.draw_ring(painter, rect, self.fraction, self.accent, width=_RING_WIDTH)
        elif self.mode == RingMode.AMOUNT:
            # A balance has no ceiling, so it gets a closed, softly tinted ring
            # instead of an arc that would pretend to be a percentage.
            tint = QColor(self.accent)
            tint.setAlpha(110)
            theme.draw_ring(
                painter,
                rect,
                0,
                self.accent,
                width=_RING_WIDTH,
                track=tint.name(QColor.NameFormat.HexArgb),
            )
        else:
            theme.draw_ring(painter, rect, None, self.accent, width=_RING_WIDTH)
        painter.end()


class ProviderCard(QFrame):
    def __init__(
        self,
        title: str,
        *,
        full_name: str | None = None,
        summary_type: str,
        quota_fields: tuple[tuple[str, str], ...] = (),
        omit_missing_quota: bool = False,
        balance_display: str = "percent",
        accent: str = theme.DEFAULT_ACCENT,
    ) -> None:
        super().__init__()
        self.short_name = title
        self.full_name = full_name or title
        self.summary_type = summary_type
        self.quota_fields = quota_fields
        self.omit_missing_quota = omit_missing_quota
        self.balance_display = balance_display
        self.accent = accent
        self.level = AlertLevel.MUTED
        self.setObjectName("provider_card")
        self.setFixedSize(CARD_WIDTH, CARD_HEIGHT)
        self.setFrameStyle(QFrame.Shape.NoFrame)
        self.setStyleSheet(
            "QFrame#provider_card {"
            f"background-color: {theme.SURFACE};"
            f"border: 1px solid {theme.BORDER};"
            "border-radius: 14px;"
            "}"
            f"QFrame#provider_card:hover {{ background-color: {theme.SURFACE_HOVER}; }}"
            "QLabel { background: transparent; }"
        )
        self.setToolTip(self.full_name)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 7)
        layout.setSpacing(0)

        self.gauge = RingGauge(accent, self)
        gauge_layout = QVBoxLayout(self.gauge)
        gauge_layout.setContentsMargins(0, 0, 0, 0)
        self.value_label = QLabel("···", self.gauge)
        self.value_label.setWordWrap(True)
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value_label.setToolTip("조회 중")
        gauge_layout.addWidget(self.value_label)

        # The abbreviation's suffix ("-5", "-W") is already spelled out by the
        # window label below, so the heading shows only the provider stem.
        self.title_label = QLabel(title.split("-", 1)[0])
        self.title_label.setFixedHeight(15)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setToolTip(self.full_name)

        # Keep the long name available to callers, accessibility tools, and old
        # settings data without rendering it on the compact main card.
        self.full_name_label = QLabel(self.full_name, self)
        self.full_name_label.setToolTip(self.full_name)
        self.full_name_label.hide()

        meta = QWidget(self)
        meta.setFixedHeight(12)
        meta_layout = QHBoxLayout(meta)
        meta_layout.setContentsMargins(0, 0, 0, 0)
        meta_layout.setSpacing(3)
        meta_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.window_label = QLabel(self._window_label_text(), meta)
        self.window_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_label = QLabel("", meta)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_label.hide()
        meta_layout.addWidget(self.window_label)
        meta_layout.addWidget(self.time_label)

        layout.addWidget(self.gauge, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)
        layout.addWidget(self.title_label)
        layout.addWidget(meta)
        self._set_font_10()
        self._apply_level(AlertLevel.MUTED)

    # -- public state used by the tray -------------------------------------------------

    @property
    def fraction(self) -> float | None:
        return self.gauge.fraction if self.gauge.mode == RingMode.ARC else None

    def compact_value(self) -> str:
        """The value reduced to what fits inside a 16px tray icon."""

        text = self.value_label.text()
        if self.gauge.mode == RingMode.ARC and text.endswith("%") and "/" not in text:
            return text[:-1]
        if self.gauge.mode == RingMode.AMOUNT:
            try:
                return str(int(Decimal(text)))
            except (ArithmeticError, ValueError):
                return "$"
        return "–"

    def summary_text(self) -> str:
        value = self.value_label.text().replace("\n", " ")
        details = [self.window_label.text()]
        if self.time_label.text():
            details.append(f"{self.time_label.text()} 초기화")
        return f"{self.full_name}  {value}  ({' · '.join(details)})"

    # -- rendering ----------------------------------------------------------------------

    def set_loading(self) -> None:
        self._set_time("")
        self._set_value("···", 13, tooltip="조회 중")
        self.gauge.set_state(RingMode.UNKNOWN)
        self._apply_level(AlertLevel.MUTED)

    def set_snapshot(self, snapshot: UsageSnapshot) -> None:
        if snapshot.status in {
            ProviderStatus.AUTH_REQUIRED,
            ProviderStatus.ERROR,
            ProviderStatus.STALE,
            ProviderStatus.UNAVAILABLE,
        }:
            if self.summary_type == "quota" and snapshot.quota_windows:
                if self._render_quota(snapshot):
                    return
                self.set_no_data(self._reason(snapshot))
                return
            self.set_error(
                self._reason(snapshot),
                error_code=snapshot.error_code,
                status=snapshot.status,
            )
            return

        if snapshot.status == ProviderStatus.MANUAL or self.summary_type == "manual":
            self._render_manual(snapshot)
            return

        if self.summary_type == "balance":
            if not self._render_balance(snapshot):
                self.set_error(
                    self._reason(snapshot),
                    error_code=snapshot.error_code,
                    status=snapshot.status,
                )
            return
        if not self._render_quota(snapshot):
            if snapshot.quota_windows:
                self.set_no_data(self._reason(snapshot))
            else:
                self.set_error(
                    self._reason(snapshot),
                    error_code=snapshot.error_code,
                    status=snapshot.status,
                )

    def set_error(
        self,
        message: str,
        *,
        error_code: str | None = None,
        status: ProviderStatus = ProviderStatus.ERROR,
    ) -> None:
        self._set_time("")
        if self._is_missing_key(error_code, message):
            self._set_value("KEY", 9, tooltip=message)
        else:
            self._set_value("OFF", 9, tooltip=message)
        self.gauge.set_state(RingMode.UNKNOWN)
        level = AlertLevel.WARNING if status == ProviderStatus.AUTH_REQUIRED else AlertLevel.MUTED
        self._apply_level(level)

    def set_no_data(self, message: str) -> None:
        self._set_time("")
        self._set_value("N/A", 9, tooltip=message)
        self.gauge.set_state(RingMode.UNKNOWN)
        self._apply_level(AlertLevel.MUTED)

    def _render_quota(self, snapshot: UsageSnapshot) -> bool:
        if not self.quota_fields:
            return False
        summary = self._format_quota(snapshot)
        if summary is None:
            return False
        tooltip = summary
        balance = self._format_balance(snapshot)
        if balance:
            tooltip = f"{summary}\n{balance}"
        self._set_value(summary, self._value_point_size(summary), tooltip=tooltip)
        has_five_hour_window = any(key == "five_hour" for key, _ in self.quota_fields)
        reset_time = self._format_reset_time(snapshot) if has_five_hour_window else None
        self._set_time(reset_time or "")
        self.window_label.setText(self._window_label_text())

        remaining = self._remaining_percents(snapshot)
        if remaining:
            # The tightest window is the one that will stop work first.
            tightest = min(remaining)
            self.gauge.set_state(RingMode.ARC, tightest / 100)
            self._apply_level(theme.level_for_remaining(tightest))
        else:
            self.gauge.set_state(RingMode.UNKNOWN)
            self._apply_level(AlertLevel.OK)
        return True

    def _remaining_percents(self, snapshot: UsageSnapshot) -> list[float]:
        values = []
        for key, _ in self.quota_fields:
            quota = self._find_quota(snapshot, key)
            if quota is not None and quota.used_percent is not None:
                values.append(max(0.0, min(100.0, 100.0 - quota.used_percent)))
        return values

    def _render_balance(self, snapshot: UsageSnapshot) -> bool:
        if not snapshot.balances:
            return False
        balance = snapshot.balances[0]
        amount = balance.remaining if balance.remaining is not None else balance.total
        if amount is None:
            return False
        self._set_time("")
        if self.balance_display == "amount":
            currency = str(balance.currency).upper()
            self.window_label.setText(currency)
            amount_text = self._format_balance_amount_fixed(amount)
            tooltip = f"{amount_text} {currency}"
            if amount <= 0:
                self._set_value("$0", 11, tooltip=tooltip)
                self.gauge.set_state(RingMode.ARC, 0)
                self._apply_level(AlertLevel.CRITICAL)
                return True
            self._set_value(amount_text, 10 if len(amount_text) <= 5 else 8, tooltip=tooltip)
            self.gauge.set_state(RingMode.AMOUNT)
            self._apply_level(AlertLevel.OK)
            return True
        self.window_label.setText("BAL")
        if amount <= 0:
            self._set_value(
                "$0",
                11,
                tooltip=f"{self._format_balance_amount(amount)} {balance.currency}",
            )
            self.gauge.set_state(RingMode.ARC, 0)
            self._apply_level(AlertLevel.CRITICAL)
            return True
        if balance.total is not None and balance.used is not None and balance.total > 0:
            percent = float(amount / balance.total * 100)
        else:
            percent = float(amount) / 20 * 100
        percent = max(0.0, min(100.0, percent))
        text = f"{self._format_percent(percent)}%"
        amount_text = self._format_balance_amount(amount)
        self._set_value(
            text, self._value_point_size(text), tooltip=f"{text} · {amount_text} {balance.currency}"
        )
        self.gauge.set_state(RingMode.ARC, percent / 100)
        self._apply_level(theme.level_for_remaining(percent))
        return True

    def _render_manual(self, snapshot: UsageSnapshot) -> None:
        self._set_time("")
        self._set_value("OFF", 9, tooltip=snapshot.message or "사용량 연동 준비 중")
        self.window_label.setText("MAN")
        self.gauge.set_state(RingMode.UNKNOWN)
        self._apply_level(AlertLevel.MUTED)

    def _window_label_text(self) -> str:
        if self.summary_type == "balance":
            return "BAL"
        if self.summary_type == "manual":
            return "MAN"
        keys = {key for key, _ in self.quota_fields}
        if {"five_hour", "weekly"} <= keys:
            return "5H/W"
        if "five_hour" in keys:
            return "5H"
        return "WEEK"

    def _set_value(self, text: str, point_size: int, *, tooltip: str) -> None:
        self._set_value_font(point_size)
        self.value_label.setText(text)
        self.value_label.setToolTip(tooltip)

    def _set_time(self, text: str) -> None:
        self.time_label.setText(text)
        self.time_label.setVisible(bool(text))

    def _format_quota(self, snapshot: UsageSnapshot) -> str | None:
        quotas = {key: self._find_quota(snapshot, key) for key, _ in self.quota_fields}
        parts: list[str] = []
        for key, label in self.quota_fields:
            quota = quotas[key]
            if quota is None:
                if not self.omit_missing_quota:
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

    @staticmethod
    def _format_balance_amount_fixed(value: Decimal) -> str:
        return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"

    @classmethod
    def _format_amount(cls, value: Decimal, unit: str | None) -> str:
        number = cls._format_number(value)
        return f"{number} {unit}" if unit else number

    @staticmethod
    def _format_percent(value: float) -> str:
        rounded = Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return str(int(rounded))

    @classmethod
    def _format_remaining_percent(cls, used_percent: float) -> str:
        return cls._format_percent(max(0.0, min(100.0, 100.0 - used_percent)))

    def _set_font_10(self) -> None:
        font = pretendard_regular(10)
        self.setFont(font)
        self.title_label.setFont(theme.bold_font(font, 8))
        small_font = QFont(font)
        small_font.setPointSize(7)
        self.full_name_label.setFont(small_font)
        self.time_label.setFont(small_font)
        self.window_label.setFont(small_font)
        self._set_value_font(13)

    def _set_value_font(self, point_size: int) -> None:
        self.value_label.setFont(theme.bold_font(self.font(), point_size))

    def _apply_level(self, level: AlertLevel) -> None:
        self.level = level
        title_color = theme.TEXT_MUTED if level == AlertLevel.MUTED else self.accent
        self.title_label.setStyleSheet(f"color: {title_color};")
        self.window_label.setStyleSheet(f"color: {theme.TEXT_FAINT};")
        self.time_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        self.value_label.setStyleSheet(f"color: {theme.LEVEL_TEXT_COLORS[level]};")

    @staticmethod
    def _value_point_size(text: str) -> int:
        if "\n" in text:
            return 7
        if "/" in text:
            return 7
        if len(text) > 4:
            return 8
        if len(text) == 4:
            return 11
        return 13

    @staticmethod
    def _is_missing_key(error_code: str | None, message: str) -> bool:
        normalized_code = (error_code or "").upper()
        if normalized_code in _MISSING_KEY_ERROR_CODES:
            return True
        if normalized_code.endswith("_KEY_NOT_CONFIGURED"):
            return True
        normalized_message = message.lower()
        mentions_key = "api 키" in normalized_message or "api key" in normalized_message
        return mentions_key and any(
            marker in normalized_message
            for marker in ("없", "입력", "설정", "not configured", "missing")
        )
