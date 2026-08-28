from __future__ import annotations

import os

from PySide6.QtCore import QPoint, QProcess, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ai_usage_monitor.domain.providers import (
    PROVIDER_CARD_SCHEMA_SETTING,
    PROVIDER_CARD_SCHEMA_VERSION,
    PROVIDER_DEFINITIONS,
    VISIBLE_PROVIDERS_SETTING,
    get_visible_provider_ids,
)
from ai_usage_monitor.infrastructure.secret_store import SecretStore
from ai_usage_monitor.infrastructure.settings_store import SettingsStore

from .api_key_dialogs import ApiKeyDeleteDialog, ApiKeyInputDialog
from .fonts import pretendard_regular

_SETTINGS_STYLE = """
QWidget {
    font-family: "Pretendard";
    font-weight: 400;
}
QFrame#settings_shell {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 #0b1020, stop:1 #12192d
    );
    border: 1px solid #293857;
    border-radius: 22px;
}
QLabel#settings_title {
    color: #f0f7ff;
    font-size: 18px;
}
QLabel#settings_subtitle {
    color: #788cb0;
    font-size: 9px;
}
QFrame#settings_section {
    background-color: #f6f8fd;
    border: 1px solid #d1dbed;
    border-radius: 16px;
}
QFrame#settings_section QLabel#section_title {
    color: #141c2b;
    font-size: 12px;
}
QFrame#settings_section QLabel#section_subtitle {
    color: #57637a;
    font-size: 9px;
}
QFrame#settings_section QCheckBox {
    color: #141c2b;
    spacing: 7px;
    font-size: 10px;
}
QFrame#settings_section QCheckBox::indicator {
    width: 15px;
    height: 15px;
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
QPushButton#close_button {
    min-width: 30px;
    max-width: 30px;
    padding: 0;
}
"""


