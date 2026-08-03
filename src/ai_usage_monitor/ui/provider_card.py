from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QProgressBar, QVBoxLayout


class ProviderCard(QFrame):
    def __init__(self, title: str) -> None:
        super().__init__()
        self.setFrameStyle(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(220)
        self._layout = QVBoxLayout(self)
        self.title_label = QLabel(title)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.status_label = QLabel("상태: 미조회")
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.message_label = QLabel("메시지: 대기 중")
        self._layout.addWidget(self.title_label)
        self._layout.addWidget(self.status_label)
        self._layout.addWidget(self.progress_bar)
        self._layout.addWidget(self.message_label)
