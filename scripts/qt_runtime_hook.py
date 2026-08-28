"""Keep frozen PySide6 extension modules on their bundled Qt DLLs."""

from __future__ import annotations

import os
import sys

if sys.platform == "win32" and getattr(sys, "frozen", False):
    pyside6_dir = os.path.join(sys._MEIPASS, "PySide6")
    if os.path.isdir(pyside6_dir):
        import ctypes

        # Keep the handle alive for the lifetime of the process. This makes
        # QtWidgets.pyd resolve Qt6Widgets/Qt6Core from this bundle before
        # looking at unrelated Qt installations on the machine.
        dll_directory = os.add_dll_directory(pyside6_dir)

        # Explicitly load the Qt dependency chain from the same directory.
        # This is an extra guard for Windows installations that have another
        # Qt6Core/Qt6Gui/Qt6Widgets earlier in their global DLL search path.
        native_handles = []

        # Qt6Core imports the unversioned Windows ICU forwarder. Some tools
        # (for example Poppler/PostgreSQL) put a different ICU build on PATH;
        # load the Windows forwarder first so its exported callbacks cannot be
        # resolved against an incompatible version.
        system_root = os.environ.get("SystemRoot", r"C:\\Windows")
        system_icu_path = os.path.join(system_root, "System32", "icuuc.dll")
        if os.path.isfile(system_icu_path):
            try:
                native_handles.append(ctypes.WinDLL(system_icu_path))
            except OSError:
                pass

        qt_handles = []
        for dll_name in ("Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll"):
            dll_path = os.path.join(pyside6_dir, dll_name)
            if not os.path.isfile(dll_path):
                continue
            try:
                qt_handles.append(ctypes.WinDLL(dll_path))
            except OSError:
                # Let the normal PySide6 import report the original error if
                # a platform-specific DLL cannot be loaded.
                continue

        sys._ai_usage_monitor_pyside6_dll_state = (dll_directory, native_handles, qt_handles)
