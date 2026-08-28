from __future__ import annotations

from datetime import timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ai_usage_monitor.domain.enums import ProviderStatus
from ai_usage_monitor.domain.models import QuotaWindow, UsageSnapshot

_MISSING_KEY_ERROR_CODES = {
    "NOT_CONFIGURED",
    "API_KEY_NOT_CONFIGURED",
    "KEY_NOT_CONFIGURED",
    "MANAGEMENT_KEY_NOT_CONFIGURED",
}


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
    ) -> None:
        super().__init__()
        self.short_name = title
        self.full_name = full_name or title
        self.summary_type = summary_type
        self.quota_fields = quota_fields
        self.omit_missing_quota = omit_missing_quota
        self.balance_display = balance_display
        self.setObjectName("provider_card")
        self.setFixedSize(62, 104)
        self.setFrameStyle(QFrame.Shape.NoFrame)
        self.setStyleSheet(
            "QFrame#provider_card {"
            "background-color: rgba(18, 25, 42, 246);"
            "border: 1px solid #263654;"
            "border-radius: 14px;"
            "}"
        )
        self.setToolTip(self.full_name)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 7, 6, 7)
        layout.setSpacing(0)

        heading = QWidget(self)
        heading.setFixedHeight(14)
        heading_layout = QHBoxLayout(heading)
        heading_layout.setContentsMargins(0, 0, 0, 0)
        heading_layout.setSpacing(3)
        heading_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.status_dot = QLabel("●", self)
        self.status_dot.setFixedSize(7, 14)
        self.status_dot.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.title_label = QLabel(title)
        self.title_label.setFixedHeight(14)
        self.title_label.setWordWrap(False)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setToolTip(self.full_name)
        heading_layout.addWidget(self.status_dot)
        heading_layout.addWidget(self.title_label)

        # Keep the long name available to callers, accessibility tools, and old
        # settings data without rendering it on the compact main card.
        self.full_name_label = QLabel(self.full_name, self)
        self.full_name_label.setToolTip(self.full_name)
        self.full_name_label.hide()

        self.time_label = QLabel("", self)
        self.time_label.setFixedHeight(9)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.value_label = QLabel("···", self)
        self.value_label.setFixedHeight(34)
        self.value_label.setWordWrap(True)
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.value_label.setToolTip("조회 중")

        self.window_label = QLabel(self._window_label_text(), self)
        self.window_label.setFixedHeight(10)
        self.window_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(heading)
        layout.addWidget(self.time_label)
        layout.addStretch(1)
        layout.addWidget(self.value_label)
        layout.addStretch(1)
        layout.addWidget(self.window_label)
        self._set_font_10()
        self._apply_status_style(ProviderStatus.OK)

    def set_loading(self) -> None:
        self.time_label.clear()
        self.value_label.setText("···")
        self.value_label.setToolTip("조회 중")
        self._set_value_font(15)
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
            if self.summary_type == "quota" and snapshot.quota_windows:
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
            self._apply_status_style(snapshot.status)
            return

        if self.summary_type == "balance":
            if not self._render_balance(snapshot):
                self.set_error(
                    self._reason(snapshot),
                    error_code=snapshot.error_code,
                    status=snapshot.status,
                )
                return
        elif not self._render_quota(snapshot):
            if snapshot.quota_windows:
                self.set_no_data(self._reason(snapshot))
            else:
                self.set_error(
                    self._reason(snapshot),
                    error_code=snapshot.error_code,
                    status=snapshot.status,
                )
            return
        self._apply_status_style(snapshot.status)

    def set_error(
        self,
        message: str,
        *,
        error_code: str | None = None,
        status: ProviderStatus = ProviderStatus.ERROR,
    ) -> None:
        self.time_label.clear()
        if self._is_missing_key(error_code, message):
            self.value_label.setText("NO\nKEY")
            self._set_value_font(8)
        else:
            self.value_label.setText("NOT\nCONNECTED")
            self._set_value_font(6)
        self.value_label.setToolTip(message)
        self._apply_status_style(status)

    def set_no_data(self, message: str) -> None:
        self.time_label.clear()
        self.value_label.setText("NO\nDATA")
        self.value_label.setToolTip(message)
        self._set_value_font(8)
        self._apply_status_style(ProviderStatus.UNAVAILABLE)

    def _render_quota(self, snapshot: UsageSnapshot) -> bool:
        if not self.quota_fields:
            return False
        summary = self._format_quota(snapshot)
        if summary is None:
            return False
        self._set_value_font(self._value_point_size(summary))
        self.value_label.setText(summary)
        tooltip = summary
        balance = self._format_balance(snapshot)
        if balance:
            tooltip = f"{summary}\n{balance}"
        self.value_label.setToolTip(tooltip)
        has_five_hour_window = any(key == "five_hour" for key, _ in self.quota_fields)
        reset_time = self._format_reset_time(snapshot) if has_five_hour_window else None
        self.time_label.setText(reset_time or "")
        self.window_label.setText(self._window_label_text())
        return True

    def _render_balance(self, snapshot: UsageSnapshot) -> bool:
        if not snapshot.balances:
            return False
        balance = snapshot.balances[0]
        amount = balance.remaining if balance.remaining is not None else balance.total
        if amount is None:
            return False
        self.time_label.clear()
        if self.balance_display == "amount":
            currency = str(balance.currency).upper()
            self.window_label.setText(currency)
            amount_text = self._format_balance_amount_fixed(amount)
            if amount <= 0:
                self._set_value_font(8)
                self.value_label.setText("NO\nCREDIT")
                self.value_label.setToolTip(f"{amount_text} {currency}")
                return True
            self._set_value_font(12)
            self.value_label.setText(amount_text)
            self.value_label.setToolTip(f"{amount_text} {currency}")
            return True
        self.window_label.setText("BAL")
        if amount <= 0:
            self._set_value_font(8)
            self.value_label.setText("NO\nCREDIT")
            self.value_label.setToolTip(f"{self._format_balance_amount(amount)} {balance.currency}")
            return True
        if balance.total is not None and balance.used is not None and balance.total > 0:
            percent = float(amount / balance.total * 100)
        else:
            percent = float(amount) / 20 * 100
        percent = max(0.0, min(100.0, percent))
        text = f"{self._format_percent(percent)}%"
        self._set_value_font(15)
        self.value_label.setText(text)
        amount_text = self._format_balance_amount(amount)
        self.value_label.setToolTip(
            f"{text.replace(chr(10), ' ')} · {amount_text} {balance.currency}"
        )
        return True

    def _render_manual(self, snapshot: UsageSnapshot) -> None:
        self.time_label.clear()
        self._set_value_font(6)
        self.value_label.setText("NOT\nCONNECTED")
        self.value_label.setToolTip(snapshot.message or "사용량 연동 준비 중")
        self.window_label.setText("MAN")

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
        font = QFont(self.font())
        font.setFamily("Noto Sans KR")
        font.setPointSize(10)
        self.setFont(font)
        card_font = QFont(font)
        card_font.setPointSize(8)
        card_font.setBold(True)
        self.title_label.setFont(card_font)
        small_font = QFont(font)
        small_font.setPointSize(7)
        self.full_name_label.setFont(small_font)
        self.time_label.setFont(small_font)
        self.window_label.setFont(small_font)
        dot_font = QFont(font)
        dot_font.setPointSize(6)
        self.status_dot.setFont(dot_font)
        self._set_value_font(15)

    def _set_value_font(self, point_size: int) -> None:
        value_font = QFont(self.font())
        value_font.setPointSize(point_size)
        value_font.setBold(True)
        self.value_label.setFont(value_font)

    def _apply_status_style(self, status: ProviderStatus) -> None:
        palette = {
            ProviderStatus.OK: "#33e8b8",
            ProviderStatus.WARNING: "#ffbf4d",
            ProviderStatus.CRITICAL: "#ff6b73",
            ProviderStatus.AUTH_REQUIRED: "#ff9f43",
            ProviderStatus.UNAVAILABLE: "#8596b2",
            ProviderStatus.ERROR: "#ff6b73",
            ProviderStatus.STALE: "#ffbf4d",
            ProviderStatus.MANUAL: "#8596b2",
        }
        color = palette.get(status, "#8596b2")
        self.status_dot.setStyleSheet(f"color: {color};")
        self.title_label.setStyleSheet(f"color: {color};")
        self.time_label.setStyleSheet("color: #788cb0;")
        self.window_label.setStyleSheet("color: #788cb0;")
        self.value_label.setStyleSheet("color: #edf5ff;")

    @staticmethod
    def _value_point_size(text: str) -> int:
        if "\n" in text:
            return 7
        if "/" in text:
            return 9
        if len(text) > 8:
            return 8
        return 15

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
