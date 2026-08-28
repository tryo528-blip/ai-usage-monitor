from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, QPoint, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ai_usage_monitor.collectors.base import Collector
from ai_usage_monitor.collectors.deepseek import DeepSeekCollector
from ai_usage_monitor.collectors.openrouter import OpenRouterCollector
from ai_usage_monitor.infrastructure.secret_store import FakeSecretStore, SecretStore

from .fonts import pretendard_regular


@dataclass(frozen=True)
class ApiKeyCredential:
    provider_id: str
    label: str
    secret_key: str
    connection_test_supported: bool = False
    note: str = "키를 저장할 수 있습니다."


API_KEY_CREDENTIALS: tuple[ApiKeyCredential, ...] = (
    ApiKeyCredential(
        provider_id="codex",
        label="Codex",
        secret_key="codex.api_key",
        note="키 저장 가능 · 현재 사용량 수집은 로컬 세션을 사용합니다.",
    ),
    ApiKeyCredential(
        provider_id="grok",
        label="Grok",
        secret_key="grok.api_key",
        note="키 저장 가능 · 현재 사용량 수집은 CLI 로그인을 사용합니다.",
    ),
    ApiKeyCredential(
        provider_id="deepseek",
        label="DeepSeek",
        secret_key="deepseek.api_key",
        connection_test_supported=True,
        note="Windows 자격 증명에 안전하게 저장됩니다.",
    ),
    ApiKeyCredential(
        provider_id="openrouter",
        label="OpenRouter",
        secret_key="openrouter.management_key",
        connection_test_supported=True,
        note="잔액 조회용 Management Key를 안전하게 저장합니다.",
    ),
    ApiKeyCredential(
        provider_id="zai",
        label="Z.AI",
        secret_key="zai.api_key",
        note="키 저장 가능 · 사용량 수집기 연결 준비 중입니다.",
    ),
    ApiKeyCredential(
        provider_id="kimi3",
        label="KIMI3",
        secret_key="kimi3.api_key",
        note="키 저장 가능 · 사용량 수집기 연결 준비 중입니다.",
    ),
    ApiKeyCredential(
        provider_id="claude",
        label="Claude",
        secret_key="claude.api_key",
        note="키 저장 가능 · 현재 사용량 수집은 CLI 로그인을 사용합니다.",
    ),
    ApiKeyCredential(
        provider_id="antyg",
        label="Antigravity",
        secret_key="antyg.api_key",
        note="키 저장 가능 · 현재 사용량 수집은 CLI 로그인을 사용합니다.",
    ),
)


class _ConnectionTestSignals(QObject):
    finished = Signal(str)


class _ConnectionTestWorker(QRunnable):
    def __init__(self, label: str, collector: Collector) -> None:
        super().__init__()
        self.label = label
        self.collector = collector
        self.signals = _ConnectionTestSignals()

    def run(self) -> None:
        try:
            snapshot = self.collector.collect()
            message = f"{self.label}: {snapshot.status.value} / {snapshot.message}"
        except Exception as exc:
            message = f"{self.label}: ERROR / 수집 중 오류: {exc}"
        self.signals.finished.emit(message)


_POPUP_STYLE = """
QDialog {
    background-color: #f6f8fd;
    border: 1px solid #b2c2db;
    border-radius: 20px;
    color: #141c2b;
    font-family: "Pretendard";
    font-weight: 400;
}
QLabel, QComboBox, QLineEdit, QPushButton {
    font-family: "Pretendard";
    font-weight: 400;
}
QLabel#popup_title {
    color: #141c2b;
    font-size: 17px;
}
QLabel#popup_subtitle, QLabel#storage_note {
    color: #57637a;
    font-size: 9px;
}
QLabel#field_label {
    color: #141c2b;
    font-size: 10px;
}
QComboBox, QLineEdit {
    min-height: 38px;
    padding: 0 12px;
    color: #141c2b;
    background-color: #ffffff;
    border: 1px solid #cdd6e4;
    border-radius: 9px;
    selection-background-color: #26344f;
}
QComboBox:hover, QLineEdit:hover {
    border-color: #788cb0;
}
QPushButton {
    min-height: 30px;
    padding: 0 12px;
    color: #202735;
    background-color: #eef1f6;
    border: 1px solid #b9c3d2;
    border-radius: 8px;
}
QPushButton:hover {
    background-color: #ffffff;
}
QPushButton#primary_button {
    color: #ffffff;
    background-color: #26344f;
    border-color: #26344f;
}
QPushButton#primary_button:hover {
    background-color: #344766;
}
QPushButton#danger_button {
    color: #ffffff;
    background-color: #ed1c24;
    border-color: #ed1c24;
}
QPushButton#danger_button:hover {
    background-color: #c9161d;
}
QPushButton:disabled {
    color: #929db0;
    background-color: #e7eaf0;
    border-color: #d4dae4;
}
QFrame#delete_warning {
    background-color: #fff1f1;
    border: 1px solid #f6b8b8;
    border-radius: 10px;
}
QLabel#warning_title {
    color: #ab1414;
    font-size: 10px;
}
QLabel#warning_body {
    color: #7a2929;
    font-size: 8px;
}
"""


