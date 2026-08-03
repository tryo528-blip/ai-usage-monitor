from __future__ import annotations

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
from ai_usage_monitor.infrastructure.secret_store import SecretStore
from ai_usage_monitor.infrastructure.settings_store import SettingsStore


class SettingsDialog(QDialog):
    def __init__(self, secret_store: SecretStore | None = None) -> None:
        super().__init__()
        self.setWindowTitle("설정")
        self.secret_store = secret_store or SecretStore()
        self.settings_store = SettingsStore()

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

        form.addRow(QLabel("OpenRouter API 키"), self.openrouter_key)
        form.addRow(QLabel("OpenRouter Management 키"), self.management_key)
        form.addRow(QLabel("DeepSeek API 키"), self.deepseek_key)
        layout.addLayout(form)
        layout.addWidget(self.auto_refresh)
        layout.addWidget(self.start_on_launch)

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

        for key, widget in (
            ("openrouter.api_key", self.openrouter_key),
            ("openrouter.management_key", self.management_key),
            ("deepseek.api_key", self.deepseek_key),
        ):
            value = widget.text().strip()
            if value:
                self.secret_store.set(key, value)
            else:
                try:
                    self.secret_store.delete(key)
                except Exception:
                    pass
        QMessageBox.information(self, "저장 완료", "설정이 저장되었습니다.")

    def test_connection(self) -> None:
        results = []
        openrouter_key = self.openrouter_key.text().strip()
        if openrouter_key:
            self.secret_store.set("openrouter.api_key", openrouter_key)
            snapshot = OpenRouterCollector(secret_store=self.secret_store).collect()
            results.append(f"OpenRouter: {snapshot.status.value} / {snapshot.message}")

        deepseek_key = self.deepseek_key.text().strip()
        if deepseek_key:
            self.secret_store.set("deepseek.api_key", deepseek_key)
            snapshot = DeepSeekCollector(secret_store=self.secret_store).collect()
            results.append(f"DeepSeek: {snapshot.status.value} / {snapshot.message}")

        if not results:
            QMessageBox.information(self, "연결 테스트", "입력된 API 키가 없습니다.")
            return

        QMessageBox.information(self, "연결 테스트", "\n".join(results))
