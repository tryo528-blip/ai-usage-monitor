from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QProgressBar, QVBoxLayout

from ai_usage_monitor.domain.models import UsageSnapshot


class ProviderCard(QFrame):
    def __init__(self, title: str) -> None:
        super().__init__()
        self.setFrameStyle(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(260)
        self._layout = QVBoxLayout(self)
        self.title_label = QLabel(title)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.status_label = QLabel("상태: 미조회")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.detail_label = QLabel("조회 불가")
        self.message_label = QLabel("메시지: 대기 중")
        self._layout.addWidget(self.title_label)
        self._layout.addWidget(self.status_label)
        self._layout.addWidget(self.progress_bar)
        self._layout.addWidget(self.detail_label)
        self._layout.addWidget(self.message_label)

    def set_loading(self) -> None:
        self.status_label.setText("상태: 조회 중")
        self.progress_bar.setRange(0, 0)
        self.detail_label.setText("조회 중...")
        self.message_label.setText("메시지: 데이터 수집 중")

    def set_snapshot(self, snapshot: UsageSnapshot) -> None:
        self.status_label.setText(f"상태: {snapshot.status.value}")
        percent = self._highest_percent(snapshot)
        if percent is None:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(int(percent))

        quota_text = self._format_quota(snapshot)
        balance_text = self._format_balance(snapshot)
        reset_text = self._format_reset(snapshot)
        last_text = self._format_last_success(snapshot)
        self.detail_label.setText(
            " | ".join(part for part in [quota_text, balance_text, reset_text, last_text] if part)
        )
        self.message_label.setText(snapshot.message or "메시지: 정상 조회")

    def set_error(self, message: str) -> None:
        self.status_label.setText("상태: 오류")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.detail_label.setText("조회 불가")
        self.message_label.setText(message)

    @staticmethod
    def _highest_percent(snapshot: UsageSnapshot) -> float | None:
        values = [
            quota.used_percent for quota in snapshot.quota_windows if quota.used_percent is not None
        ]
        if not values:
            return None
        return max(values)

    @staticmethod
    def _format_quota(snapshot: UsageSnapshot) -> str:
        if not snapshot.quota_windows:
            return "한도: 조회 불가"
        parts = []
        for quota in snapshot.quota_windows:
            if (
                quota.used_value is None
                and quota.limit_value is None
                and quota.remaining_value is None
            ):
                parts.append(f"{quota.label}: 한도 미설정")
                continue
            used = quota.used_value if quota.used_value is not None else Decimal("0")
            limit = quota.limit_value if quota.limit_value is not None else None
            remaining = quota.remaining_value if quota.remaining_value is not None else None
            usage_text = f"{used}"
            if limit is not None:
                usage_text = f"{used}/{limit}"
            if remaining is not None:
                usage_text = f"{usage_text} (잔여 {remaining})"
            parts.append(f"{quota.label}: {usage_text}")
        return " ; ".join(parts)

    @staticmethod
    def _format_balance(snapshot: UsageSnapshot) -> str:
        if not snapshot.balances:
            return "잔액: 조회 불가"
        balances = []
        for balance in snapshot.balances:
            remaining = balance.remaining if balance.remaining is not None else "조회 불가"
            used = balance.used if balance.used is not None else "조회 불가"
            balances.append(f"{balance.currency}: {remaining} (사용 {used})")
        return " ; ".join(balances)

    @staticmethod
    def _format_reset(snapshot: UsageSnapshot) -> str:
        for quota in snapshot.quota_windows:
            if quota.resets_at:
                return f"초기화: {quota.resets_at.isoformat()}"
        return "초기화: 조회 불가"

    @staticmethod
    def _format_last_success(snapshot: UsageSnapshot) -> str:
        if snapshot.last_success_at is None:
            return "최근 성공: 없음"
        return f"최근 성공: {snapshot.last_success_at.isoformat()}"
