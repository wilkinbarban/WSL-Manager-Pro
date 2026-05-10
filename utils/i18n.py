"""
utils/i18n.py
=============

Runtime internationalisation (i18n) support for WSL Manager Pro.

Loads JSON translation bundles from ``resources/i18n/<lang>.json`` at
startup and exposes a module-level :func:`t` function for use throughout
the application.  Supports live language switching via the :class:`I18nManager`
singleton's ``language_changed`` :class:`~PySide6.QtCore.Signal`.

Supported languages
-------------------
* ``en`` — English (default, fallback).
* ``es`` — Español (Spanish).
* ``pt`` — Português (Brazilian Portuguese).

Key concepts
------------
* **Singleton pattern** — One :class:`I18nManager` instance (`_I18N`) shared
  by all modules.  Thread-safe reads are fine; writes (``set_language``)
  should happen only on the GUI thread.
* **Fallback chain** — If a key is missing in the current language, the
  English catalog is checked.  If still missing, the key itself is returned
  as-is (so untranslated keys are visible in the UI).
* **Formatting** — The :func:`t` function supports Python ``str.format()``
  keyword arguments (e.g. ``t("hello {name}", name="World")``).
* **PyInstaller support** — Uses ``sys._MEIPASS`` when bundled, falling
  back to the project root for development.

Usage::

    from utils.i18n import t
    label.setText(t("Install"))
    label.setText(t("Downloaded {pct}%", pct=75))
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Final

# Graceful fallback when PySide6 is not available (e.g., headless tests)
try:
    from PySide6.QtCore import QObject, Signal
except ModuleNotFoundError:
    # --- Minimal fallback for non-GUI environments ---
    class _FallbackSignal:
        """Stand-in for PySide6 Signal when the Qt bindings are unavailable."""

        def __init__(self, *_args, **_kwargs) -> None:
            self._callbacks: list = []

        def connect(self, callback) -> None:
            self._callbacks.append(callback)

        def emit(self, *args, **kwargs) -> None:
            for callback in list(self._callbacks):
                callback(*args, **kwargs)

    class QObject:  # type: ignore[no-redef]
        def __init__(self, *_args, **_kwargs) -> None:
            pass

    def Signal(*_args, **_kwargs):  # type: ignore[misc]
        return _FallbackSignal()


#: Supported language codes (ISO 639-1, lowercase).
#: Used for validation and for iterating over catalog files.
SUPPORTED_LANGUAGES: Final[tuple[str, ...]] = ("en", "es", "pt")

#: Human-readable labels for each supported language.
#: Displayed in the language selector UI.
LANGUAGE_LABELS: Final[dict[str, str]] = {
    "en": "English",
    "es": "Español",
    "pt": "Português",
}


def _resource_root() -> Path:
    """Return the root directory for resource lookups.

    When running from a PyInstaller bundle, uses ``sys._MEIPASS``
    (the temporary extraction directory).  Otherwise, returns the
    project root (parent of ``utils/``).
    """
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent.parent


class I18nManager(QObject):
    """Runtime language store with live-change notifications.

    Emits :attr:`language_changed` whenever :meth:`set_language` is called
    with a different language code.  UI widgets connect to this signal to
    refresh their translatable strings.

    Attributes
    ----------
    language_changed : Signal(str)
        Emitted with the new language code after a successful change.
    """

    language_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._language: str = "en"
        self._catalogs: dict[str, dict[str, str]] = {}
        self._load_catalogs()

    @property
    def language(self) -> str:
        """The currently active language code (e.g. ``"en"``)."""
        return self._language

    def set_language(self, language: str) -> None:
        """Switch the active language.

        Normalises the input to lowercase and validates against
        :data:`SUPPORTED_LANGUAGES`.  If the language is unsupported, it
        falls back to ``"en"``.  If the language is the same as the current
        one, no action is taken (no signal emitted).

        Args:
            language: Language code (case-insensitive), e.g. ``"ES"`` or
                ``"pt"``.
        """
        normalized = language.strip().lower()
        if normalized not in SUPPORTED_LANGUAGES:
            normalized = "en"
        if normalized == self._language:
            return
        self._language = normalized
        self.language_changed.emit(normalized)

    def label_for(self, language: str) -> str:
        """Return a human-readable label for *language*.

        Args:
            language: Language code (e.g. ``"es"``).

        Returns:
            The label (e.g. ``"Español"``), or the code itself if not found.
        """
        return LANGUAGE_LABELS.get(language, language)

    def translate(self, key: str, **kwargs) -> str:
        """Translate *key* into the current language.

        **Fallback chain:**
        1. Look up *key* in the current language catalog.
        2. If not found, look up in the English (``"en"``) catalog.
        3. If still not found, return *key* itself (untranslated).

        **String formatting:**
        If *kwargs* are provided, the translated string is formatted with
        ``str.format(**kwargs)``.  If formatting fails, the raw translation
        is returned without raising.

        Args:
            key: Translation key (matches keys in ``resources/i18n/*.json``).
            **kwargs: Optional format arguments.

        Returns:
            The translated (and optionally formatted) string.
        """
        lang_catalog = self._catalogs.get(self._language, {})
        text = lang_catalog.get(key)
        if text is None:
            # Fall back to English
            text = self._catalogs.get("en", {}).get(key, key)
        if kwargs:
            try:
                return text.format(**kwargs)
            except Exception:
                return text
        return text

    def _load_catalogs(self) -> None:
        """Load all JSON translation bundles from disk.

        Catalogs that fail to parse are stored as empty dicts (keys will
        fall back to English).  This ensures the application can start even
        if translation files are corrupted or missing.
        """
        base = _resource_root() / "resources" / "i18n"
        for language in SUPPORTED_LANGUAGES:
            path = base / f"{language}.json"
            try:
                self._catalogs[language] = json.loads(path.read_text(encoding="utf-8"))
            except OSError:
                self._catalogs[language] = {}
            except json.JSONDecodeError:
                self._catalogs[language] = {}


#: Module-level singleton — created at import time.
#: All modules access translations through this instance.
_I18N = I18nManager()


def get_i18n() -> I18nManager:
    """Return the module-level :class:`I18nManager` singleton.

    Useful when a module needs to connect to the ``language_changed`` signal
    or inspect the current language directly.
    """
    return _I18N


def t(key: str, **kwargs) -> str:
    """Convenience function: translate *key* using the global i18n singleton.

    Equivalent to ``get_i18n().translate(key, **kwargs)``.

    Args:
        key: Translation key.
        **kwargs: Optional format arguments passed to ``str.format()``.

    Returns:
        The translated string.
    """
    return _I18N.translate(key, **kwargs)
