"""
Smoke tests for Qt dialogs in :mod:`ui.dialogs`.

Runs with ``QT_QPA_PLATFORM=offscreen`` for headless execution.

Covers:
* ``UserCreationDialog`` — Instantiation and ``retranslate_ui()`` without crash.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtWidgets = pytest.importorskip("PySide6.QtWidgets")


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_user_creation_dialog_retranslate_does_not_crash() -> None:
    from ui.dialogs import UserCreationDialog

    _app()
    dialog = UserCreationDialog()
    dialog.retranslate_ui()
    assert dialog.windowTitle()


def test_deep_clean_rejects_dangerous_directories(tmp_path) -> None:
    from ui.main_window import MainWindow

    assert MainWindow._unsafe_cleanup_dir_reason(Path.home())
    assert MainWindow._unsafe_cleanup_dir_reason(Path.cwd())
    assert not MainWindow._unsafe_cleanup_dir_reason(tmp_path / "cache")
