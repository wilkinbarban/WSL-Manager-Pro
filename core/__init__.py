"""
core
====

Core package for WSL Manager Pro.

Provides the low-level business logic for interacting with WSL (Windows
Subsystem for Linux) on Windows, including:

* **WslEngine** — High-level facade around ``wsl.exe`` for distro management,
  command execution, post-install configuration, and Windows tool integration
  (winget, DISM, PowerShell).
* **DownloadManager** — Thread-friendly HTTP downloader with resume support,
  checksum verification, and archive extraction (APPX, Arch bootstrap).
* **Catalog loader** — Validates and merges local/remote distro catalogs
  (``distros.json``) with strict schema enforcement.
* **WSL list parser** — Pure functions that parse the text output of
  ``wsl --list --verbose`` and ``wsl --list --online`` without spawning
  subprocesses (unit-testable on any OS).
* **Constants** — Centralised timeout, retry, chunk-size, and UI-limit values
  shared across the project.
"""