class _ApiKeyDialogBase(QDialog):
    def __init__(self, title: str, *, secret_store: SecretStore) -> None:
        super().__init__()
        self.secret_store = secret_store
        self.setWindowTitle(title)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setFont(pretendard_regular())
        self.setStyleSheet(_POPUP_STYLE)
        self._drag_position: QPoint | None = None

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() <= 72:
            self._drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_position is not None and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_position)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_position = None
        super().mouseReleaseEvent(event)

    @staticmethod
    def _credential_at(combo: QComboBox) -> ApiKeyCredential:
        return API_KEY_CREDENTIALS[combo.currentIndex()]

    def _has_key(self, credential: ApiKeyCredential) -> bool:
        try:
            return bool(self.secret_store.get(credential.secret_key))
        except Exception:
            return False

    @staticmethod
    def _add_header(layout: QVBoxLayout, title: str) -> None:
        title_label = QLabel(title)
        title_label.setObjectName("popup_title")
        subtitle = QLabel("모든 모델 API 키")
        subtitle.setObjectName("popup_subtitle")
        layout.addWidget(title_label)
        layout.addWidget(subtitle)

    @staticmethod
    def _add_model_field(layout: QVBoxLayout) -> QComboBox:
        label = QLabel("모델")
        label.setObjectName("field_label")
        combo = QComboBox()
        combo.addItems([item.label for item in API_KEY_CREDENTIALS])
        layout.addWidget(label)
        layout.addWidget(combo)
        return combo


