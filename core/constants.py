"""
Centralised constants for timeouts, retries, download settings, and
UI-friendly operational limits used across the entire application.

All values are designed to be imported by any module without circular
dependency risk (this file imports nothing except ``__future__``).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Catalog fetch timeouts
# ---------------------------------------------------------------------------

#: ``(connect_timeout, read_timeout)`` tuple in seconds for fetching the
#: remote distro catalog via HTTP (see :mod:`core.catalog_loader`).
CATALOG_TIMEOUT: tuple[int, int] = (5, 10)

# ---------------------------------------------------------------------------
# Download configuration
# ---------------------------------------------------------------------------

#: Chunk size (bytes) for streaming HTTP downloads — 128 KB.
#: Used by :class:`~core.downloader.DownloadManager`.
DOWNLOAD_CHUNK_SIZE: int = 1 << 17  # 131 072

#: TCP connect timeout (seconds) for download connections.
#: Used by :class:`~core.downloader.DownloadManager`.
DOWNLOAD_CONNECT_TIMEOUT: int = 15

#: Socket read timeout (seconds) for download connections.
#: Used by :class:`~core.downloader.DownloadManager`.
DOWNLOAD_READ_TIMEOUT: int = 60

#: Maximum retry attempts for a failed/resumable download.
#: Used by :class:`~core.downloader.DownloadManager`.
DOWNLOAD_MAX_RETRIES: int = 3

# ---------------------------------------------------------------------------
# WSL operation timeouts (seconds)
# ---------------------------------------------------------------------------

#: Timeout for ``wsl --import`` and ``wsl --export`` operations (10 min).
#: Large rootfs tars may take several minutes to import.
WSL_IMPORT_EXPORT_TIMEOUT: int = 600

#: Timeout for ``wsl --set-version`` conversion (5 min).
#: Converting between WSL 1 and WSL 2 requires a full filesystem copy.
WSL_SET_VERSION_TIMEOUT: int = 300

#: Timeout for the post-install user-home validation command (2 min).
#: Runs ``pwd && whoami`` from the new user's home directory.
WSL_VALIDATE_USER_TIMEOUT: int = 120

#: Timeout for checking if a Linux user account exists via ``id -u <user>``.
WSL_USER_EXISTS_TIMEOUT: int = 20

#: Timeout for querying the default user of a distro via ``wsl.conf`` parsing.
WSL_DEFAULT_USER_TIMEOUT: int = 25

#: Timeout for opening an interactive shell session to a distro.
WSL_SHELL_USER_TIMEOUT: int = 30

#: Timeout for collecting WSL diagnostic info (``wsl --version``, etc.).
WSL_DIAGNOSTIC_TIMEOUT: int = 60

#: Timeout for probing the runtime default user via ``bash -lc 'id -un'``.
#: Used by :class:`~utils.worker_threads.UserStatusProbeWorker`.
WSL_PROBE_USER_TIMEOUT: int = 20

# ---------------------------------------------------------------------------
# UI / display limits
# ---------------------------------------------------------------------------

#: Minimum refresh interval (seconds) for the dashboard auto-refresh timer.
#: Prevents excessive polling of ``wsl --list --verbose``.
AUTO_REFRESH_MIN_SECONDS: int = 15

#: Maximum number of log lines retained in the in-memory log buffer.
#: When exceeded, older lines are dropped to bound memory usage.
LOG_LINE_HARD_LIMIT: int = 5000