class SettingsDialog(QDialog):
    def __init__(
        self,
        secret_store: SecretStore | None = None,
        settings_store: SettingsStore | None = None,
        show_claude_auth: bool = True,
    ) -> None:
        super().__init__()
        self.setWindowTitle("설정")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(460, 648)
        self.setFont(pretendard_regular())
        self._drag_position: QPoint | None = None
        self.secret_store = secret_store or SecretStore()
        self.settings_store = settings_store or SettingsStore()

        settings = self.settings_store.load()
        visible_provider_ids = set(get_visible_provider_ids(settings))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        shell = QFrame(self)
        shell.setObjectName("settings_shell")
        shell.setStyleSheet(_SETTINGS_STYLE)
        outer.addWidget(shell)

        layout = QVBoxLayout(shell)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)
        layout.addWidget(self._build_header())
        layout.addWidget(self._build_models_section(visible_provider_ids))
        layout.addWidget(self._build_key_section())
        layout.addWidget(
            self._build_runtime_section(
                bool(settings.get("auto_refresh", True)),
                show_claude_auth,
            )
        )
        layout.addStretch(1)
        layout.addLayout(self._build_footer())

        self.close_button.clicked.connect(self.reject)
        self.cancel_button.clicked.connect(self.reject)
        self.save_button.clicked.connect(self.save_settings)
        self.key_input_button.clicked.connect(self._open_key_input)
        self.key_delete_button.clicked.connect(self._open_key_delete)
        self.claude_auth_button.clicked.connect(self._launch_claude_auth)
        self.grok_auth_button.clicked.connect(self._launch_grok_auth)

    def mousePressEvent(self, event) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and event.position().y() <= 70
            and self.childAt(event.position().toPoint()) is not self.close_button
        ):
            self._drag_position = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (
            self._drag_position is not None
            and event.buttons() == Qt.MouseButton.LeftButton
        ):
            self.move(event.globalPosition().toPoint() - self._drag_position)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_position = None
        super().mouseReleaseEvent(event)

    def _build_header(self) -> QWidget:
        header = QWidget(self)
        header.setFixedHeight(48)
        row = QHBoxLayout(header)
        row.setContentsMargins(0, 0, 0, 0)

        stack = QVBoxLayout()
        stack.setSpacing(1)
        title = QLabel("설정")
        title.setObjectName("settings_title")
        subtitle = QLabel("표시 모델 · 인증 · 자동 새로고침")
        subtitle.setObjectName("settings_subtitle")
        stack.addWidget(title)
        stack.addWidget(subtitle)

        self.close_button = QPushButton("×")
        self.close_button.setObjectName("close_button")
        self.close_button.setToolTip("닫기")
        row.addLayout(stack)
        row.addStretch(1)
        row.addWidget(self.close_button)
        return header

    @staticmethod
    def _section() -> tuple[QFrame, QVBoxLayout]:
        section = QFrame()
        section.setObjectName("settings_section")
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(14, 12, 14, 12)
        section_layout.setSpacing(6)
        return section, section_layout

    @staticmethod
    def _section_heading(
        layout: QVBoxLayout,
        title: str,
        subtitle: str,
    ) -> None:
        title_label = QLabel(title)
        title_label.setObjectName("section_title")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("section_subtitle")
        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)

    def _build_models_section(self, visible_ids: set[str]) -> QFrame:
        section, section_layout = self._section()
        section.setFixedHeight(232)
        self._section_heading(
            section_layout,
            "표시할 모델",
            "선택한 카드 수에 맞춰 메인 창이 자동으로 작아집니다.",
        )
        grid = QGridLayout()
        grid.setContentsMargins(0, 3, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(5)
        self.provider_checkboxes: dict[str, QCheckBox] = {}
        self.provider_rows: dict[str, QWidget] = {}
        for index, definition in enumerate(PROVIDER_DEFINITIONS):
            full_name = definition.full_name or definition.title
            checkbox = QCheckBox(f"{definition.title}  {full_name}")
            checkbox.setFixedHeight(23)
            checkbox.setChecked(definition.provider_id in visible_ids)
            checkbox.setToolTip(full_name)
            self.provider_checkboxes[definition.provider_id] = checkbox
            self.provider_rows[definition.provider_id] = checkbox
            grid.addWidget(checkbox, index // 2, index % 2)
        section_layout.addLayout(grid)
        return section

    def _build_key_section(self) -> QFrame:
        section, section_layout = self._section()
        section.setFixedHeight(82)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        text = QVBoxLayout()
        text.setSpacing(1)
        self._section_heading(
            text,
            "API 키",
            "모든 모델의 키를 안전하게 저장·삭제",
        )
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.key_input_button = QPushButton("키 입력")
        self.key_input_button.setObjectName("primary_button")
        self.key_delete_button = QPushButton("키 삭제")
        self.key_delete_button.setObjectName("danger_button")
        actions.addWidget(self.key_input_button)
        actions.addWidget(self.key_delete_button)
        row.addLayout(text)
        row.addStretch(1)
        row.addLayout(actions)
        section_layout.addLayout(row)
        return section

    def _build_runtime_section(
        self,
        auto_refresh_enabled: bool,
        show_claude_auth: bool,
    ) -> QFrame:
        section, section_layout = self._section()
        section.setFixedHeight(132)

        auth_row = QHBoxLayout()
        auth_text = QVBoxLayout()
        auth_text.setSpacing(1)
        self._section_heading(auth_text, "CLI 인증", "로컬 로그인 창 열기")
        auth_actions = QHBoxLayout()
        auth_actions.setSpacing(6)
        self.claude_auth_button = QPushButton("Claude")
        self.grok_auth_button = QPushButton("Grok")
        auth_actions.addWidget(self.claude_auth_button)
        auth_actions.addWidget(self.grok_auth_button)
        if not show_claude_auth:
            self.claude_auth_button.hide()
        auth_row.addLayout(auth_text)
        auth_row.addStretch(1)
        auth_row.addLayout(auth_actions)
        section_layout.addLayout(auth_row)

        refresh_row = QHBoxLayout()
        refresh_text = QVBoxLayout()
        refresh_text.setSpacing(1)
        self._section_heading(
            refresh_text,
            "자동 새로고침",
            "10분마다 사용량 갱신",
        )
        self.auto_refresh = QCheckBox()
        self.auto_refresh.setChecked(auto_refresh_enabled)
        self.auto_refresh.setToolTip("자동 새로고침")
        refresh_row.addLayout(refresh_text)
        refresh_row.addStretch(1)
        refresh_row.addWidget(self.auto_refresh)
        section_layout.addLayout(refresh_row)
        return section

    def _build_footer(self) -> QHBoxLayout:
        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addStretch(1)
        self.cancel_button = QPushButton("취소")
        self.save_button = QPushButton("저장")
        self.save_button.setObjectName("primary_button")
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.save_button)
        return footer

    def _open_key_input(self) -> None:
        ApiKeyInputDialog(secret_store=self.secret_store, parent=self).exec()

    def _open_key_delete(self) -> None:
        ApiKeyDeleteDialog(secret_store=self.secret_store, parent=self).exec()

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
        settings[PROVIDER_CARD_SCHEMA_SETTING] = PROVIDER_CARD_SCHEMA_VERSION
        settings[VISIBLE_PROVIDERS_SETTING] = [
            definition.provider_id
            for definition in PROVIDER_DEFINITIONS
            if self.provider_checkboxes[definition.provider_id].isChecked()
        ]
        self.settings_store.save(settings)
        self.accept()
