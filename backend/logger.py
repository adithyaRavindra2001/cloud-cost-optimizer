import logging
import sys
from logging.handlers import RotatingFileHandler
import os

LOG_FILE = os.path.join(os.path.dirname(__file__), "app.log")

_fmt = logging.Formatter(
    fmt="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def get_logger(name: str) -> logging.Logger:
    """Return a logger that writes to both stdout and app.log."""
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger  # already configured

    logger.setLevel(logging.DEBUG)

    # Stream handler — stdout so FastAPI / uvicorn picks it up
    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.DEBUG)
    sh.setFormatter(_fmt)
    logger.addHandler(sh)

    # Rotating file handler — keeps last 5 MB × 3 files
    fh = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(_fmt)
    logger.addHandler(fh)

    logger.propagate = False
    return logger
