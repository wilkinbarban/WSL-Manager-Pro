"""
utils
=====

Utility package for WSL Manager Pro.

Provides cross-cutting services used by both the core engine and the UI:

* **app_logging** — Rotating file logger (``%LOCALAPPDATA%\\WSLManagerPro\\logs\\app.log``)
  with password-sanitization contract.
* **config_manager** — Persistent JSON configuration (``%APPDATA%\\WSLManagerPro\\config.json``)
  with schema versioning, migration, and validation.
* **diagnostic_bundle** — ZIP bundle generator for troubleshooting
  (captures app version, log tail, ``wsl --version``, ``wsl --status``).
* **i18n** — Runtime internationalisation with live language switching
  (English, Spanish, Portuguese).
* **worker_threads** — :class:`~PySide6.QtCore.QThread`-based workers for
  background operations (downloads, imports, exports, post-install, refresh).
"""
