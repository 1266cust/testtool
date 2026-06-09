from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional


_logger: Optional[logging.Logger] = None


def setup_logging(
    level: int = logging.INFO,
    log_file: Optional[Path] = None,
) -> logging.Logger:
    global _logger

    logger = logging.getLogger("test_tool")
    logger.setLevel(level)

    if logger.handlers:
        logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    _logger = logger
    return logger


def get_logger(name: str) -> logging.Logger:
    if _logger is None:
        setup_logging()
    return logging.getLogger(f"test_tool.{name}")