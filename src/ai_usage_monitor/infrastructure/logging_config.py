from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .paths import get_paths


def configure_logging() -> logging.Logger:
    paths = get_paths()
    paths.log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("ai_usage_monitor")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = RotatingFileHandler(paths.log_path, maxBytes=2 * 1024 * 1024, backupCount=5)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    return logger
