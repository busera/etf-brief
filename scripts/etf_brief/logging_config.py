"""Loguru logging setup for the etf-brief skill.

Vendored from the author's PA skill infrastructure so this repo is
self-contained — no sibling `shared/` package required.

Usage:
    from etf_brief.logging_config import setup_logger
    logger = setup_logger("etf_brief")
    logger.info("Starting run")

Default log location: ``<repo_root>/logs/<skill_name>.log`` with daily
rotation and 7-day retention.
"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger


def setup_logger(
    skill_name: str,
    log_dir: Path | None = None,
    level: str = "INFO",
    rotation: str = "1 day",
    retention: str = "7 days",
) -> "logger":
    """Configure loguru for a skill script.

    Args:
        skill_name: Name used for the log file (e.g. ``"etf_brief"``).
        log_dir: Directory for log files. Defaults to the caller's
            ``<skill_dir>/logs/`` (where ``skill_dir`` is the parent of
            ``scripts/``).
        level: Minimum file log level (``"DEBUG"``, ``"INFO"``,
            ``"WARNING"``, ``"ERROR"``).
        rotation: When to rotate (e.g. ``"1 day"``, ``"10 MB"``).
        retention: How long to keep old logs (e.g. ``"7 days"``).

    Returns:
        The configured loguru logger singleton.

    Raises:
        OSError: If ``log_dir`` cannot be created.
    """
    logger.remove()

    logger.add(
        sys.stderr,
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<7} | {message}",
    )

    if log_dir is None:
        caller_frame = sys._getframe(1)
        caller_file = Path(
            caller_frame.f_globals.get("__file__", ".")
        ).resolve()
        # scripts/fetcher.py → <skill_dir>/logs/
        skill_dir = caller_file.parent.parent
        log_dir = skill_dir / "logs"

    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{skill_name}.log"

    logger.add(
        str(log_file),
        level=level,
        format=(
            "{time:YYYY-MM-DD HH:mm:ss} | {level:<7} | "
            "{module}:{function}:{line} | {message}"
        ),
        rotation=rotation,
        retention=retention,
        compression="gz",
    )

    return logger
