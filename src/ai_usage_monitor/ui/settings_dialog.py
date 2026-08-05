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
)

from ai_usage_monitor.collectors.deepseek import DeepSeekCollector
from ai_usage_monitor.collectors.openrouter import OpenRouterCollector
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
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.management_key = QLineEdit()
        self.management_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.deepseek_key = QLineEdit()
        self.deepseek_key.setEchoMode(QLineEdit.EchoMode.Password)

        self.auto_refresh = QCheckBox("자동 새로고침")
        self.start_on_launch = QCheckBox("시작 시 실행 (준비 중)")
        self.start_on_launch.setEnabled(False)
        self.delete_management_key = QCheckBox("OpenRouter Management 키 삭제")
        self.delete_deepseek_key = QCheckBox("DeepSeek 키 삭제")

        self.auto_refresh.setChecked(bool(settings.get("auto_refresh", True)))

        form.addRow(QLabel("OpenRouter Management 키"), self.management_key)
        form.addRow(QLabel("DeepSeek API 키"), self.deepseek_key)
        layout.addLayout(form)

        auth_buttons = QHBoxLayout()
        self.claude_auth_button = QPushButton("Claude 인증")
        self.grok_auth_button = QPushButton("Grok 인증")
        auth_buttons.addWidget(self.claude_auth_button)
        auth_buttons.addWidget(self.grok_auth_button)
        layout.addLayout(auth_buttons)
        layout.addWidget(self.auto_refresh)
        layout.addWidget(self.start_on_launch)
        layout.addWidget(self.delete_management_key)
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
        self.settings_store.save(settings)

        for key, widget, delete_checkbox in (
            ("openrouter.management_key", self.management_key, self.delete_management_key),
            ("deepseek.api_key", self.deepseek_key, self.delete_deepseek_key),
        ):
            value = widget.text().strip()
            if delete_checkbox.isChecked():
                try:
                    self.secret_store.delete(key)
                except Exception:
                    pass
            elif value:
                self.secret_store.set(key, value)
        self.accept()

    def test_connection(self) -> None:
        temp_store = FakeSecretStore()
        pending = []

        management_key = self.management_key.text().strip()
        deepseek_key = self.deepseek_key.text().strip()

        if management_key:
            temp_store.set("openrouter.management_key", management_key)
            worker = ConnectionTestWorker(
                OpenRouterCollector(secret_store=temp_store),
                "OpenRouter",
            )
            worker.signals.finished.connect(self._handle_test_result)
            pending.append(worker)

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
