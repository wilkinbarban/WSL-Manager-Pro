"""
ui/wsl_install_dialog.py
========================

Custom dialog to validate, install, and configure Windows Subsystem for Linux
(WSL) when it is missing from the host system.

Features:
- Compatibility checks: OS Build (>= 19041) and CPU virtualization enablement.
- Step-by-step progress tracking for background execution of 'wsl --install'.
- UAC elevation validation and reboot prompts.
"""
from __future__ import annotations

import subprocess
import sys

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from utils.i18n import t


def check_wsl_compatibility() -> tuple[bool, str]:
    """Check if the system supports WSL 2.

    Returns:
        tuple[bool, str]: (supported, reason)
    """
    if sys.platform != "win32":
        return False, t("This application only runs on Windows.")

    # Check OS build (must be >= 19041)
    build = sys.getwindowsversion().build
    if build < 19041:
        msg = t(
            "Your Windows build ({build}) is too old. "
            "WSL 2 requires Windows 10 Build 19041 or higher."
        )
        return False, msg.format(build=build)

    # Check BIOS virtualization
    try:
        cmd = [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "(Get-CimInstance -ClassName Win32_Processor).VirtualizationFirmwareEnabled"
        ]
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        if "False" in res.stdout:
            msg = t(
                "Hardware-assisted virtualization (VT-x/AMD-V) is disabled in your BIOS. "
                "Please enable virtualization in your BIOS/UEFI settings before continuing."
            )
            return False, msg
    except Exception:
        # Fallback to prevent blocking on query errors
        pass

    return True, ""


class WslInstallThread(QThread):
    """Background worker thread to install WSL."""

    finished = Signal(bool, int, str)  # success, exit_code, error_message

    def run(self) -> None:
        try:
            # Execute wsl --install --no-distribution
            res = subprocess.run(
                ["wsl.exe", "--install", "--no-distribution"],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            if res.returncode == 0:
                self.finished.emit(True, 0, "")
            else:
                err = (
                    res.stderr or res.stdout or
                    f"WSL install failed with exit code {res.returncode}"
                )
                self.finished.emit(False, res.returncode, err)
        except Exception as e:
            self.finished.emit(False, -1, str(e))


class WslInstallDialog(QDialog):
    """Guided WSL installation and configuration wizard."""

    def __init__(self, is_admin: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._is_admin = is_admin
        self._install_thread: WslInstallThread | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowTitle(t("WSL Installation Required"))
        self.setFixedSize(480, 260)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Header Title
        self.title_label = QLabel(t("Windows Subsystem for Linux (WSL)"))
        self.title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #00f0ff;")
        layout.addWidget(self.title_label)

        # Main Descriptive text
        self.desc_label = QLabel(
            t("WSL is required but was not found on your system. "
              "WSL Manager Pro can automatically enable required features and install WSL for you.")
        )
        self.desc_label.setWordWrap(True)
        self.desc_label.setStyleSheet("color: #e2e8f0; font-size: 12px;")
        layout.addWidget(self.desc_label)

        # Progress bar (hidden initially)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate spinner
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        layout.addStretch()

        # Action Buttons Layout
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)

        self.btn_quit = QPushButton(t("Quit"))
        self.btn_quit.clicked.connect(self.reject)

        self.btn_install = QPushButton(t("Install WSL"))
        self.btn_install.setStyleSheet(
            "background-color: #00e676; color: #090a0f; font-weight: bold;"
        )
        self.btn_install.clicked.connect(self._start_install)

        button_layout.addStretch()
        button_layout.addWidget(self.btn_quit)
        button_layout.addWidget(self.btn_install)
        layout.addLayout(button_layout)

    def _start_install(self) -> None:
        # Check compatibility first
        supported, reason = check_wsl_compatibility()
        if not supported:
            QMessageBox.critical(self, t("System Unsupported"), reason)
            return

        if not self._is_admin:
            # Need elevation - notify user and trigger relaunch
            QMessageBox.information(
                self,
                t("Administrator Rights Required"),
                t("Installing WSL requires Administrator privileges. "
                  "The application will now request elevation to proceed.")
            )
            self.done(2)  # Return code 2 indicates relaunch request
            return

        # Start installation UI state
        self.btn_install.setEnabled(False)
        self.btn_quit.setEnabled(False)
        self.progress_bar.setVisible(True)
        msg = t(
            "Activating Virtual Machine Platform and downloading WSL... "
            "This may take a few minutes."
        )
        self.desc_label.setText(msg)

        # Spawn installer worker thread
        self._install_thread = WslInstallThread()
        self._install_thread.finished.connect(self._on_install_finished)
        self._install_thread.start()

    def _on_install_finished(self, success: bool, exit_code: int, error_msg: str) -> None:
        self.progress_bar.setVisible(False)

        if success:
            msg = t(
                "WSL has been successfully installed! "
                "A system restart is required to apply the changes."
            )
            self.desc_label.setText(msg)

            # Change buttons to reboot prompts
            self.btn_install.setText(t("Reboot Now"))
            self.btn_install.setEnabled(True)
            self.btn_install.clicked.disconnect()
            self.btn_install.clicked.connect(self._trigger_reboot)

            self.btn_quit.setText(t("Reboot Later"))
            self.btn_quit.setEnabled(True)
            self.btn_quit.clicked.disconnect()
            self.btn_quit.clicked.connect(self.accept)
        else:
            self.btn_install.setEnabled(True)
            self.btn_quit.setEnabled(True)
            self.desc_label.setText(t("Failed to install WSL automatically."))
            msg = t(
                "WSL installation failed with code {code}.\n\n"
                "Detail: {detail}\n\n"
                "Please run 'wsl --install' manually as administrator."
            ).format(code=exit_code, detail=error_msg)
            QMessageBox.critical(
                self,
                t("Installation Error"),
                msg
            )

    def _trigger_reboot(self) -> None:
        try:
            # Trigger computer restart in 5 seconds
            subprocess.run(
                ["shutdown.exe", "/r", "/t", "5"],
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            QMessageBox.information(
                self,
                t("Rebooting System"),
                t("Your computer will restart in 5 seconds. Please save any open files.")
            )
            self.accept()
        except Exception as e:
            msg = t(
                "Could not trigger system restart automatically: {error}\n\n"
                "Please reboot your computer manually."
            ).format(error=str(e))
            QMessageBox.warning(
                self,
                t("Reboot Failed"),
                msg
            )
            self.accept()
