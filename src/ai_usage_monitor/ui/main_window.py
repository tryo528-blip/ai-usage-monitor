from __future__ import annotations

from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .provider_card import ProviderCard


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("AI Usage Monitor")
        self.resize(1000, 680)

        root = QWidget(self)
        layout = QVBoxLayout(root)

        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel("AI Usage Monitor"))
        self.refresh_button = QPushButton("새로고침")
        self.settings_button = QPushButton("설정")
        top_bar.addWidget(self.refresh_button)
        top_bar.addWidget(self.settings_button)
        layout.addLayout(top_bar)

        cards_layout = QGridLayout()
        self.cards = {
            "mock": ProviderCard("Mock"),
            "openrouter": ProviderCard("OpenRouter"),
            "deepseek": ProviderCard("DeepSeek"),
            "claude": ProviderCard("Claude"),
            "codex": ProviderCard("Codex"),
            "manual": ProviderCard("Grok / Gemini"),
        }
        positions = [
            (0, 0),
            (0, 1),
            (1, 0),
            (1, 1),
            (2, 0),
            (2, 1),
        ]
        for (_key, card), pos in zip(self.cards.items(), positions, strict=True):
            cards_layout.addWidget(card, *pos)
        layout.addLayout(cards_layout)

        self.setCentralWidget(root)
