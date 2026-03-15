"""Application logging setup."""

from __future__ import annotations

import logging
import logging.config
from typing import Any


def build_logging_config(level: str = "INFO") -> dict[str, Any]:
    """Return a basic dictConfig payload for console logging."""

    resolved_level = level.upper()
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s %(levelname)s [%(name)s] %(message)s",
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "standard",
                "level": resolved_level,
            }
        },
        "root": {"handlers": ["console"], "level": resolved_level},
    }


def configure_logging(level: str = "INFO") -> None:
    """Configure process-wide logging."""

    logging.config.dictConfig(build_logging_config(level=level))
