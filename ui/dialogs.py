"""
ui/dialogs.py
=============

Modal dialogs and the multi-step Install Wizard for WSL Manager Pro.

All dialogs inherit from :class:`~PySide6.QtWidgets.QDialog` and present
a focused, self-contained UI for a single configuration task.  The
Install Wizard orchestrates the full distro installation flow across five
pages.

Dialogs
-------
* :class:`UserCreationDialog` — Username, password, sudo checkbox with
  regex validation.
* :class:`DirectoryDialog` — Install directory and download cache directory
  with file-browser buttons.
* :class:`SwapConfigDialog` — Memory / swap / processor spinboxes for
  ``.wslconfig`` generation.

Wizard
------
* :class:`InstallWizard` — 5-page guided installer:
  1. **Select Distro** — Choose from the merged catalog (``distros.json``
     + ``wsl --list --online``).
  2. **Configure Paths** — WSL name, install directory, download directory,
     WSL version, external PowerShell toggle.
  3. **User Account** — Username/password (optional), system update,
     systemd, profile save/load.
  4. **Summary** — Read-only HTML review before launching.
  5. **Progress** — Live log + progress bar during installation.

Helper functions
----------------
* :func:`_browse_dir` — Open a folder picker and update a :class:`QLineEdit`.
* :func:`_browse_file` — Open a file picker and update a :class:`QLineEdit`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from utils.i18n import get_i18n, t


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _browse_dir(parent: QWidget, line_edit: QLineEdit, title: str = "Select directory") -> None:
    path = QFileDialog.getExistingDirectory(parent, t(title), line_edit.text() or "")
    if path:
        line_edit.setText(path)


def _browse_file(
    parent: QWidget,
    line_edit: QLineEdit,
    title: str = "Select file",
    filter_: str = "All files (*)",
) -> None:
    path, _ = QFileDialog.getOpenFileName(parent, t(title), line_edit.text() or "", t(filter_))
    if path:
        line_edit.setText(path)


# ---------------------------------------------------------------------------
# UserCreationDialog
# ---------------------------------------------------------------------------

class UserCreationDialog(QDialog):
    """
    Collect a username and password for the new Linux user.

    Attributes
    ----------
    username : str
    password : str
    add_sudo : bool
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._i18n = get_i18n()
        self.setMinimumWidth(380)
        self._build_ui()
        self._i18n.language_changed.connect(lambda _lang: self.retranslate_ui())
        self.retranslate_ui()

    def _build_ui(self) -> None:
        self._form = QFormLayout()
        self._form.setSpacing(10)

        self._lbl_username = QLabel()
        self._username = QLineEdit()
        self._username.setPlaceholderText(t("e.g. devuser"))
        self._form.addRow(self._lbl_username, self._username)

        self._lbl_password = QLabel()
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._password.setPlaceholderText(t("Password"))
        self._form.addRow(self._lbl_password, self._password)

        self._lbl_confirm = QLabel()
        self._confirm = QLineEdit()
        self._confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self._confirm.setPlaceholderText(t("Confirm password"))
        self._form.addRow(self._lbl_confirm, self._confirm)

        self._sudo = QCheckBox()
        self._sudo.setChecked(True)
        self._form.addRow("", self._sudo)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self._validate_and_accept)
        self._buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addLayout(self._form)
        layout.addWidget(self._buttons)
        self.setLayout(layout)

    def retranslate_ui(self) -> None:
        self.setWindowTitle(t("Create Linux User"))
        self._lbl_username.setText(t("Username:"))
        self._username.setPlaceholderText(t("e.g. devuser"))
        self._lbl_password.setText(t("Password:"))
        self._password.setPlaceholderText(t("Password"))
        self._lbl_confirm.setText(t("Confirm:"))
        self._confirm.setPlaceholderText(t("Confirm password"))
        self._sudo.setText(t("Add user to sudo / wheel group"))
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText(t("OK"))
        self._buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t("Cancel"))

    def _validate_and_accept(self) -> None:
        import re
        username = self._username.text().strip()
        password = self._password.text()
        confirm  = self._confirm.text()

        if not re.match(r"^[a-z_][a-z0-9_-]{0,30}$", username):
            QMessageBox.warning(
                self, t("Invalid username"),
                t(
                    "Username must start with a lowercase letter or underscore "
                    "and contain only letters, digits, underscores, or hyphens."
                )
            )
            return
        if len(password) < 4:
            QMessageBox.warning(
                self,
                t("Weak password"),
                t("Password must be at least 4 characters."),
            )
            return
        if password != confirm:
            QMessageBox.warning(self, t("Password mismatch"),
                                t("Passwords do not match."))
            return
        self.accept()

    @property
    def username(self) -> str:
        return self._username.text().strip()

    @property
    def password(self) -> str:
        return self._password.text()

    @property
    def add_sudo(self) -> bool:
        return self._sudo.isChecked()


