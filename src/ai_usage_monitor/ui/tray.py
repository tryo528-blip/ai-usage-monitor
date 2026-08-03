from __future__ import annotations

from PySide6.QtWidgets import QSystemTrayIcon


class Tray(QSystemTrayIcon):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setToolTip("AI Usage Monitor")
