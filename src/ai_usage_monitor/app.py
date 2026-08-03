from __future__ import annotations

from PySide6.QtWidgets import QApplication

from ai_usage_monitor.infrastructure.logging_config import configure_logging
from ai_usage_monitor.ui.main_window import MainWindow


class App:
    def __init__(self) -> None:
        self.logger = configure_logging()
        self.app = QApplication([])
        self.window = MainWindow()

    def run(self) -> None:
        self.window.show()
        self.app.exec()