class ApiKeyInputDialog(_ApiKeyDialogBase):
    def __init__(self, *, secret_store: SecretStore, parent=None) -> None:
        super().__init__("API 키 입력", secret_store=secret_store)
        if parent is not None:
            self.setParent(parent, self.windowFlags())
        self.setFixedSize(400, 330)
        self._worker: _ConnectionTestWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(8)
        self._add_header(layout, "API 키 입력")
        layout.addSpacing(8)
        self.model_combo = self._add_model_field(layout)
        layout.addSpacing(5)

        key_label = QLabel("API 키")
        key_label.setObjectName("field_label")
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("키를 입력하세요")
        self.api_key_input.setClearButtonEnabled(True)
        layout.addWidget(key_label)
        layout.addWidget(self.api_key_input)

        self.storage_note = QLabel()
        self.storage_note.setObjectName("storage_note")
        layout.addWidget(self.storage_note)
        layout.addStretch(1)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addStretch(1)
        self.cancel_button = QPushButton("취소")
        self.test_button = QPushButton("연결 테스트")
        self.save_button = QPushButton("저장")
        self.save_button.setObjectName("primary_button")
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.test_button)
        footer.addWidget(self.save_button)
        layout.addLayout(footer)

        self.cancel_button.clicked.connect(self.reject)
        self.test_button.clicked.connect(self.test_connection)
        self.save_button.clicked.connect(self.save_key)
        self.api_key_input.returnPressed.connect(self.save_key)
        self.model_combo.currentIndexChanged.connect(self._refresh_state)
        self._refresh_state()

    @property
    def selected_credential(self) -> ApiKeyCredential:
        return self._credential_at(self.model_combo)

    def _refresh_state(self) -> None:
        credential = self.selected_credential
        self.api_key_input.clear()
        if self._has_key(credential):
            self.storage_note.setText("저장된 키 있음 · 값은 화면에 표시되지 않습니다.")
        else:
            self.storage_note.setText(credential.note)
        self.test_button.setEnabled(credential.connection_test_supported)
        if credential.connection_test_supported:
            self.test_button.setToolTip("입력한 키로 연결을 확인합니다.")
        else:
            self.test_button.setToolTip("이 모델의 사용량 수집기 연결 후 지원됩니다.")

    def save_key(self) -> None:
        value = self.api_key_input.text().strip()
        if not value:
            QMessageBox.information(self, "API 키", "키를 입력해 주세요.")
            return
        try:
            self.secret_store.set(self.selected_credential.secret_key, value)
        except Exception as exc:
            QMessageBox.warning(self, "API 키", f"키를 저장할 수 없습니다: {exc}")
            return
        self.api_key_input.clear()
        self.accept()

    def test_connection(self) -> None:
        credential = self.selected_credential
        if not credential.connection_test_supported:
            return
        value = self.api_key_input.text().strip()
        if not value:
            QMessageBox.information(self, "연결 테스트", "키를 입력해 주세요.")
            return
        temp_store = FakeSecretStore()
        temp_store.set(credential.secret_key, value)
        if credential.provider_id == "deepseek":
            collector: Collector = DeepSeekCollector(secret_store=temp_store)
        elif credential.provider_id == "openrouter":
            collector = OpenRouterCollector(secret_store=temp_store)
        else:
            return
        self._worker = _ConnectionTestWorker(credential.label, collector)
        self._worker.signals.finished.connect(self._handle_test_result)
        self.test_button.setEnabled(False)
        QThreadPool.globalInstance().start(self._worker)

    def _handle_test_result(self, message: str) -> None:
        QMessageBox.information(self, "연결 테스트", message)
        self._worker = None
        self._refresh_state()


class ApiKeyDeleteDialog(_ApiKeyDialogBase):
    def __init__(self, *, secret_store: SecretStore, parent=None) -> None:
        super().__init__("API 키 삭제", secret_store=secret_store)
        if parent is not None:
            self.setParent(parent, self.windowFlags())
        self.setFixedSize(400, 306)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(8)
        self._add_header(layout, "API 키 삭제")
        layout.addSpacing(8)
        self.model_combo = self._add_model_field(layout)
        layout.addSpacing(8)

        warning = QFrame()
        warning.setObjectName("delete_warning")
        warning_layout = QVBoxLayout(warning)
        warning_layout.setContentsMargins(14, 10, 14, 10)
        warning_layout.setSpacing(2)
        title = QLabel("저장된 키를 삭제합니다")
        title.setObjectName("warning_title")
        self.warning_body = QLabel()
        self.warning_body.setObjectName("warning_body")
        warning_layout.addWidget(title)
        warning_layout.addWidget(self.warning_body)
        layout.addWidget(warning)
        layout.addStretch(1)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addStretch(1)
        self.cancel_button = QPushButton("취소")
        self.delete_button = QPushButton("삭제")
        self.delete_button.setObjectName("danger_button")
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.delete_button)
        layout.addLayout(footer)

        self.cancel_button.clicked.connect(self.reject)
        self.delete_button.clicked.connect(self.delete_key)
        self.model_combo.currentIndexChanged.connect(self._refresh_state)
        self._refresh_state()

    @property
    def selected_credential(self) -> ApiKeyCredential:
        return self._credential_at(self.model_combo)

    def _refresh_state(self) -> None:
        credential = self.selected_credential
        has_key = self._has_key(credential)
        state = "저장된 키가 있습니다." if has_key else "저장된 키가 없습니다."
        self.warning_body.setText(f"{state} 삭제 후에는 해당 모델을 다시 연결해야 합니다.")
        self.delete_button.setEnabled(has_key)

    def delete_key(self) -> None:
        credential = self.selected_credential
        if not self._has_key(credential):
            self._refresh_state()
            return
        try:
            self.secret_store.delete(credential.secret_key)
        except Exception as exc:
            QMessageBox.warning(self, "API 키", f"키를 삭제할 수 없습니다: {exc}")
            return
        self.accept()
