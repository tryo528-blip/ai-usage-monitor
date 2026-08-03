from __future__ import annotations

from PySide6.QtWidgets import QDialog, QTextEdit, QVBoxLayout


class HistoryDialog(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("조회 이력")
        layout = QVBoxLayout(self)
        self.editor = QTextEdit()
        self.editor.setPlainText("조회 이력은 후속 단계에서 확장됩니다.")
        layout.addWidget(self.editor)
