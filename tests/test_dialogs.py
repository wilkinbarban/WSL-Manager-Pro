"""
Smoke tests for Qt dialogs in :mod:`ui.dialogs`.

Runs with ``QT_QPA_PLATFORM=offscreen`` for headless execution.

Covers:
* ``UserCreationDialog`` — Instantiation and ``retranslate_ui()`` without crash.
"""
from __future__ import annotations

import os

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
