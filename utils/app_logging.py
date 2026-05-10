"""
utils/app_logging.py
====================

Application-wide :mod:`logging` setup with a rotating file handler stored
under the local application data directory.

**Log file location (Windows):**
    ``%LOCALAPPDATA%\\WSLManagerPro\\logs\\app.log``

**Log file location (Linux):**
    ``~/.local/share/wslmanagerpro/logs/app.log``

**Rotation policy:**
    * Max file size: 2 MB.
    * Backup count: 5 (``app.log.1`` through ``app.log.5``).
    * Encoding: UTF-8.
    * Format: ``YYYY-MM-DD HH:MM:SS | LEVEL | message``.

Security contract (ROADMAP C1)
------------------------------
Call sites **must never** pass user passwords or tokens into log messages.
The file handler records exactly the string it receives — there is no
automatic redaction.  This is enforced by convention at every call site;
the logging layer itself does not inspect message content.

Key functions
-------------
* :func:`configure_logging` — Attach the rotating handler (idempotent).
* :func:`log_level_for_ui_line` — Map legacy UI colour/text hints to
  :mod:`logging` severity levels.
* :func:`log_dir` — Determine the log directory for the current platform.
* :func:`get_logger` — Return the module-scoped :class:`logging.Logger`.
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

#: Logger name used throughout the application.
#: Import via :func:`get_logger`.
WSL_MANAGER_LOGGER: str = "wsl_manager_pro"


def log_dir() -> Path:
    """Determine the directory for ``app.log`` (created on configure).

    * **Windows** — ``%LOCALAPPDATA%\\WSLManagerPro\\logs``.
    * **Linux** — ``~/.local/share/wslmanagerpro/logs``.

    Returns:
        The platform-appropriate log directory as a :class:`~pathlib.Path`.
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        return Path(base) / "WSLManagerPro" / "logs"
    return Path.home() / ".local" / "share" / "wslmanagerpro" / "logs"


def get_logger() -> logging.Logger:
    """Return the module-scoped logger for ``"wsl_manager_pro"``.

    Safe to call before :func:`configure_logging` — the returned logger
    simply won't have a file handler yet.
    """
    return logging.getLogger(WSL_MANAGER_LOGGER)


def configure_logging() -> logging.Logger:
    """Attach a rotating file handler to the app logger (idempotent).

    Creates the log directory if it does not exist.  If a
    :class:`~logging.handlers.RotatingFileHandler` is already attached,
    this function returns immediately without adding a second handler.

    Returns:
        The configured :class:`logging.Logger`.  Safe to call once from
        ``main()`` after :class:`~PySide6.QtWidgets.QApplication` exists;
        the file I/O does not require the GUI event loop.
    """
    log = get_logger()
    log.setLevel(logging.DEBUG)
    log.propagate = False

    # Idempotency check — don't add a second rotating handler
    if any(isinstance(h, RotatingFileHandler) for h in log.handlers):
        return log

    path = log_dir()
    path.mkdir(parents=True, exist_ok=True)
    file_path = path / "app.log"

    fh = RotatingFileHandler(
        str(file_path),
        maxBytes=2_000_000,   # 2 MB per file
        backupCount=5,        # keep 5 backups
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    log.addHandler(fh)
    log.debug("Logging initialized; log file: %s", file_path)
    return log


def log_level_for_ui_line(text: str, color: str) -> int:
    """Map legacy ``_log(..., color=...)`` hints to :mod:`logging` severity levels.

    Used by the in-app log console to translate UI-level colour coding into
    standardised log levels for the file handler.

    Mapping
    -------
    * ``color == "#F44336"`` or text starts with ``[ERROR]`` → ``logging.ERROR``
    * ``color == "#FFA500"`` or text starts with ``[WARNING]`` → ``logging.WARNING``
    * Everything else → ``logging.INFO``

    Args:
        text: The log message text.
        color: HTML colour hex string used in the UI (e.g. ``"#F44336"``).

    Returns:
        The corresponding :mod:`logging` level constant.
    """
    t = text.strip()
    tc = t.casefold()
    if color == "#F44336" or tc.startswith("[error]"):
        return logging.ERROR
    if color == "#FFA500" or tc.startswith("[warning]"):
        return logging.WARNING
    return logging.INFO
