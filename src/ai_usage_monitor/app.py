from __future__ import annotations

import sys

from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from ai_usage_monitor.infrastructure.logging_config import configure_logging
from ai_usage_monitor.ui.main_window import MainWindow

# One running copy per Windows user. A second launch (for example the Startup
# shortcut plus a manual start) just brings the first window forward.
_INSTANCE_KEY = "AIUsageMonitor.single-instance"
_START_IN_TRAY_FLAG = "--tray"


def _signal_running_instance() -> bool:
    socket = QLocalSocket()
    socket.connectToServer(_INSTANCE_KEY)
    if not socket.waitForConnected(300):
        return False
    socket.write(b"show")
    socket.waitForBytesWritten(300)
    socket.disconnectFromServer()
    return True


class App:
    def __init__(self, argv: list[str] | None = None) -> None:
        argv = sys.argv if argv is None else argv
        self.logger = configure_logging()
        self.app = QApplication(argv)
        # The window may hide into the taskbar tray; MainWindow decides when
        # closing actually quits.
        self.app.setQuitOnLastWindowClosed(False)
        self.start_in_tray = _START_IN_TRAY_FLAG in argv
        self.already_running = _signal_running_instance()
        if self.already_running:
            return

        QLocalServer.removeServer(_INSTANCE_KEY)
        self.server = QLocalServer()
        self.server.newConnection.connect(self._show_from_second_launch)
        self.server.listen(_INSTANCE_KEY)
        self.window = MainWindow()

    def _show_from_second_launch(self) -> None:
        while self.server.hasPendingConnections():
            self.server.nextPendingConnection().deleteLater()
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def run(self) -> None:
        if self.already_running:
            return
        # At login the Startup shortcut passes --tray: only the taskbar gauges
        # appear. Without tray icons there would be nothing to click, so the
        # window is shown anyway.
        if not (self.start_in_tray and self.window.tray.active):
            self.window.show()
        self.app.exec()
