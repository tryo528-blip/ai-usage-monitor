from __future__ import annotations

import os

from PySide6.QtCore import QObject, QProcess, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ai_usage_monitor.collectors.deepseek import DeepSeekCollector
from ai_usage_monitor.domain.providers import (
    PROVIDER_DEFINITIONS,
    VISIBLE_PROVIDERS_SETTING,
    get_visible_provider_ids,
)
from ai_usage_monitor.infrastructure.secret_store import FakeSecretStore, SecretStore
from ai_usage_monitor.infrastructure.settings_store import SettingsStore


class ConnectionTestSignals(QObject):
    finished = Signal(str)


class ConnectionTestWorker(QRunnable):
    def __init__(self, collector, label: str) -> None:
        super().__init__()
        self.collector = collector
        self.label = label
        self.signals = ConnectionTestSignals()

    def run(self) -> None:
        try:
            snapshot = self.collector.collect()
            message = f"{self.label}: {snapshot.status.value} / {snapshot.message}"
        except Exception as exc:
            message = f"{self.label}: ERROR / 수집 중 오류: {exc}"
        finally:
            self.signals.finished.emit(message)


class SettingsDialog(QDialog):
    def __init__(
        self,
        secret_store: SecretStore | None = None,
        settings_store: SettingsStore | None = None,
        show_claude_auth: bool = True,
    ) -> None:
        super().__init__()
        self.setWindowTitle("설정")
        font = QFont(self.font())
        font.setPointSize(10)
        self.setFont(font)
        self.secret_store = secret_store or SecretStore()
        self.settings_store = settings_store or SettingsStore()
        self._pending_test_count = 0

        settings = self.settings_store.load()
        visible_provider_ids = set(get_visible_provider_ids(settings))
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.deepseek_key = QLineEdit()
        self.deepseek_key.setEchoMode(QLineEdit.EchoMode.Password)

        layout.addWidget(QLabel("표시할 모델"))
        self.provider_checkboxes = {}
        self.provider_rows = {}
        for definition in PROVIDER_DEFINITIONS:
            row = QWidget(self)
            row.setFixedHeight(24)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)

            checkbox = QCheckBox(definition.title, row)
            checkbox.setChecked(definition.provider_id in visible_provider_ids)
            checkbox.setMinimumWidth(64)
            checkbox.setToolTip(definition.full_name or definition.title)
            self.provider_checkboxes[definition.provider_id] = checkbox

            full_name = QLabel(definition.full_name or definition.title, row)
            full_name.setStyleSheet("color: #6b7280;")
            full_name.setToolTip(definition.full_name or definition.title)
            row_layout.addWidget(checkbox)
            row_layout.addWidget(full_name, 1)
            self.provider_rows[definition.provider_id] = row
            layout.addWidget(row)

        self.auto_refresh = QCheckBox("자동 새로고침")
        self.start_on_launch = QCheckBox("시작 시 실행 (준비 중)")
        self.start_on_launch.setEnabled(False)
        self.delete_deepseek_key = QCheckBox("DeepSeek 키 삭제")

        self.auto_refresh.setChecked(bool(settings.get("auto_refresh", True)))

        form.addRow(QLabel("DeepSeek API 키"), self.deepseek_key)
        layout.addLayout(form)

        auth_buttons = QHBoxLayout()
        self.claude_auth_button = QPushButton("Claude 인증")
        self.grok_auth_button = QPushButton("Grok 인증")
        auth_buttons.addWidget(self.claude_auth_button)
        auth_buttons.addWidget(self.grok_auth_button)
        if not show_claude_auth:
            self.claude_auth_button.hide()
        layout.addLayout(auth_buttons)
        layout.addWidget(self.auto_refresh)
        layout.addWidget(self.start_on_launch)
        layout.addWidget(self.delete_deepseek_key)

        buttons = QHBoxLayout()
        self.save_button = QPushButton("저장")
        self.test_button = QPushButton("연결 테스트")
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.test_button)
        layout.addLayout(buttons)

        self.save_button.clicked.connect(self.save_settings)
        self.test_button.clicked.connect(self.test_connection)
        self.claude_auth_button.clicked.connect(self._launch_claude_auth)
        self.grok_auth_button.clicked.connect(self._launch_grok_auth)

    def _launch_claude_auth(self) -> None:
        self._start_cli("Claude", "claude", ["auth", "login"])

    def _launch_grok_auth(self) -> None:
        self._start_cli("Grok", "grok", ["login"])

    def _start_cli(self, label: str, command: str, arguments: list[str]) -> None:
        if os.name == "nt":
            program = os.environ.get("ComSpec", "cmd.exe")
            process_arguments = ["/k", command, *arguments]
        else:
            program = command
            process_arguments = arguments
        if not QProcess.startDetached(program, process_arguments):
            QMessageBox.warning(self, f"{label} 인증", f"{label} 인증 창을 열 수 없습니다.")

    def save_settings(self) -> None:
        settings = self.settings_store.load()
        settings["auto_refresh"] = self.auto_refresh.isChecked()
        settings[VISIBLE_PROVIDERS_SETTING] = [
            definition.provider_id
            for definition in PROVIDER_DEFINITIONS
            if self.provider_checkboxes[definition.provider_id].isChecked()
        ]
        self.settings_store.save(settings)

        value = self.deepseek_key.text().strip()
        if self.delete_deepseek_key.isChecked():
            try:
                self.secret_store.delete("deepseek.api_key")
            except Exception:
                pass
        elif value:
            self.secret_store.set("deepseek.api_key", value)
        self.accept()

    def test_connection(self) -> None:
        temp_store = FakeSecretStore()
        pending = []

        deepseek_key = self.deepseek_key.text().strip()

        if deepseek_key:
            temp_store.set("deepseek.api_key", deepseek_key)
            worker = ConnectionTestWorker(
                DeepSeekCollector(secret_store=temp_store),
                "DeepSeek",
            )
            worker.signals.finished.connect(self._handle_test_result)
            pending.append(worker)

        if not pending:
            QMessageBox.information(self, "연결 테스트", "입력된 키가 없습니다.")
            return

        self.test_button.setEnabled(False)
        self._pending_test_count = len(pending)
        for worker in pending:
            QThreadPool.globalInstance().start(worker)

    def _handle_test_result(self, message: str) -> None:
        self._pending_test_count -= 1
        QMessageBox.information(self, "연결 테스트", message)
        if self._pending_test_count <= 0:
            self.test_button.setEnabled(True)
