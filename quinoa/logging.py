"""Logging configuration for Quinoa."""

import logging
import sys
from pathlib import Path

# Create logger
logger = logging.getLogger("quinoa")


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for the application.

    Args:
        verbose: If True, set DEBUG level. Otherwise INFO.
    """
    level = logging.DEBUG if verbose else logging.INFO

    # Console handler
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(level)
    console_format = logging.Formatter("%(levelname)s: %(message)s")
    console_handler.setFormatter(console_format)

    # File handler (optional - only if log dir exists)
    log_dir = Path.home() / ".local" / "share" / "quinoa"
    if log_dir.exists():
        file_handler = logging.FileHandler(log_dir / "quinoa.log")
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)

    logger.addHandler(console_handler)
    logger.setLevel(level)
