from __future__ import annotations

import sys

from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from ai_usage_monitor.infrastructure.logging_config import configure_logging
from ai_usage_monitor.ui.main_window import MainWindow

# One running copy per Windows user. A second launch (for example the Startup
# shortcut plus a manual start) just brings the first window forward.
_INSTANCE_KEY = "AIUsageMonitor.single-instance"
# Startup shortcut flag: begin with only the taskbar readout, window hidden.
_START_HIDDEN_FLAG = "--hidden"
# Generous enough for a busy login; a missing server fails immediately anyway.
_CONNECT_TIMEOUT_MS = 1000


def should_show_window(start_hidden: bool, taskbar_active: bool) -> bool:
    """At login (--hidden) only the taskbar readout appears, if there is one."""

    return not (start_hidden and taskbar_active)


def signal_running_instance(key: str = _INSTANCE_KEY) -> bool:
    socket = QLocalSocket()
    socket.connectToServer(key)
    if not socket.waitForConnected(_CONNECT_TIMEOUT_MS):
        return False
    socket.write(b"show")
    socket.waitForBytesWritten(_CONNECT_TIMEOUT_MS)
    socket.disconnectFromServer()
    return True


class App:
    def __init__(self, argv: list[str] | None = None) -> None:
        argv = sys.argv if argv is None else argv
        self.logger = configure_logging()
        self.app = QApplication(argv)
        # The window may hide behind the taskbar readout; MainWindow decides when
        # closing actually quits.
        self.app.setQuitOnLastWindowClosed(False)
        self.start_hidden = _START_HIDDEN_FLAG in argv
        self.already_running = signal_running_instance()
        if self.already_running:
            return

        QLocalServer.removeServer(_INSTANCE_KEY)
        self.server = QLocalServer()
        self.server.newConnection.connect(self._show_from_second_launch)
        self.server.listen(_INSTANCE_KEY)
        self.window = MainWindow()
        # Windows logoff/shutdown must not be blocked by the hide-on-close.
        self.app.commitDataRequest.connect(self.window.allow_close)
        self.app.aboutToQuit.connect(self.window.allow_close)

    def _show_from_second_launch(self) -> None:
        while self.server.hasPendingConnections():
            self.server.nextPendingConnection().deleteLater()
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def run(self) -> None:
        if self.already_running:
            return
        # Without the taskbar readout there would be nothing to click, so the
        # window is shown even with --hidden.
        if should_show_window(self.start_hidden, self.window.taskbar_bar.active):
            self.window.show()
        self.app.exec()
