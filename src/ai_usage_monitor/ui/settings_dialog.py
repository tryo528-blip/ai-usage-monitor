from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
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
    def __init__(self, collector, label: str, secret_store: FakeSecretStore) -> None:
        super().__init__()
        self.collector = collector
        self.label = label
        self.secret_store = secret_store
        self.signals = ConnectionTestSignals()

    def run(self) -> None:
        snapshot = self.collector.collect()
        self.signals.finished.emit(f"{self.label}: {snapshot.status.value} / {snapshot.message}")


class SettingsDialog(QDialog):
    def __init__(
        self,
        secret_store: SecretStore | None = None,
        settings_store: SettingsStore | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("설정")
        self.secret_store = secret_store or SecretStore()
        self.settings_store = settings_store or SettingsStore()
        self._pending_test_count = 0

        settings = self.settings_store.load()
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.openrouter_key = QLineEdit()
        self.openrouter_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.management_key = QLineEdit()
        self.management_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.deepseek_key = QLineEdit()
        self.deepseek_key.setEchoMode(QLineEdit.EchoMode.Password)

        self.auto_refresh = QCheckBox("자동 새로고침")
        self.start_on_launch = QCheckBox("시작 시 실행")
        self.delete_openrouter_key = QCheckBox("OpenRouter 키 삭제")
        self.delete_management_key = QCheckBox("OpenRouter Management 키 삭제")
        self.delete_deepseek_key = QCheckBox("DeepSeek 키 삭제")

        self.auto_refresh.setChecked(bool(settings.get("auto_refresh", True)))
        self.start_on_launch.setChecked(bool(settings.get("start_on_launch", False)))

        form.addRow(QLabel("OpenRouter API 키"), self.openrouter_key)
        form.addRow(QLabel("OpenRouter Management 키"), self.management_key)
        form.addRow(QLabel("DeepSeek API 키"), self.deepseek_key)
        layout.addLayout(form)
        layout.addWidget(self.auto_refresh)
        layout.addWidget(self.start_on_launch)
        layout.addWidget(self.delete_openrouter_key)
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

    def save_settings(self) -> None:
        settings = self.settings_store.load()
        settings["auto_refresh"] = self.auto_refresh.isChecked()
        settings["start_on_launch"] = self.start_on_launch.isChecked()
        self.settings_store.save(settings)

        for key, widget, delete_checkbox in (
            ("openrouter.api_key", self.openrouter_key, self.delete_openrouter_key),
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

        openrouter_key = self.openrouter_key.text().strip()
        management_key = self.management_key.text().strip()
        deepseek_key = self.deepseek_key.text().strip()

        if openrouter_key:
            temp_store.set("openrouter.api_key", openrouter_key)
            if management_key:
                temp_store.set("openrouter.management_key", management_key)
            worker = ConnectionTestWorker(
                OpenRouterCollector(secret_store=temp_store),
                "OpenRouter",
                temp_store,
            )
            worker.signals.finished.connect(self._handle_test_result)
            pending.append(worker)

        if deepseek_key:
            temp_store.set("deepseek.api_key", deepseek_key)
            worker = ConnectionTestWorker(
                DeepSeekCollector(secret_store=temp_store),
                "DeepSeek",
                temp_store,
            )
            worker.signals.finished.connect(self._handle_test_result)
            pending.append(worker)

        if not pending:
            QMessageBox.information(self, "연결 테스트", "입력된 API 키가 없습니다.")
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
