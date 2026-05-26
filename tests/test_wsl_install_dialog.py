"""
Unit tests for ui.wsl_install_dialog.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtWidgets = pytest.importorskip("PySide6.QtWidgets")


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_check_wsl_compatibility_supported() -> None:
    from ui.wsl_install_dialog import check_wsl_compatibility

    # Mock OS build >= 19041 and powershell command virtualization returning True
    mock_version = MagicMock()
    mock_version.build = 19045

    mock_run = MagicMock()
    mock_run.stdout = "True"
    mock_run.returncode = 0

    with patch("sys.getwindowsversion", return_value=mock_version), \
         patch("subprocess.run", return_value=mock_run):
        supported, reason = check_wsl_compatibility()
        assert supported
        assert not reason


def test_check_wsl_compatibility_old_build() -> None:
    from ui.wsl_install_dialog import check_wsl_compatibility

    mock_version = MagicMock()
    mock_version.build = 18363  # Windows 10 build 1909 (before 2004)

    with patch("sys.getwindowsversion", return_value=mock_version):
        supported, reason = check_wsl_compatibility()
        assert not supported
        assert "build" in reason or "old" in reason


def test_check_wsl_compatibility_no_virtualization() -> None:
    from ui.wsl_install_dialog import check_wsl_compatibility

    mock_version = MagicMock()
    mock_version.build = 19045

    mock_run = MagicMock()
    mock_run.stdout = "False"
    mock_run.returncode = 0

    with patch("sys.getwindowsversion", return_value=mock_version), \
         patch("subprocess.run", return_value=mock_run):
        supported, reason = check_wsl_compatibility()
        assert not supported
        reason_lower = reason.lower()
        assert (
            "virtualization" in reason_lower or
            "vt-x" in reason_lower or
            "disabled" in reason_lower
        )


def test_wsl_install_dialog_instantiation() -> None:
    from ui.wsl_install_dialog import WslInstallDialog

    _app()
    dialog = WslInstallDialog(is_admin=False)
    assert dialog.windowTitle()
    assert dialog.btn_install.isEnabled()
