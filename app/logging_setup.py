#!/usr/bin/env python3
"""Shared logging setup for branch-watcher.

Gives every module a logger that writes to both the console and a rotating
log file, so issues (e.g. a MAC that can't be resolved to an IP) leave a trail
even when the script runs unattended from a backend.

Configuration via environment (or a .env file if python-dotenv is installed):
    BW_LOG_LEVEL  log level: DEBUG/INFO/WARNING/ERROR  (default: INFO)
    BW_LOG_FILE   path to the log file                 (default: branch_watcher.log)
"""

import logging
import os
from logging.handlers import RotatingFileHandler

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


LOG_LEVEL = os.getenv("BW_LOG_LEVEL", "INFO").upper()
LOG_FILE = os.getenv("BW_LOG_FILE", "branch_watcher.log")

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"

# Track which loggers we've already configured so repeated get_logger() calls
# don't stack duplicate handlers (which would print every line N times).
_configured = set()


def get_logger(name):
    """Return a configured logger for `name` (usually __name__)."""
    logger = logging.getLogger(name)
    if name in _configured:
        return logger

    logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)

    # File logging is best-effort: if the path isn't writable (read-only dir,
    # permissions) we keep going with console-only rather than crashing.
    try:
        file_handler = RotatingFileHandler(
            LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError as exc:
        logger.warning("Could not open log file %s: %s", LOG_FILE, exc)

    # Don't also bubble up to the root logger's default handler.
    logger.propagate = False
    _configured.add(name)
    return logger