# ---------------------------------------------------------------------------
# DirectoryDialog
# ---------------------------------------------------------------------------

class DirectoryDialog(QDialog):
    """
    Configure the default install directory and download/cache directory.
    """

    def __init__(self, install_dir: str, download_dir: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("Configure Directories"))
        self.setMinimumWidth(500)
        self._build_ui(install_dir, download_dir)

    def _build_ui(self, install_dir: str, download_dir: str) -> None:
        layout = QVBoxLayout()
        layout.setSpacing(12)

        # Install dir
        install_group = QGroupBox(t("WSL Installation Directory"))
        install_layout = QHBoxLayout()
        self._install_edit = QLineEdit(install_dir)
        btn_install = QPushButton(t("Browse..."))
        btn_install.clicked.connect(
            lambda: _browse_dir(self, self._install_edit, "Select install directory")
        )
        install_layout.addWidget(self._install_edit)
        install_layout.addWidget(btn_install)
        install_group.setLayout(install_layout)

        # Download dir
        dl_group = QGroupBox(t("Download Cache Directory"))
        dl_layout = QHBoxLayout()
        self._download_edit = QLineEdit(download_dir)
        btn_dl = QPushButton(t("Browse..."))
        btn_dl.clicked.connect(
            lambda: _browse_dir(self, self._download_edit, "Select download directory")
        )
        dl_layout.addWidget(self._download_edit)
        dl_layout.addWidget(btn_dl)
        dl_group.setLayout(dl_layout)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addWidget(install_group)
        layout.addWidget(dl_group)
        layout.addWidget(buttons)
        self.setLayout(layout)

    @property
    def install_dir(self) -> str:
        return self._install_edit.text().strip()

    @property
    def download_dir(self) -> str:
        return self._download_edit.text().strip()


# ---------------------------------------------------------------------------
# SwapConfigDialog
# ---------------------------------------------------------------------------

