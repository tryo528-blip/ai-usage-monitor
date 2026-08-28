from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase

PRETENDARD_FAMILY = "Pretendard"
_PRETENDARD_REGULAR_PATH = Path(__file__).resolve().parent / "assets" / "Pretendard-Regular.otf"


@lru_cache(maxsize=1)
def ensure_pretendard_font() -> str:
    font_id = QFontDatabase.addApplicationFont(str(_PRETENDARD_REGULAR_PATH))
    if font_id < 0:
        raise RuntimeError(
            f"Bundled Pretendard font could not be loaded: {_PRETENDARD_REGULAR_PATH}"
        )
    families = QFontDatabase.applicationFontFamilies(font_id)
    if not families:
        raise RuntimeError("Bundled Pretendard font has no registered family")
    return families[0]


def pretendard_regular(point_size: int = 10) -> QFont:
    font = QFont(ensure_pretendard_font(), point_size)
    font.setWeight(QFont.Weight.Normal)
    font.setBold(False)
    return font
