from __future__ import annotations

from datetime import datetime
from pathlib import Path
import logging

from .config import AppConfig


LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def _build_log_path(log_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S%f")[:-3]
    return log_dir / f"{timestamp}.log"


def configure_logging(config: AppConfig) -> Path:
    config.log_dir.mkdir(parents=True, exist_ok=True)
    log_path = _build_log_path(config.log_dir)

    root_logger = logging.getLogger()
    root_logger.setLevel(config.log_level)
    root_logger.handlers.clear()

    formatter = logging.Formatter(LOG_FORMAT)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)

    logging.getLogger(__name__).info("logging configured: %s", log_path)
    return log_path
