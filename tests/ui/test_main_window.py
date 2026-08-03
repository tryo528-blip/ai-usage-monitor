from __future__ import annotations

from PySide6.QtWidgets import QApplication

from ai_usage_monitor.ui.main_window import MainWindow


def test_main_window_builds_cards(qtbot) -> None:
    QApplication.instance() or QApplication([])
    window = MainWindow()
    qtbot.addWidget(window)
    titles = [card.title_label.text() for card in window.cards.values()]
    assert len(window.cards) == 6
    assert "Mock" not in titles
    assert "Grok" in titles
    assert "Gemini" in titles