class SwapConfigDialog(QDialog):
    """
    Configure .wslconfig memory / swap / processor limits.
    """

    def __init__(
        self,
        memory_gb: int,
        swap_gb: int,
        processors: int,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("WSL2 Resource Limits (.wslconfig)"))
        self.setMinimumWidth(360)
        self._build_ui(memory_gb, swap_gb, processors)

    def _build_ui(self, memory_gb: int, swap_gb: int, processors: int) -> None:
        form = QFormLayout()
        form.setSpacing(10)

        self._memory = QSpinBox()
        self._memory.setRange(1, 256)
        self._memory.setSuffix(" GB")
        self._memory.setValue(memory_gb)
        form.addRow(t("Memory limit:"), self._memory)

        self._swap = QSpinBox()
        self._swap.setRange(0, 128)
        self._swap.setSuffix(" GB")
        self._swap.setValue(swap_gb)
        form.addRow(t("Swap size:"), self._swap)

        self._processors = QSpinBox()
        self._processors.setRange(1, 256)
        self._processors.setSuffix(" core(s)")
        self._processors.setValue(processors)
        form.addRow(t("Processor count:"), self._processors)

        note = QLabel(
            t(
                "Changes take effect after running <b>wsl --shutdown</b> and restarting your distributions."
            )
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #888888; font-size: 11px;")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(buttons)
        self.setLayout(layout)

    @property
    def memory_gb(self) -> int:
        return self._memory.value()

    @property
    def swap_gb(self) -> int:
        return self._swap.value()

    @property
    def processors(self) -> int:
        return self._processors.value()


# ---------------------------------------------------------------------------
# Install Wizard
# ---------------------------------------------------------------------------

class InstallWizard(QDialog):
    """
    Five-step guided installer for a WSL distribution.

    Collect all parameters → confirm → run the InstallWorker in-dialog.

    Public attributes after acceptance (step 3)
    -------------------------------------------
    selected_distro_id : str    (key from distros.json)
    wsl_name           : str    (WSL registration name)
    install_dir        : str
    download_dir       : str
    username           : str    (may be empty = skip user creation)
    password           : str
    """

    def __init__(
        self,
        distros: dict,
        install_dir: str,
        download_dir: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("Install New Distribution"))
        self.setMinimumSize(620, 480)
        self.setModal(True)

        self._distros      = distros
        self._install_dir  = install_dir
        self._download_dir = download_dir

        # Result attributes filled during wizard
        self.selected_distro_id: str = ""
        self.wsl_name: str = ""
        self.install_dir: str = install_dir
        self.download_dir: str = download_dir
        self.username: str = ""
        self.password: str = ""
        self.run_in_external_powershell: bool = True
        self.run_system_update: bool = True
        self.enable_systemd: bool = True

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self._stack = QStackedWidget()
        self._stack.addWidget(self._page_select_distro())
        self._stack.addWidget(self._page_paths())
        self._stack.addWidget(self._page_user())
        self._stack.addWidget(self._page_summary())

        # Navigation buttons
        self._btn_back   = QPushButton(t("< Back"))
        self._btn_next   = QPushButton(t("Next >"))
        self._btn_cancel = QPushButton(t("Cancel"))
        self._btn_next.setDefault(True)

        self._btn_back.clicked.connect(self._go_back)
        self._btn_next.clicked.connect(self._go_next)
        self._btn_cancel.clicked.connect(self.reject)

        nav = QHBoxLayout()
        nav.addWidget(self._btn_cancel)
        nav.addStretch()
        nav.addWidget(self._btn_back)
        nav.addWidget(self._btn_next)

        # Step indicator
        self._step_label = QLabel()
        self._step_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._step_label.setStyleSheet("color: #888; font-size: 11px;")

        root = QVBoxLayout()
        root.addWidget(self._stack)
        root.addWidget(self._step_label)
        root.addLayout(nav)
        self.setLayout(root)

        self._update_nav()
        self._apply_selected_distro_defaults()

    # ------------------------------------------------------------------
    # Page 0 - distro selection
    # ------------------------------------------------------------------

    def _page_select_distro(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        header = QLabel(t("Select a distribution to install:"))
        header.setStyleSheet("font-size: 14px; font-weight: bold; margin-bottom: 6px;")
        layout.addWidget(header)

        self._distro_list = QListWidget()
        self._distro_list.setSpacing(2)
        for did, dcfg in self._distros.items():
            item = QListWidgetItem(dcfg.get("display_name", did))
            item.setData(Qt.ItemDataRole.UserRole, did)
            item.setToolTip(dcfg.get("description", ""))
            self._distro_list.addItem(item)
        self._distro_list.currentItemChanged.connect(
            lambda _cur, _prev: self._apply_selected_distro_defaults()
        )
        self._distro_list.setCurrentRow(0)
        layout.addWidget(self._distro_list)

        return page

    # ------------------------------------------------------------------
    # Page 1 - paths + WSL name
    # ------------------------------------------------------------------

    def _page_paths(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setSpacing(10)

        self._wsl_name_edit = QLineEdit()
        self._wsl_name_edit.setPlaceholderText(t("e.g. Ubuntu-Dev"))
        form.addRow(t("WSL distribution name:"), self._wsl_name_edit)

        install_row = QHBoxLayout()
        self._install_edit = QLineEdit(self._install_dir)
        self._btn_install_browse = QPushButton(t("Browse..."))
        self._btn_install_browse.clicked.connect(lambda: _browse_dir(page, self._install_edit))
        install_row.addWidget(self._install_edit)
        install_row.addWidget(self._btn_install_browse)
        self._install_row_widget = QWidget()
        self._install_row_widget.setLayout(install_row)
        form.addRow(t("Install directory:"), self._install_row_widget)

        dl_row = QHBoxLayout()
        self._dl_edit = QLineEdit(self._download_dir)
        self._btn_dl_browse = QPushButton(t("Browse..."))
        self._btn_dl_browse.clicked.connect(lambda: _browse_dir(page, self._dl_edit))
        dl_row.addWidget(self._dl_edit)
        dl_row.addWidget(self._btn_dl_browse)
        self._download_row_widget = QWidget()
        self._download_row_widget.setLayout(dl_row)
        form.addRow(t("Download directory:"), self._download_row_widget)

        self._wsl_ver = QSpinBox()
        self._wsl_ver.setRange(1, 2)
        self._wsl_ver.setValue(2)
        form.addRow(t("WSL version:"), self._wsl_ver)

        self._external_ps_check = QCheckBox(t("Run installation in separate PowerShell window"))
        self._external_ps_check.setChecked(True)
        self._external_ps_check.setToolTip(
            t("Shows complete wsl output in a dedicated console for troubleshooting.")
        )
        form.addRow("", self._external_ps_check)

        self._legacy_path_note = QLabel(
            t(
                "Oracle Linux and SUSE Linux Enterprise 15 SP6 use distro-native first boot and repair flow.\n"
                "Install/download directory selection is disabled for this installer path."
            )
        )
        self._legacy_path_note.setWordWrap(True)
        self._legacy_path_note.setStyleSheet("color: #bdbdbd;")
        self._legacy_path_note.setVisible(False)
        form.addRow("", self._legacy_path_note)

        return page

    # ------------------------------------------------------------------
    # Page 2 - user creation (optional)
    # ------------------------------------------------------------------

    def _page_user(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self._skip_user = QCheckBox(t("Skip user creation (log in as root)"))
        self._skip_user.toggled.connect(self._on_skip_user_toggled)
        layout.addWidget(self._skip_user)

        self._update_system_check = QCheckBox(t("Run full system update during install"))
        self._update_system_check.setChecked(True)
        self._update_system_check.setToolTip(t("Example: apt-get update && apt-get upgrade -y"))
        layout.addWidget(self._update_system_check)

        self._systemd_check = QCheckBox(t("Enable systemd when the distro supports it"))
        self._systemd_check.setChecked(True)
        layout.addWidget(self._systemd_check)

        profile_row = QHBoxLayout()
        self._btn_import_profile = QPushButton(t("Load Profile..."))
        self._btn_import_profile.clicked.connect(self._load_profile)
        self._btn_export_profile = QPushButton(t("Save Profile..."))
        self._btn_export_profile.clicked.connect(self._save_profile)
        profile_row.addWidget(self._btn_import_profile)
        profile_row.addWidget(self._btn_export_profile)
        profile_row.addStretch()
        layout.addLayout(profile_row)

        self._user_group = QGroupBox(t("New user account"))
        form = QFormLayout(self._user_group)
        form.setSpacing(8)

        self._user_edit = QLineEdit()
        self._user_edit.setPlaceholderText(t("e.g. devuser"))
        form.addRow(t("Username:"), self._user_edit)

        self._pass_edit = QLineEdit()
        self._pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(t("Password:"), self._pass_edit)

        self._pass_confirm = QLineEdit()
        self._pass_confirm.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(t("Confirm password:"), self._pass_confirm)

        self._sudo_check = QCheckBox(t("Add to sudo / wheel group"))
        self._sudo_check.setChecked(True)
        form.addRow("", self._sudo_check)

        layout.addWidget(self._user_group)

        self._legacy_user_note = QLabel(
            t("For Oracle Linux and SUSE Linux Enterprise 15 SP6, user creation is handled in the distro first-boot interface.")
        )
        self._legacy_user_note.setWordWrap(True)
        self._legacy_user_note.setStyleSheet("color: #bdbdbd;")
        self._legacy_user_note.setVisible(False)
        layout.addWidget(self._legacy_user_note)
        layout.addStretch()
        return page

    def _on_skip_user_toggled(self, skip: bool) -> None:
        self._user_group.setEnabled(not skip)

    # ------------------------------------------------------------------
    # Page 3 - summary
    # ------------------------------------------------------------------

    def _page_summary(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        header = QLabel(t("Review your configuration:"))
        header.setStyleSheet("font-size: 14px; font-weight: bold; margin-bottom: 6px;")
        layout.addWidget(header)

        self._summary_label = QLabel()
        self._summary_label.setWordWrap(True)
        self._summary_label.setTextFormat(Qt.TextFormat.RichText)
        self._summary_label.setStyleSheet(
            "background-color: #252526; padding: 12px; border-radius: 4px;"
        )
        layout.addWidget(self._summary_label)
        layout.addStretch()

        note = QLabel(t("Click <b>Install</b> to begin - this may take several minutes."))
        note.setWordWrap(True)
        layout.addWidget(note)
        return page

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _current_page(self) -> int:
        return self._stack.currentIndex()

    def _update_nav(self) -> None:
        page = self._current_page()
        total = self._stack.count()
        self._btn_back.setEnabled(page > 0)
        if page == total - 1:
            self._btn_next.setText(t("Install"))
        else:
            self._btn_next.setText(t("Next >"))
        self._step_label.setText(t("Step {current} of {total}", current=page + 1, total=total))

    def _go_next(self) -> None:
        page = self._current_page()
        if not self._validate_page(page):
            return
        if page == self._stack.count() - 1:
            self._collect_results()
            self.accept()
            return
        if page == self._stack.count() - 2:
            self._populate_summary()
        self._stack.setCurrentIndex(page + 1)
        self._update_nav()

    def _go_back(self) -> None:
        page = self._current_page()
        if page > 0:
            self._stack.setCurrentIndex(page - 1)
            self._update_nav()

    # ------------------------------------------------------------------
    # Validation per page
    # ------------------------------------------------------------------

    def _validate_page(self, page: int) -> bool:
        if page == 0:
            if not self._distro_list.currentItem():
                QMessageBox.warning(self, t("No selection"), t("Please select a distribution."))
                return False

        elif page == 1:
            name = self._wsl_name_edit.text().strip()
            if not name:
                # Auto-fill from selected distro
                self._wsl_name_edit.setText(self._suggested_wsl_name())
            cfg = self._selected_distro_cfg()
            if cfg.get("install_method") == "wsl_online":
                expected = self._suggested_wsl_name()
                if self._wsl_name_edit.text().strip() != expected:
                    self._wsl_name_edit.setText(expected)
            if (not self._is_legacy_interactive_install()) and not self._install_edit.text().strip():
                QMessageBox.warning(self, t("Missing path"), t("Please specify an install directory."))
                return False
            if (not self._is_legacy_interactive_install()) and not self._dl_edit.text().strip():
                QMessageBox.warning(self, t("Missing path"), t("Please specify a download directory."))
                return False

        elif page == 2:
            if self._is_legacy_interactive_install():
                return True
            if not self._skip_user.isChecked():
                if not self._validate_user_credentials():
                    return False
        return True

    # ------------------------------------------------------------------
    # Summary population
    # ------------------------------------------------------------------

    def _populate_summary(self) -> None:
        item = self._distro_list.currentItem()
        distro_name = item.text() if item else "?"
        wsl_name    = self._wsl_name_edit.text().strip()
        install_dir = self._install_edit.text().strip()
        dl_dir      = self._dl_edit.text().strip()
        user_line   = (
            f"<b>{t('User')}:</b> {self._user_edit.text().strip()} (sudo)"
            if not self._skip_user.isChecked()
            else f"<b>{t('User')}:</b> <i>{t('skip')}</i>"
        )
        if self._is_legacy_interactive_install():
            user_line = f"<b>{t('User')}:</b> <i>{t('Created in distro first-boot interface')}</i>"
        html = (
            f"<b>{t('Distribution')}:</b> {distro_name}<br>"
            f"<b>{t('WSL name')}:</b> {wsl_name}<br>"
            f"<b>{t('Install directory')}:</b> {install_dir}<br>"
            f"<b>{t('Download directory')}:</b> {dl_dir}<br>"
            f"<b>{t('WSL version')}:</b> {self._wsl_ver.value()}<br>"
            f"<b>{t('System update')}:</b> {t('yes') if self._update_system_check.isChecked() else t('no')}<br>"
            f"<b>systemd:</b> {t('yes') if self._systemd_check.isChecked() else t('no')}<br>"
            f"{user_line}"
        )
        self._summary_label.setText(html)

    # ------------------------------------------------------------------
    # Collect final result
    # ------------------------------------------------------------------

    def _collect_results(self) -> None:
        item = self._distro_list.currentItem()
        self.selected_distro_id = item.data(Qt.ItemDataRole.UserRole) if item else ""
        cfg = self._selected_distro_cfg()
        if cfg.get("install_method") == "wsl_online":
            self.wsl_name = self._suggested_wsl_name()
        else:
            self.wsl_name = self._wsl_name_edit.text().strip() or self.selected_distro_id
        self.install_dir  = self._install_edit.text().strip()
        self.download_dir = self._dl_edit.text().strip()
        self.run_in_external_powershell = self._external_ps_check.isChecked()
        self.run_system_update = self._update_system_check.isChecked()
        self.enable_systemd = self._systemd_check.isChecked()
        if self._is_legacy_interactive_install():
            self.username = ""
            self.password = ""
            return
        if not self._skip_user.isChecked():
            if not self._validate_user_credentials():
                raise ValueError("User credentials became invalid before finishing the wizard.")
            self.username = self._user_edit.text().strip()
            self.password = self._pass_edit.text()
        else:
            self.username = ""
            self.password = ""

    # ------------------------------------------------------------------
    # WSL version accessor
    # ------------------------------------------------------------------

    @property
    def wsl_version(self) -> int:
        return self._wsl_ver.value()

    def _selected_distro_cfg(self) -> dict:
        item = self._distro_list.currentItem()
        if not item:
            return {}
        distro_id = item.data(Qt.ItemDataRole.UserRole)
        return self._distros.get(distro_id, {})

    def _suggested_wsl_name(self) -> str:
        item = self._distro_list.currentItem()
        if not item:
            return ""
        distro_id = item.data(Qt.ItemDataRole.UserRole)
        cfg = self._distros.get(distro_id, {})
        return str(cfg.get("online_name") or distro_id)

    def _apply_selected_distro_defaults(self) -> None:
        if not hasattr(self, "_wsl_name_edit"):
            return
        cfg = self._selected_distro_cfg()
        suggested = self._suggested_wsl_name()
        is_online = cfg.get("install_method") == "wsl_online"
        is_legacy = self._is_legacy_interactive_install(cfg)
        self._wsl_name_edit.setEnabled(not is_online)
        if hasattr(self, "_external_ps_check"):
            if is_online:
                self._external_ps_check.setChecked(True)
                self._external_ps_check.setEnabled(False)
                self._external_ps_check.setToolTip(
                    t(
                        "Online distros use the external installer so selected install/cache directories and user injection are honored."
                    )
                )
            else:
                self._external_ps_check.setEnabled(True)
                self._external_ps_check.setToolTip(
                    t("Shows complete wsl output in a dedicated console for troubleshooting.")
                )
        if suggested:
            if is_online or not self._wsl_name_edit.text().strip():
                self._wsl_name_edit.setText(suggested)
        if hasattr(self, "_systemd_check"):
            self._systemd_check.setChecked(bool(cfg.get("systemd", False)))
            self._systemd_check.setEnabled(not is_legacy)

        if hasattr(self, "_install_row_widget"):
            self._install_row_widget.setVisible(not is_legacy)
        if hasattr(self, "_download_row_widget"):
            self._download_row_widget.setVisible(not is_legacy)
        if hasattr(self, "_legacy_path_note"):
            self._legacy_path_note.setVisible(is_legacy)

        if hasattr(self, "_skip_user"):
            self._skip_user.setVisible(not is_legacy)
        if hasattr(self, "_user_group"):
            self._user_group.setVisible(not is_legacy)
        if hasattr(self, "_legacy_user_note"):
            self._legacy_user_note.setVisible(is_legacy)
        if is_legacy:
            self._skip_user.setChecked(True)

    def _is_legacy_interactive_install(self, cfg: Optional[dict] = None) -> bool:
        data = cfg if cfg is not None else self._selected_distro_cfg()
        online_name = str(data.get("online_name", "")).lower()
        display = str(data.get("display_name", "")).lower()
        return (
            online_name.startswith("oraclelinux_")
            or online_name == "suse-linux-enterprise-15-sp6"
            or "oracle linux" in display
            or "suse linux enterprise 15 sp6" in display
        )

    def _current_profile_payload(self) -> dict:
        return {
            "profile_version": 1,
            "selected_distro_id": self._distro_list.currentItem().data(Qt.ItemDataRole.UserRole)
            if self._distro_list.currentItem()
            else "",
            "wsl_name": self._wsl_name_edit.text().strip(),
            "install_dir": self._install_edit.text().strip(),
            "download_dir": self._dl_edit.text().strip(),
            "run_system_update": self._update_system_check.isChecked(),
            "enable_systemd": self._systemd_check.isChecked(),
            "username": self._user_edit.text().strip(),
        }

    def _save_profile(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            t("Save install profile"),
            str(Path.home() / "wsl-install-profile.json"),
            t("JSON files (*.json)"),
        )
        if not path:
            return
        Path(path).write_text(json.dumps(self._current_profile_payload(), indent=2), encoding="utf-8")
        QMessageBox.information(
            self,
            t("Profile saved"),
            t("Profile saved without the password. You will still enter the password at install time."),
        )

    def _load_profile(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            t("Load install profile"),
            str(Path.home()),
            t("JSON files (*.json)"),
        )
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            QMessageBox.warning(self, t("Profile load failed"), str(exc))
            return
        if payload.get("profile_version") != 1:
            QMessageBox.warning(self, t("Profile load failed"), t("Unsupported profile_version."))
            return
        distro_id = str(payload.get("selected_distro_id", "")).strip()
        if distro_id:
            for idx in range(self._distro_list.count()):
                item = self._distro_list.item(idx)
                if item and item.data(Qt.ItemDataRole.UserRole) == distro_id:
                    self._distro_list.setCurrentRow(idx)
                    break
        self._wsl_name_edit.setText(str(payload.get("wsl_name", self._wsl_name_edit.text())).strip())
        self._install_edit.setText(str(payload.get("install_dir", self._install_edit.text())).strip())
        self._dl_edit.setText(str(payload.get("download_dir", self._dl_edit.text())).strip())
        self._update_system_check.setChecked(bool(payload.get("run_system_update", True)))
        self._systemd_check.setChecked(bool(payload.get("enable_systemd", True)))
        self._user_edit.setText(str(payload.get("username", "")).strip())

    def _validate_user_credentials(self) -> bool:
        import re

        username = self._user_edit.text().strip()
        password = self._pass_edit.text()
        confirm = self._pass_confirm.text()
        if not re.match(r"^[a-z_][a-z0-9_-]{0,30}$", username):
            QMessageBox.warning(
                self,
                t("Invalid username"),
                t("Use lowercase letters, digits, underscores, and hyphens only."),
            )
            return False
        if len(password) < 4:
            QMessageBox.warning(
                self,
                t("Weak password"),
                t("Password must be at least 4 characters."),
            )
            return False
        if password != confirm:
            QMessageBox.warning(self, t("Mismatch"), t("Passwords do not match."))
            return False
        return True
