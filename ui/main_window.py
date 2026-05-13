"""
ui/main_window.py
=================
Main application window for WSL Manager Pro.

Layout
------
  QMainWindow
  ├── QToolBar          – Install, Refresh, Shutdown, Settings
  ├── Central widget
  │   └── QSplitter (vertical)
  │       ├── QTabWidget (stretch 3)
  │       │   ├── Tab ``Dashboard``  (:class:`ui.tabs.dashboard_tab.DashboardTab`)
  │       │   ├── Tab ``Manage``     (:class:`ui.tabs.manage_tab.ManageTab`)
  │       │   └── Tab ``Settings`` (:class:`ui.tabs.settings_tab.SettingsTab`)
  │       └── Log Console          – QTextEdit read-only (stretch 1)
  └── QStatusBar        – privilege indicator + current stage

The Dashboard table refreshes automatically every N seconds via a QTimer
driving a RefreshWorker; it also refreshes after every install/action.

Phase A (ROADMAP) note — residual work for further slimming
-----------------------------------------------------------
Tab widgets live under ``ui/tabs/``; this module still owns workers, wizard,
and distro row logic. Future phases may move presenters / catalog builders out
until the file stays under the agreed line budget without losing cohesion.
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QFileDialog,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from core.constants import (
    AUTO_REFRESH_MIN_SECONDS,
    LOG_LINE_HARD_LIMIT,
    WSL_DEFAULT_USER_TIMEOUT,
    WSL_DIAGNOSTIC_TIMEOUT,
    WSL_SHELL_USER_TIMEOUT,
    WSL_USER_EXISTS_TIMEOUT,
)
from core.catalog_loader import load_catalog
from core.wsl_engine import DistroInfo, WslCommandError, WslEngine, WslNotFoundError
from utils.app_logging import get_logger, log_level_for_ui_line
from utils.config_manager import ConfigManager, ConfigValidationError, InstalledDistro
from utils.diagnostic_bundle import write_diagnostic_zip
from utils.i18n import LANGUAGE_LABELS, SUPPORTED_LANGUAGES, get_i18n, t
from utils.update_checker import DEFAULT_UPDATE_REPO_URL
from utils.worker_threads import (
    ExportWorker,
    ImportWorker,
    InstallWorker,
    PostInstallWorker,
    RefreshWorker,
    UpdateCheckWorker,
    UserStatusProbeWorker,
    WingetInstallWorker,
    WslCommandWorker,
    WslConfigWorker,
)

from ui.icons import get_icon
from ui.tabs.dashboard_tab import DashboardTab
from ui.tabs.manage_tab import ManageTab
from ui.tabs.settings_tab import SettingsTab
from ui.theme import (
    COLOR_ACCENT,
    COLOR_ERROR,
    COLOR_INFO,
    COLOR_MUTED,
    COLOR_STOPPED,
    COLOR_SUCCESS,
    COLOR_TEXT,
    COLOR_WARNING,
)


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    """Main application window for WSL Manager Pro.

    Orchestrates all tabs, background worker threads, toolbar actions,
    the log console, and the status bar.  This is the **central hub**
    that wires user actions to WSL operations and routes results back to
    the UI.

    Core responsibilities
    ---------------------
    * **Tab management** — Hosts :class:`DashboardTab`, :class:`ManageTab`,
      and :class:`SettingsTab` in a :class:`QTabWidget`.
    * **Worker coordination** — Spawns background :class:`QThread` workers
      (refresh, install, export, import, etc.) and connects their signals
      to UI update slots.
    * **Catalog loading** — Loads the local ``distros.json`` and merges it
      with the live ``wsl --list --online`` catalog.
    * **Distro operations** — Set default, terminate, shutdown, unregister,
      export, import, open shell, system update, repair, winget install.
    * **Install wizard** — Launches the 5-page :class:`InstallWizard` and
      routes the result to the appropriate install worker.
    * **Logging** — Collects timestamped log lines, supports filtering,
      copy-to-clipboard, and diagnostic export.
    * **Settings persistence** — Reads/writes :class:`ConfigManager` and
      applies ``.wslconfig`` resource limits.
    * **Language switching** — Reacts to ``language_changed`` signal and
      calls ``retranslate_ui()`` on all tabs.

    Instance state (key attributes)
    -------------------------------
    * ``_engine : Optional[WslEngine]`` — WSL engine instance (None if WSL
      unavailable).
    * ``_config_mgr : ConfigManager`` — Persistent application config.
    * ``_i18n : I18nManager`` — Runtime language manager.
    * ``_distros_cfg : dict`` — Merged distro catalog (static + online).
    * ``_active_workers : list`` — References to active QThread workers.
    * ``_external_install_procs : dict[str, Popen]`` — External PowerShell
      install processes tracked for cleanup.
    * ``_shell_procs : dict[str, Popen]`` — Open shell sessions tracked for
      termination on shutdown.
    * ``_active_operation : Optional[str]`` — Label of the currently running
      long operation (used for mutual exclusion).
    * ``_log_lines : list[tuple[str, str]]`` — All log lines as
      ``(plain_text, html_color)`` pairs.
    """

    def __init__(self, is_admin: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("WSL Manager Pro")
        self._apply_adaptive_window_size()

        self._is_admin    = is_admin
        self._config_mgr  = ConfigManager()
        self._i18n = get_i18n()
        self._catalog_source = "local"
        self._catalog_warnings: list[str] = []
        self._startup_messages: list[str] = []
        self._static_distros_cfg = self._load_distros_catalog()
        self._distros_cfg: dict = {}
        self._active_workers: list = []   # keep references so GC doesn't kill them
        self._worker_labels: dict[int, str] = {}
        self._external_install_procs: dict[str, subprocess.Popen] = {}
        self._shell_procs: dict[str, subprocess.Popen] = {}
        self._fallback_user_distros: set[str] = set()
        self._probed_default_users: dict[str, str] = {}
        self._last_distro_names: tuple[str, ...] = ()
        self._auto_user_status_verified: set[str] = set()
        self._active_operation: Optional[str] = None
        self._update_banner_url = ""
        self._log_lines: list[tuple[str, str]] = []
        self._cache_status_value = "N/A"
        self._cache_status_level = "none"
        self._catalog_status_source = "local"

        try:
            self._engine = WslEngine()
            self._wsl_ok = True
        except WslNotFoundError as exc:
            self._wsl_ok = False
            self._wsl_error = str(exc)
            self._engine = None  # type: ignore[assignment]

        self._distros_cfg = self._build_install_catalog()

        self._build_ui()
        self._build_toolbar()
        self._build_status_bar(is_admin)
        self._set_cache_status("N/A", "none")
        self._set_catalog_status(self._catalog_source)
        self._announce_startup_issues()
        self._i18n.language_changed.connect(self._on_language_changed)

        # Auto-refresh timer
        self._refresh_timer = QTimer(self)
        refresh_seconds = max(AUTO_REFRESH_MIN_SECONDS, int(self._config_mgr.config.auto_refresh_interval_sec))
        self._refresh_timer.setInterval(refresh_seconds * 1000)
        self._refresh_timer.timeout.connect(self._refresh_distros)
        if self._wsl_ok:
            self._refresh_distros()
            self._refresh_timer.start()
        else:
            self._log(f"[WARNING] {self._wsl_error}", color=COLOR_WARNING)
            self._dashboard_tab.show_empty_state(
                t("WSL was not detected.\n\nEnable WSL in Windows Features or install it from the Microsoft Store, then retry detection."),
                allow_retry=True,
            )

        self._apply_privilege_mode()
        self._maybe_check_for_updates()

        get_logger().info(
            "MainWindow ready (wsl_ok=%s, admin=%s)", self._wsl_ok, self._is_admin
        )

    # =========================================================================
    # UI construction
    # =========================================================================

    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setHandleWidth(4)

        self._tabs = QTabWidget()

        self._dashboard_tab = DashboardTab()
        self._dashboard_tab.refresh_requested.connect(self._refresh_distros)
        self._dashboard_tab.rescan_users_requested.connect(self._rescan_user_status)
        self._dashboard_tab.retry_detection_requested.connect(self._retry_wsl_detection)
        self._tabs.addTab(self._dashboard_tab, "  Dashboard  ")
        self._table = self._dashboard_tab.table
        self._distro_count_label = self._dashboard_tab.distro_count_label
        self._table.customContextMenuRequested.connect(self._show_distro_context_menu)

        self._manage_tab = ManageTab(self._config_mgr)
        self._tabs.addTab(self._manage_tab, "  Manage     ")
        self._import_tar_edit = self._manage_tab.import_tar_edit
        self._import_name_edit = self._manage_tab.import_name_edit
        self._import_dir_edit = self._manage_tab.import_dir_edit
        self._export_combo = self._manage_tab.export_combo
        self._export_path_edit = self._manage_tab.export_path_edit
        self._action_combo = self._manage_tab.action_combo
        self._btn_open_user_shell = self._manage_tab.btn_open_user_shell
        self._btn_open_root_shell = self._manage_tab.btn_open_root_shell
        self._btn_install_winget = self._manage_tab.btn_install_winget
        self._btn_repair_oracle = self._manage_tab.btn_repair_oracle
        self._btn_repair_suse = self._manage_tab.btn_repair_suse
        self._wire_manage_tab()

        self._settings_tab = SettingsTab(self._config_mgr)
        self._tabs.addTab(self._settings_tab, "  Settings   ")
        self._cfg_install_edit = self._settings_tab.cfg_install_edit
        self._cfg_dl_edit = self._settings_tab.cfg_dl_edit
        self._remote_catalog_url_edit = self._settings_tab.remote_catalog_url_edit
        self._run_as_admin_check = self._settings_tab.run_as_admin_check
        self._check_for_updates_check = self._settings_tab.check_for_updates_check
        self._update_repo_url_edit = self._settings_tab.update_repo_url_edit
        self._mem_spin = self._settings_tab.mem_spin
        self._swap_spin = self._settings_tab.swap_spin
        self._cpu_spin = self._settings_tab.cpu_spin
        self._localhost_forwarding_check = self._settings_tab.localhost_forwarding_check
        self._vm_idle_timeout_spin = self._settings_tab.vm_idle_timeout_spin
        self._wire_settings_tab()

        self._log_console = QTextEdit()
        self._log_console.setReadOnly(True)
        # Avoid QFontDatabase FixedFont on some Windows builds where it can
        # report an invalid point size and trigger Qt warnings.
        mono_font = QFont("Consolas")
        mono_font.setStyleHint(QFont.StyleHint.Monospace)
        mono_font.setFixedPitch(True)
        mono_font.setPointSize(10)
        self._log_console.setFont(mono_font)
        self._log_console.setMinimumHeight(96)
        self._log_console.setPlaceholderText("Output will appear here...")

        self._update_banner = QLabel("")
        self._update_banner.setVisible(False)
        self._update_banner.setOpenExternalLinks(False)
        self._update_banner.linkActivated.connect(self._open_update_link)
        self._update_banner.setStyleSheet(
            f"background-color: {COLOR_ACCENT}; color: #111; padding: 6px 10px; border-radius: 4px;"
        )

        self._log_filter_edit = QLineEdit()
        self._log_filter_edit.setPlaceholderText("Filter log lines...")
        self._log_filter_edit.textChanged.connect(self._apply_log_filter)
        self._btn_copy_log = QPushButton("Copy All")
        self._btn_copy_log.clicked.connect(self._copy_all_logs)
        self._btn_copy_selection = QPushButton("Copy Selection")
        self._btn_copy_selection.clicked.connect(self._copy_selected_logs)
        self._language_label = QLabel("Language")
        self._language_combo = QComboBox()
        for language in SUPPORTED_LANGUAGES:
            self._language_combo.addItem(LANGUAGE_LABELS[language], language)
        current_language_index = self._language_combo.findData(self._config_mgr.config.language)
        if current_language_index >= 0:
            self._language_combo.setCurrentIndex(current_language_index)
        self._language_combo.currentIndexChanged.connect(self._change_language_from_ui)
        self._log_label = QLabel("Log")
        log_header = QFrame()
        log_header.setObjectName("sectionPanel")
        log_toolbar = QHBoxLayout()
        log_toolbar.setContentsMargins(10, 7, 10, 7)
        log_toolbar.setSpacing(8)
        log_toolbar.addWidget(self._log_label)
        log_toolbar.addWidget(self._log_filter_edit, 1)
        log_toolbar.addWidget(self._btn_copy_selection)
        log_toolbar.addWidget(self._btn_copy_log)
        log_header.setLayout(log_toolbar)

        log_panel = QWidget()
        log_layout = QVBoxLayout(log_panel)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(8)
        log_layout.addWidget(log_header)
        log_layout.addWidget(self._log_console)

        splitter.addWidget(self._tabs)
        splitter.addWidget(log_panel)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([560, 180])

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(6)
        root_layout.addWidget(self._update_banner)
        root_layout.addWidget(splitter)
        self.setCentralWidget(root)
        self.retranslate_ui()

    def _wire_manage_tab(self) -> None:
        """Connect Manage tab buttons to MainWindow slots (keeps ManageTab Qt-only)."""
        m = self._manage_tab
        m.btn_browse_tar.clicked.connect(
            lambda: self._browse_file(
                m.import_tar_edit,
                "Select rootfs archive",
                "Archives (*.tar *.tar.gz *.tar.xz *.tgz)",
            )
        )
        m.btn_browse_import_dir.clicked.connect(
            lambda: self._browse_dir(m.import_dir_edit)
        )
        m.btn_browse_export.clicked.connect(
            lambda: self._browse_save(
                m.export_path_edit, "Save export as", "Archives (*.tar)"
            )
        )
        m.btn_import.clicked.connect(self._do_manual_import)
        m.btn_export.clicked.connect(self._do_export)
        m.action_combo.currentTextChanged.connect(
            lambda _t: self._update_repair_buttons_visibility()
        )
        m.btn_set_default.clicked.connect(self._do_set_default)
        m.btn_terminate.clicked.connect(self._do_terminate)
        m.btn_shutdown.clicked.connect(self._do_shutdown)
        m.btn_open_user_shell.clicked.connect(
            lambda: self._open_shell(self._action_combo.currentText(), root=False)
        )
        m.btn_open_root_shell.clicked.connect(
            lambda: self._open_shell(self._action_combo.currentText(), root=True)
        )
        m.btn_full_update.clicked.connect(self._do_full_system_update)
        m.btn_install_winget.clicked.connect(self._do_install_via_winget)
        m.btn_repair_oracle.clicked.connect(self._do_repair_oracle_existing)
        m.btn_repair_suse.clicked.connect(self._do_repair_suse_existing)
        m.btn_unregister.clicked.connect(self._do_unregister)
        m.btn_deep_clean.clicked.connect(self._do_deep_clean)

    def _wire_settings_tab(self) -> None:
        """Connect Settings tab browse and apply actions."""
        s = self._settings_tab
        s.btn_browse_install.clicked.connect(lambda: self._browse_dir(s.cfg_install_edit))
        s.btn_browse_download.clicked.connect(lambda: self._browse_dir(s.cfg_dl_edit))
        s.btn_apply_wslconfig.clicked.connect(self._apply_wslconfig)
        s.btn_save.clicked.connect(self._save_settings)
        s.btn_export_diagnostics.clicked.connect(self._export_diagnostic_bundle)

    # ------------------------------------------------------------------
    # Toolbar
    # ------------------------------------------------------------------

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main toolbar")
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        tb.setContentsMargins(8, 4, 8, 4)

        self._btn_install = QPushButton("Install")
        self._btn_install.setMinimumWidth(96)
        self._btn_install.setToolTip(t("Launch the Install Wizard"))
        self._btn_install.clicked.connect(self._open_install_wizard)

        self._btn_refresh = QPushButton("Refresh")
        self._btn_refresh.setMinimumWidth(96)
        self._btn_refresh.setToolTip(t("Refresh distribution list"))
        self._btn_refresh.clicked.connect(self._refresh_distros)

        self._btn_shutdown = QPushButton("Shutdown All")
        self._btn_shutdown.setMinimumWidth(116)
        self._btn_shutdown.setToolTip(t("wsl --shutdown"))
        self._btn_shutdown.clicked.connect(self._do_shutdown)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        for widget in (
            self._btn_install,
            self._btn_refresh,
            self._btn_shutdown,
            spacer,
            self._language_label,
            self._language_combo,
        ):
            tb.addWidget(widget)

        self.addToolBar(tb)

    def _apply_adaptive_window_size(self) -> None:
        """Choose a compact startup size that fits smaller displays."""
        app = QApplication.instance()
        screen = app.primaryScreen() if app is not None else None
        if screen is None:
            self.resize(980, 680)
            self.setMinimumSize(860, 620)
            return
        available = screen.availableGeometry()
        width = min(980, max(860, int(available.width() * 0.9)))
        height = min(680, max(620, int(available.height() * 0.86)))
        self.resize(width, height)
        self.setMinimumSize(820, 600)

    # ------------------------------------------------------------------
    # Status bar
    # ------------------------------------------------------------------

    def _build_status_bar(self, is_admin: bool) -> None:
        sb = self.statusBar()
        assert sb is not None

        if is_admin:
            priv_text  = "Administrator"
            priv_color = "#4CAF50"
        else:
            priv_text  = "Limited privileges - some features disabled"
            priv_color = "#FFA500"

        self._priv_label = QLabel(f"  {priv_text}  ")
        self._priv_label.setStyleSheet(
            f"color: white; background: {priv_color}; padding: 2px 8px; border-radius: 3px;"
        )

        self._stage_label = QLabel("  Ready  ")
        self._stage_label.setStyleSheet("color: #cccccc;")

        self._cache_label = QLabel("  Cache: N/A  ")
        self._cache_label.setStyleSheet("color: #d4d4d4;")

        self._catalog_label = QLabel("  Catalog: local  ")
        self._catalog_label.setStyleSheet("color: #64B5F6;")

        sb.addPermanentWidget(self._priv_label)
        sb.addPermanentWidget(self._catalog_label)
        sb.addPermanentWidget(self._cache_label)
        sb.addWidget(self._stage_label)
        self.retranslate_ui()

    # =========================================================================
    # Refresh / distro list
    # =========================================================================

    def _refresh_distros(self) -> None:
        if not self._wsl_ok:
            return
        engine = self._engine
        if engine is None:
            return
        worker = RefreshWorker(engine, parent=self)
        worker.distros_updated.connect(self._on_distros_updated)
        worker.error_occurred.connect(lambda e: self._log(e, color="#F44336"))
        self._track_worker(worker, "refresh distros")

    def _on_distros_updated(self, distros: list) -> None:
        self._table.setRowCount(0)
        if not distros:
            self._dashboard_tab.show_empty_state(
                "No WSL distributions were found yet.\n\nUse Install to add one, or retry detection if WSL was just enabled.",
                allow_retry=True,
            )
        else:
            self._dashboard_tab.show_empty_state("", allow_retry=False)
        for distro in distros:
            self._add_distro_row(distro)
        self._resize_dashboard_columns()
        self._distro_count_label.setText(t("({count} distros)", count=len(distros)))

        # Sync combo boxes in Manage tab
        names = [d.name for d in distros]
        for combo in (self._action_combo, self._export_combo):
            current = combo.currentText()
            combo.clear()
            combo.addItems(names)
            idx = combo.findText(current)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        self._update_repair_buttons_visibility()

        names_tuple = tuple(names)
        if names_tuple != self._last_distro_names:
            self._last_distro_names = names_tuple
            pending_names = [name for name in names if name.strip().lower() not in self._auto_user_status_verified]
            if pending_names:
                stopped_names = {
                    d.name.strip().lower()
                    for d in distros
                    if not d.is_running
                }
                self._refresh_user_status_async(pending_names, stop_after_probe=stopped_names)

    def _add_distro_row(self, distro: DistroInfo) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)

        # Column 0: status icon
        icon_item = QTableWidgetItem()
        if distro.state.lower() == "running":
            icon_item.setIcon(get_icon("running"))
        elif distro.state.lower() == "installing":
            icon_item.setIcon(get_icon("installing"))
        else:
            icon_item.setIcon(get_icon("stopped"))
        icon_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._table.setItem(row, 0, icon_item)

        # Column 1: name
        name_item = QTableWidgetItem(distro.name)
        if distro.is_default:
            name_item.setIcon(get_icon("default"))
            name_item.setForeground(QColor("#64B5F6"))
        self._table.setItem(row, 1, name_item)

        # Column 2: state
        alias = distro.name.strip().lower()
        fallback = alias in self._fallback_user_distros
        state_text = f"{distro.state} (fallback user)" if fallback and distro.is_running else distro.state
        state_item = QTableWidgetItem(state_text)
        state_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        color = "#FFB300" if fallback and distro.is_running else ("#4CAF50" if distro.is_running else "#9E9E9E")
        state_item.setForeground(QColor(color))
        if fallback and distro.is_running:
            state_item.setToolTip(t("Started with fallback user mode because configured user did not exist."))
        self._table.setItem(row, 2, state_item)

        # Column 3: WSL version
        ver_item = QTableWidgetItem(str(distro.version))
        ver_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._table.setItem(row, 3, ver_item)

        # Column 4: default
        default_item = QTableWidgetItem("yes" if distro.is_default else "")
        default_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        default_item.setForeground(QColor("#64B5F6"))
        self._table.setItem(row, 4, default_item)

        # Column 5: user configured (based on installation metadata + fallback flag)
        configured, tip = self._user_configured_state(distro.name)
        user_item = QTableWidgetItem("yes" if configured else "no")
        user_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        user_item.setForeground(QColor("#4CAF50" if configured else "#EF5350"))
        if tip:
            user_item.setToolTip(tip)
        self._table.setItem(row, 5, user_item)

        # Column 6: action button (Terminate / Wake note)
        if distro.is_running:
            btn = QPushButton(t("Stop"))
            btn.setObjectName("tableActionStop")
            btn.setFixedSize(58, 22)
            btn.clicked.connect(lambda _, n=distro.name: self._do_terminate(n))
        else:
            btn = QPushButton(t("Start"))
            btn.setObjectName("tableActionStart")
            btn.setFixedSize(58, 22)
            btn.setToolTip(t("Launch a command to wake the distro"))
            btn.clicked.connect(
                lambda _, n=distro.name: self._wake_distro(n)
            )
        btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        action_cell = QWidget()
        action_layout = QHBoxLayout(action_cell)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(0)
        action_layout.addStretch()
        action_layout.addWidget(btn)
        action_layout.addStretch()
        self._table.setCellWidget(row, 6, action_cell)
        self._table.setRowHeight(row, 30)

    def _resize_dashboard_columns(self) -> None:
        """Size dashboard columns from translated headers and first visible row."""
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)

        self._table.setColumnWidth(0, 34)
        self._table.setColumnWidth(2, self._dashboard_column_width(2, extra=30, min_width=122, max_width=230))
        self._table.setColumnWidth(3, self._dashboard_column_width(3, extra=20, min_width=62, max_width=90))
        self._table.setColumnWidth(4, self._dashboard_column_width(4, extra=20, min_width=76, max_width=112))
        self._table.setColumnWidth(5, self._dashboard_column_width(5, extra=28, min_width=130, max_width=210))
        self._table.setColumnWidth(6, 78)

    def _dashboard_column_width(
        self,
        column: int,
        extra: int = 24,
        min_width: int = 44,
        max_width: int = 320,
    ) -> int:
        """Measure one dashboard column using translated header and visible rows."""
        header_item = self._table.horizontalHeaderItem(column)
        header_text = header_item.text() if header_item is not None else ""
        header_metrics = QFontMetrics(self._table.horizontalHeader().font())
        content_metrics = QFontMetrics(self._table.font())

        header_width = header_metrics.horizontalAdvance(header_text)
        cell_width = 0
        row_scan_limit = min(self._table.rowCount(), 24)
        for row in range(row_scan_limit):
            item = self._table.item(row, column)
            if item is not None:
                cell_width = max(cell_width, content_metrics.horizontalAdvance(item.text()))
        width = max(min_width, header_width, cell_width) + extra
        return min(max_width, width)

    def _user_configured_state(self, distro_name: str) -> tuple[bool, str]:
        alias = distro_name.strip().lower()
        runtime_user = self._probed_default_users.get(distro_name, "")
        if runtime_user and runtime_user != "root":
            return True, f"Configured inside distro. Default user: {runtime_user}"
        installed = self._config_mgr.find_installed(distro_name)
        if not installed:
            return False, "No installation metadata for this distro in WSL Manager Pro."
        user = (installed.username or "").strip()
        if not user:
            return False, "This distro was installed without configured user (root mode)."
        if alias in self._fallback_user_distros:
            return False, f"Configured user '{user}' failed at runtime; fallback user mode was used."
        return True, f"Configured user: {user}"

    def _refresh_user_status_async(
        self,
        distro_names: list[str],
        stop_after_probe: Optional[set[str]] = None,
    ) -> None:
        if not self._wsl_ok or not distro_names:
            return
        engine = self._engine
        if engine is None:
            return
        worker = UserStatusProbeWorker(engine, distro_names, stop_after_probe=stop_after_probe, parent=self)
        worker.user_status_updated.connect(self._on_user_status_updated)
        worker.error_occurred.connect(lambda e: self._log(e, color="#F44336"))
        self._track_worker(worker, "probe user status")

    def _rescan_user_status(self) -> None:
        names: list[str] = []
        for row in range(self._table.rowCount()):
            name_item = self._table.item(row, 1)
            if name_item and name_item.text().strip():
                names.append(name_item.text().strip())
        if not names:
            self._log_t("[INFO] No distros available to re-scan user status.")
            return
        self._probed_default_users.clear()
        for name in names:
            self._auto_user_status_verified.discard(name.strip().lower())
        self._log_t("[INFO] Re-scanning distro user status...")
        self._refresh_user_status_async(names)

    def _on_user_status_updated(self, results: dict[str, str], stopped_distro_names: list[str]) -> None:
        self._probed_default_users.update(results)
        for distro_name in list(results.keys()) + list(stopped_distro_names):
            self._auto_user_status_verified.add(distro_name.strip().lower())
        for row in range(self._table.rowCount()):
            name_item = self._table.item(row, 1)
            if not name_item:
                continue
            configured, tip = self._user_configured_state(name_item.text())
            user_item = self._table.item(row, 5)
            if user_item is None:
                user_item = QTableWidgetItem()
                user_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._table.setItem(row, 5, user_item)
            user_item.setText(t("yes") if configured else t("no"))
            user_item.setForeground(QColor("#4CAF50" if configured else "#EF5350"))
            user_item.setToolTip(tip)
        if stopped_distro_names:
            self._log_t("[INFO] User-status probe finished; auto-stopped verified distros that were previously off.")
            self._refresh_distros()

    # =========================================================================
    # Context menu
    # =========================================================================

    def _show_distro_context_menu(self, pos) -> None:
        item = self._table.itemAt(pos)
        if item is None:
            return
        row   = item.row()
        name_item = self._table.item(row, 1)
        if not name_item:
            return
        name = name_item.text()

        menu = QMenu(self)
        menu.addAction(t("Set as Default"), lambda: self._do_set_default(name))
        menu.addAction(t("Terminate"), lambda: self._do_terminate(name))
        menu.addAction(t("Export..."), lambda: self._export_distro_dialog(name))
        menu.addSeparator()
        menu.addAction(t("Open Shell (root)"), lambda: self._open_shell(name, root=True))
        menu.addAction(t("Open Shell (user)"), lambda: self._open_shell(name, root=False))
        menu.addAction(t("Full System Update"), lambda: self._do_full_system_update(name))
        if "oraclelinux" in name.lower():
            menu.addAction(t("Repair Oracle Existing"), lambda: self._do_repair_oracle_existing(name))
        lowered_name = name.lower()
        if lowered_name == "suse-linux-enterprise-15-sp6" or lowered_name == "suse linux enterprise 15 sp6":
            menu.addAction(t("Repair SLE 15 SP6 Image"), lambda: self._do_repair_suse_existing(name))
        menu.addSeparator()
        unregister_action = menu.addAction(t("Unregister (Delete...)"))
        unregister_action.triggered.connect(lambda: self._do_unregister(name))
        menu.exec(self._table.mapToGlobal(pos))

    def _apply_privilege_mode(self) -> None:
        limited = not self._is_admin
        widgets = [
            self._manage_tab.btn_import,
            self._manage_tab.btn_shutdown,
            self._manage_tab.btn_unregister,
            self._manage_tab.btn_deep_clean,
            self._manage_tab.btn_repair_oracle,
            self._manage_tab.btn_repair_suse,
            self._manage_tab.btn_install_winget,
        ]
        tip = t("Disabled in limited mode. Restart with administrator privileges to enable.")
        for widget in widgets:
            widget.setEnabled(not limited)
            if limited:
                widget.setToolTip(tip)

    def _retry_wsl_detection(self) -> None:
        try:
            self._engine = WslEngine()
            self._wsl_ok = True
            self._wsl_error = ""
        except WslNotFoundError as exc:
            self._wsl_ok = False
            self._wsl_error = str(exc)
            self._dashboard_tab.show_empty_state(
                t("WSL is still unavailable.\n\nCheck Windows Features or Store installation, then try again."),
                allow_retry=True,
            )
            self._log(f"[WARNING] {self._wsl_error}", color=COLOR_WARNING)
            return
        self._distros_cfg = self._build_install_catalog()
        self._refresh_timer.start()
        self._refresh_distros()

    def _begin_operation(self, label: str) -> bool:
        if self._active_operation:
            self._log_t(
                "[INFO] Another operation is already running: {operation}",
                color=COLOR_INFO,
                operation=self._active_operation,
            )
            self._set_stage(t("Operation in progress: {operation}", operation=self._active_operation))
            return False
        self._active_operation = label
        self._set_stage(t("Operation in progress: {operation}", operation=label))
        return True

    def _end_operation(self, label: str = "") -> None:
        if not label or self._active_operation == label:
            self._active_operation = None
            self._set_stage(t("Ready"))

    def _worker_label(self, worker) -> str:
        return self._worker_labels.get(id(worker), "unspecified")

    def _track_worker(self, worker, label: str) -> None:
        self._worker_labels[id(worker)] = label
        worker.started.connect(
            lambda: self._log(
                t(
                    "[DEBUG] Worker started: {name} ({label})",
                    name=worker.__class__.__name__,
                    label=label,
                ),
                color=COLOR_MUTED,
            )
        )
        worker.finished.connect(lambda: self._untrack_worker(worker))
        self._active_workers.append(worker)
        worker.start()

    def _untrack_worker(self, worker) -> None:
        label = self._worker_labels.pop(id(worker), "unspecified")
        if worker in self._active_workers:
            self._active_workers.remove(worker)
        self._log(
            t(
                "[DEBUG] Worker finished: {name} ({label})",
                name=worker.__class__.__name__,
                label=label,
            ),
            color=COLOR_MUTED,
        )

    def _maybe_check_for_updates(self) -> None:
        if not self._config_mgr.config.check_for_updates:
            return
        repo_url = self._config_mgr.config.update_repo_url.strip() or DEFAULT_UPDATE_REPO_URL
        current_version = QApplication.instance().applicationVersion()
        worker = UpdateCheckWorker(repo_url, current_version, parent=self)
        worker.update_result.connect(self._on_update_check_result)
        worker.error_occurred.connect(
            lambda error: self._log_t(
                "[WARN] Update check failed: {error}",
                color=COLOR_WARNING,
                error=error,
            )
        )
        self._track_worker(worker, "update check")

    def _on_update_check_result(self, result) -> None:
        if not result.update_available:
            self._log_t(
                "[INFO] WSL Manager Pro is up to date ({version}).",
                color=COLOR_INFO,
                version=result.latest_version,
            )
            return
        self._update_banner_url = result.release_url
        self._update_banner.setText(
            t(
                'WSL Manager Pro {version} is available. <a href="{url}">Open release download</a>',
                version=result.latest_version,
                url=result.release_url,
            )
        )
        self._update_banner.setVisible(True)
        QMessageBox.information(
            self,
            t("Update available"),
            t(
                "WSL Manager Pro {version} is available.\n\nDownload page:\n{url}",
                version=result.latest_version,
                url=result.release_url,
            ),
            QMessageBox.StandardButton.Ok,
        )

    def _open_update_link(self, url: str) -> None:
        webbrowser.open(url)

    def _log_t(self, key: str, color: str = "", **kwargs) -> None:
        self._log(t(key, **kwargs), color=color)

    def _terminate_tracked_process(self, proc: Optional[subprocess.Popen]) -> None:
        if proc is None or proc.poll() is not None:
            return
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

    def _change_language_from_ui(self) -> None:
        language = str(self._language_combo.currentData() or "en")
        if language == self._config_mgr.config.language:
            return
        self._config_mgr.config.language = language
        self._config_mgr.save()
        self._i18n.set_language(language)

    def _on_language_changed(self, language: str) -> None:
        index = self._language_combo.findData(language)
        if index >= 0 and index != self._language_combo.currentIndex():
            self._language_combo.setCurrentIndex(index)
        self.retranslate_ui()
        self._resize_dashboard_columns()

    def retranslate_ui(self) -> None:
        self.setWindowTitle(t("WSL Manager Pro"))
        if not hasattr(self, "_btn_install"):
            return
        self._log_label.setText(t("Log"))
        self._language_label.setText(t("Language"))
        self._btn_install.setText(t("Install"))
        self._btn_install.setToolTip(t("Launch the Install Wizard"))
        self._btn_refresh.setText(t("Refresh"))
        self._btn_refresh.setToolTip(t("Refresh distribution list"))
        self._btn_shutdown.setText(t("Shutdown All"))
        self._btn_shutdown.setToolTip(t("wsl --shutdown"))
        self._log_filter_edit.setPlaceholderText(t("Filter log lines..."))
        self._btn_copy_log.setText(t("Copy All"))
        self._btn_copy_selection.setText(t("Copy Selection"))
        priv_text = t("Administrator") if self._is_admin else t("Limited privileges - some features disabled")
        self._priv_label.setText(f"  {priv_text}  ")
        self._set_cache_status(self._cache_status_value, self._cache_status_level)
        self._set_catalog_status(self._catalog_status_source)
        if self._active_operation:
            self._set_stage(t("Operation in progress: {operation}", operation=self._active_operation))
        else:
            self._set_stage(t("Ready"))
        self._tabs.setTabText(0, f"  {t('Dashboard')}  ")
        self._tabs.setTabText(1, f"  {t('Manage')}     ")
        self._tabs.setTabText(2, f"  {t('Settings')}   ")

    # =========================================================================
    # Actions
    # =========================================================================

    def _do_set_default(self, name: str = "") -> None:
        if not name:
            name = self._action_combo.currentText()
        if not name:
            return
        try:
            self._engine.set_default(name)
            self._log_t("'{name}' is now the default distribution.", name=name)
            self._refresh_distros()
        except Exception as exc:  # noqa: BLE001
            self._log(f"[ERROR] {exc}", color="#F44336")

    def _do_terminate(self, name: str = "") -> None:
        if not name:
            name = self._action_combo.currentText()
        if not name:
            return
        alias = name.strip().lower()
        shell_proc = self._shell_procs.get(alias)
        if shell_proc is not None:
            if shell_proc.poll() is None:
                try:
                    self._terminate_tracked_process(shell_proc)
                    self._log_t("Closed shell console for '{name}' (PID {pid}).", name=name, pid=shell_proc.pid)
                except Exception as exc:  # noqa: BLE001
                    self._log_t("[ERROR] Could not close shell console for '{name}': {exc}", color="#F44336", name=name, exc=exc)
            self._shell_procs.pop(alias, None)
        proc = self._external_install_procs.get(alias)
        if proc is not None:
            if proc.poll() is None:
                try:
                    self._terminate_tracked_process(proc)
                    self._log_t("Stopped external installer for '{name}' (PID {pid}).", name=name, pid=proc.pid)
                except Exception as exc:  # noqa: BLE001
                    self._log_t("[ERROR] Could not stop external installer for '{name}': {exc}", color="#F44336", name=name, exc=exc)
            for key, p in list(self._external_install_procs.items()):
                if p is proc:
                    self._external_install_procs.pop(key, None)
        try:
            self._engine.terminate(name)
            self._log_t("'{name}' terminated.", name=name)
            self._refresh_distros()
        except Exception as exc:  # noqa: BLE001
            self._log(f"[ERROR] {exc}", color="#F44336")

    def _do_shutdown(self) -> None:
        reply = QMessageBox.question(
            self, t("Shutdown All"),
            t("This will shut down all running WSL distributions and the WSL 2 VM.\nContinue?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            for alias, proc in list(self._shell_procs.items()):
                self._terminate_tracked_process(proc)
            self._shell_procs.clear()
            for alias, proc in list(self._external_install_procs.items()):
                self._terminate_tracked_process(proc)
            self._external_install_procs.clear()
            self._engine.shutdown()
            self._log_t("All WSL distributions shut down.")
            self._refresh_distros()
        except Exception as exc:  # noqa: BLE001
            self._log(f"[ERROR] {exc}", color="#F44336")

    def _do_unregister(self, name: str = "") -> None:
        if not name:
            name = self._action_combo.currentText()
        if not name:
            return
        reply = QMessageBox.warning(
            self, t("Unregister Distribution"),
            t("This will permanently delete the distribution '{name}' and all its data.\n\nContinue?", name=name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._engine.unregister_distro(name)
            self._config_mgr.unregister_distro(name)
            self._log_t("'{name}' unregistered.", name=name)
            self._refresh_distros()
        except Exception as exc:  # noqa: BLE001
            self._log(f"[ERROR] {exc}", color="#F44336")

    def _do_deep_clean(self) -> None:
        cache_dir = Path(self._config_mgr.config.download_dir)
        guard_reason = self._unsafe_cleanup_dir_reason(cache_dir)
        if guard_reason:
            QMessageBox.warning(
                self,
                t("Deep Clean"),
                t("Deep clean refused for safety:\n{reason}", reason=guard_reason),
            )
            self._log_t(
                "[WARN] Deep clean refused for safety: {reason}",
                color="#FFC107",
                reason=guard_reason,
            )
            return

        reply = QMessageBox.warning(
            self,
            t("Deep Clean"),
            t(
                "This will do a deep cleanup to free disk space.\n\n"
                "Cache directory:\n{cache_dir}\n\n"
                "- Shutdown all WSL distributions\\n"
                "- Remove all files inside the configured download/cache directory\\n"
                "- Remove generated install PowerShell temp scripts\\n"
                "- Remove stale installed-distro records from this app\\n"
                "- Remove empty orphan folders inside the configured install directory\\n\\n"
                "Continue?",
                cache_dir=str(cache_dir),
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._log_t("[CLEANUP] Starting deep cleanup ...")

        reclaimed_total = 0
        files_removed = 0
        dirs_removed = 0

        # 1) Ensure WSL is not running before touching cache/install artifacts.
        try:
            for _alias, proc in list(self._shell_procs.items()):
                self._terminate_tracked_process(proc)
            self._shell_procs.clear()

            for _alias, proc in list(self._external_install_procs.items()):
                self._terminate_tracked_process(proc)
            self._external_install_procs.clear()

            self._engine.shutdown()
            self._log_t("[CLEANUP] WSL shutdown completed.")
        except Exception as exc:  # noqa: BLE001
            self._log_t(
                "[WARN] Could not fully shutdown WSL before cleanup: {error}",
                color="#FFC107",
                error=exc,
            )

        # 2) Build live distro name set for stale-registry pruning.
        live_names_lower: set[str] = set()
        try:
            live_names_lower = {d.name.strip().lower() for d in self._engine.list_distros()}
        except Exception as exc:  # noqa: BLE001
            self._log_t(
                "[WARN] Could not query live distros: {error}",
                color="#FFC107",
                error=exc,
            )

        # 3) Remove stale app records.
        stale_names = [
            d.name
            for d in self._config_mgr.config.installed_distros
            if d.name.strip().lower() not in live_names_lower
        ]
        for stale_name in stale_names:
            self._config_mgr.unregister_distro(stale_name)
            self._fallback_user_distros.discard(stale_name.strip().lower())
            self._log_t("[CLEANUP] Removed stale app registry entry: {name}", name=stale_name)

        # 4) Clear saved download state metadata.
        if self._config_mgr.config.download_states:
            self._config_mgr.config.download_states.clear()
            self._config_mgr.save()
            self._log_t("[CLEANUP] Cleared cached download resume states.")

        # 5) Purge configured download/cache directory contents.
        if cache_dir.exists() and cache_dir.is_dir():
            for child in list(cache_dir.iterdir()):
                removed_bytes, removed_files, removed_dirs = self._remove_path_with_stats(child)
                reclaimed_total += removed_bytes
                files_removed += removed_files
                dirs_removed += removed_dirs
            self._log_t("[CLEANUP] Purged cache directory: {path}", path=cache_dir)
        else:
            self._log_t("[CLEANUP] Cache directory not found, skipped: {path}", path=cache_dir)

        # 6) Remove generated temporary install scripts.
        temp_dir = Path(tempfile.gettempdir())
        for script in temp_dir.glob("wsl_manager_install_*.ps1"):
            removed_bytes, removed_files, removed_dirs = self._remove_path_with_stats(script)
            reclaimed_total += removed_bytes
            files_removed += removed_files
            dirs_removed += removed_dirs

        # 7) Remove empty orphan folders under install directory.
        install_dir = Path(self._config_mgr.config.install_dir)
        if install_dir.exists() and install_dir.is_dir():
            for child in list(install_dir.iterdir()):
                if not child.is_dir():
                    continue
                if child.name.strip().lower() in live_names_lower:
                    continue
                if self._dir_is_empty(child):
                    removed_bytes, removed_files, removed_dirs = self._remove_path_with_stats(child)
                    reclaimed_total += removed_bytes
                    files_removed += removed_files
                    dirs_removed += removed_dirs

        reclaimed_mb = reclaimed_total / (1024 * 1024)
        self._log_t(
            "[CLEANUP] Done. Removed {files} files, {dirs} folders, reclaimed ~{mb:.2f} MB.",
            color="#4CAF50",
            files=files_removed,
            dirs=dirs_removed,
            mb=reclaimed_mb,
        )
        self._set_stage(t("Deep cleanup completed"))
        self._refresh_distros()
        QMessageBox.information(
            self,
            t("Deep Clean Complete"),
            t(
                "Cleanup finished.\n\nRemoved files: {files}\nRemoved folders: {dirs}\nApprox. reclaimed: {mb:.2f} MB",
                files=files_removed,
                dirs=dirs_removed,
                mb=reclaimed_mb,
            ),
        )

    def _remove_path_with_stats(self, path: Path) -> tuple[int, int, int]:
        """Best-effort remove a file/folder and return (bytes, files, dirs)."""
        try:
            if path.is_file() or path.is_symlink():
                size = path.stat().st_size if path.exists() else 0
                path.unlink(missing_ok=True)
                return size, 1, 0

            if not path.is_dir():
                return 0, 0, 0

            total_bytes = 0
            file_count = 0
            dir_count = 1
            for root, dirs, files in os.walk(path):
                dir_count += len(dirs)
                file_count += len(files)
                for filename in files:
                    fp = Path(root) / filename
                    try:
                        total_bytes += fp.stat().st_size
                    except OSError:
                        pass
            shutil.rmtree(path, ignore_errors=True)
            return total_bytes, file_count, dir_count
        except Exception as exc:  # noqa: BLE001
            self._log_t("[WARN] Could not remove '{path}': {error}", color="#FFC107", path=path, error=exc)
            return 0, 0, 0

    @staticmethod
    def _dir_is_empty(path: Path) -> bool:
        try:
            next(path.iterdir())
            return False
        except StopIteration:
            return True
        except OSError:
            return False

    @staticmethod
    def _unsafe_cleanup_dir_reason(path: Path) -> str:
        raw = str(path).strip()
        if not raw:
            return "Cleanup directory is empty."
        try:
            resolved = path.expanduser().resolve()
        except OSError as exc:
            return f"Could not resolve cleanup directory '{path}': {exc}"

        if not resolved.is_absolute():
            return f"Cleanup directory is not absolute: {path}"
        if resolved.parent == resolved:
            return f"Cleanup directory points to a filesystem root: {resolved}"

        project_root = Path(__file__).resolve().parent.parent.resolve()
        protected = {
            project_root,
            Path.home().resolve(),
            (Path.home() / "Desktop").resolve(),
            (Path.home() / "Documents").resolve(),
            (Path.home() / "Downloads").resolve(),
            Path(tempfile.gettempdir()).resolve(),
        }
        for env_name in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "USERPROFILE"):
            env_value = os.environ.get(env_name)
            if env_value:
                protected.add(Path(env_value).resolve())

        for protected_path in protected:
            if resolved == protected_path:
                return f"Cleanup directory is a protected location: {resolved}"

        try:
            project_root.relative_to(resolved)
            return f"Cleanup directory contains the project workspace: {resolved}"
        except ValueError:
            return ""

    def _do_export(self) -> None:
        if not self._begin_operation("export"):
            return
        name = self._export_combo.currentText()
        path = self._export_path_edit.text().strip()
        if not name or not path:
            self._end_operation("export")
            QMessageBox.warning(self, t("Missing data"), t("Please select a distribution and an export path."))
            return
        self._log_t("Exporting '{name}' -> {path} ...", name=name, path=path)
        worker = ExportWorker(self._engine, name, path, parent=self)
        worker.finished_ok.connect(lambda: self._log_t("Export complete: {path}", path=path))
        worker.error_occurred.connect(lambda e: self._log(e, color=COLOR_ERROR))
        worker.finished.connect(lambda: self._end_operation("export"))
        self._track_worker(worker, "export distro")

    def _do_manual_import(self) -> None:
        if not self._begin_operation("manual import"):
            return
        tar   = self._import_tar_edit.text().strip()
        name  = self._import_name_edit.text().strip()
        idir  = self._import_dir_edit.text().strip()
        if not tar or not name or not idir:
            self._end_operation("manual import")
            QMessageBox.warning(
                self,
                t("Missing data"),
                t("Please fill in tar path, name, and install directory."),
            )
            return
        self._log_t("Importing '{name}' from {path} ...", name=name, path=tar)
        worker = ImportWorker(self._engine, name, idir, tar, parent=self)
        worker.finished_ok.connect(lambda: (self._log_t("Import of '{name}' done.", name=name), self._refresh_distros()))
        worker.error_occurred.connect(lambda e: self._log(e, color=COLOR_ERROR))
        worker.finished.connect(lambda: self._end_operation("manual import"))
        self._track_worker(worker, "manual import")

    def _wake_distro(self, name: str) -> None:
        self._open_shell(name, root=False)
        self._refresh_distros()

    def _open_shell(self, name: str, root: bool) -> None:
        """Open WSL shell in Windows Terminal; falls back to PowerShell if wt.exe is absent."""
        name = name.strip()
        if not name:
            return
        alias = name.strip().lower()
        shell_user = "root" if root else self._cached_shell_user(name)
        if not root and not shell_user:
            shell_user = "root"
            self._log_t(
                "[INFO] No configured user was found for '{name}'. Opening the shell as root.",
                color=COLOR_INFO,
                name=name,
            )
        if not root:
            self._fallback_user_distros.discard(alias)
        self._terminate_tracked_process(self._shell_procs.pop(alias, None))
        user_arg = ["-u", shell_user] if shell_user else []
        workdir = "/root" if shell_user == "root" else f"/home/{shell_user}"
        cd_arg = ["--cd", workdir]
        wt = shutil.which("wt.exe")
        if wt:
            proc = subprocess.Popen(
                [wt, "wsl.exe", "-d", name, *user_arg, *cd_arg],
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
        else:
            ps = shutil.which("pwsh.exe") or shutil.which("powershell.exe") or "powershell.exe"
            wsl_cmd = subprocess.list2cmdline(["wsl.exe", "-d", name] + user_arg + cd_arg)
            proc = subprocess.Popen(
                [ps, "-NoExit", "-NoProfile", "-Command", wsl_cmd],
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
        self._shell_procs[alias] = proc
        self._log_t(
            "Opened shell for '{name}' as {user} in {path}.",
            color=COLOR_INFO,
            name=name,
            user=shell_user or "default",
            path=workdir,
        )

    def _do_install_via_winget(self) -> None:
        if not self._begin_operation("winget install"):
            return
        if not self._is_admin:
            self._end_operation("winget install")
            QMessageBox.warning(
                self,
                t("Limited mode"),
                t("winget installs require administrator privileges."),
            )
            return
        distro_name = self._action_combo.currentText().strip()
        if not distro_name:
            self._end_operation("winget install")
            QMessageBox.warning(self, t("winget install"), t("Select a target distribution first."))
            return
        distro_cfg = {}
        normalized = re.sub(r"[^a-z0-9]", "", distro_name.lower())
        for cfg in self._distros_cfg.values():
            display = re.sub(r"[^a-z0-9]", "", str(cfg.get("display_name", "")).lower())
            online_name = re.sub(r"[^a-z0-9]", "", str(cfg.get("online_name", "")).lower())
            if normalized and normalized in (display, online_name):
                distro_cfg = cfg
                break
        package_id = str(distro_cfg.get("winget_id") or "").strip()
        if not package_id:
            self._end_operation("winget install")
            QMessageBox.warning(
                self,
                t("winget install"),
                t("The selected distro does not define a winget_id in the catalog."),
            )
            return
        worker = WingetInstallWorker(self._engine, package_id, parent=self)
        worker.log_message.connect(self._log)
        worker.error_occurred.connect(lambda e: self._log(e, color=COLOR_ERROR))
        worker.finished.connect(lambda: self._end_operation("winget install"))
        self._track_worker(worker, "winget install")

    def _cached_shell_user(self, name: str) -> str:
        installed = self._config_mgr.find_installed(name)
        if installed and installed.username:
            return installed.username.strip()
        probed = self._probed_default_users.get(name, "").strip()
        if probed and probed != "root":
            return probed
        return ""

    def _export_distro_dialog(self, name: str) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, t("Export '{name}'", name=name), f"{name}.tar", t("Archives (*.tar)")
        )
        if path:
            self._export_path_edit.setText(path)
            self._export_combo.setCurrentText(name)
            self._tabs.setCurrentIndex(1)   # switch to Manage tab
            self._do_export()

    def _do_full_system_update(self, name: str = "") -> None:
        if not self._begin_operation("full system update"):
            return
        if not name:
            name = self._action_combo.currentText()
        if not name:
            self._end_operation("full system update")
            return

        reply = QMessageBox.question(
            self,
            t("Full System Update"),
            t(
                "Run a full package update for '{name}'?\n\nThis can take several minutes and may upgrade many packages.",
                name=name,
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            self._end_operation("full system update")
            return

        self._log_t("Starting full system update for '{name}' ...", name=name)
        cmd = (
            "if command -v apt-get >/dev/null 2>&1; then "
            "DEBIAN_FRONTEND=noninteractive apt-get update && "
            "DEBIAN_FRONTEND=noninteractive apt-get upgrade -y; "
            "elif command -v dnf >/dev/null 2>&1; then "
            "dnf upgrade --refresh -y; "
            "elif command -v pacman >/dev/null 2>&1; then "
            "pacman -Syu --noconfirm; "
            "elif command -v apk >/dev/null 2>&1; then "
            "apk update && apk upgrade; "
            "elif command -v zypper >/dev/null 2>&1; then "
            "zypper --non-interactive refresh && zypper --non-interactive update; "
            "else echo 'No supported package manager found.' >&2; exit 1; fi"
        )
        worker = WslCommandWorker(
            engine=self._engine,
            distro=name,
            command=cmd,
            as_root=True,
            parent=self,
        )
        worker.log_message.connect(self._log)
        worker.error_occurred.connect(lambda e: self._log(e, color="#F44336"))
        worker.finished_ok.connect(lambda: self._log_t("Full system update finished for '{name}'.", name=name))
        worker.finished.connect(lambda: self._end_operation("full system update"))
        self._track_worker(worker, "full system update")

    def _do_repair_oracle_existing(self, name: str = "") -> None:
        if not name:
            name = self._action_combo.currentText()
        name = name.strip()
        if not name:
            return
        if "oraclelinux" not in name.lower():
            QMessageBox.warning(
                self,
                t("Repair Oracle Existing"),
                t("This action is intended only for Oracle Linux distros."),
            )
            return

        reply = QMessageBox.question(
            self,
            t("Repair Oracle Existing"),
            t(
                "This will repair '{name}' by exporting it, unregistering it, and importing it into your configured install directory.\n\nContinue?",
                name=name,
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        install_dir = str(Path(self._config_mgr.config.install_dir) / name)
        export_file = str(Path(self._config_mgr.config.download_dir) / f"{name}.tar")
        existing = self._config_mgr.find_installed(name)
        remembered_user = (existing.username if existing else "").strip()
        if not remembered_user:
            remembered_user = self._default_shell_user(name).strip()

        self._log_t("[REPAIR] Exporting '{name}' to {path}", name=name, path=export_file)
        self._log_t("[REPAIR] Re-import target dir: {path}", path=install_dir)

        from PySide6.QtCore import QThread

        class _RepairOracleWorker(QThread):
            def __init__(self, engine, distro_name, idir, efile, parent=None):
                super().__init__(parent)
                self._e = engine
                self._name = distro_name
                self._idir = idir
                self._efile = efile
                self.error: str = ""

            def run(self):
                try:
                    Path(self._efile).parent.mkdir(parents=True, exist_ok=True)
                    try:
                        self._e.terminate(self._name)
                    except Exception:
                        pass
                    try:
                        self._e.shutdown()
                    except Exception:
                        pass
                    self._e.export_distro(self._name, self._efile)
                    self._e.unregister_distro(self._name)
                    if Path(self._idir).exists():
                        shutil.rmtree(self._idir, ignore_errors=True)
                    self._e.import_distro(self._name, self._idir, self._efile, version=2)
                    if remembered_user:
                        safe_user = shlex.quote(remembered_user)
                        wsl_conf = f"[user]\ndefault={remembered_user}\n"
                        escaped_conf = wsl_conf.replace("'", "'\\''")
                        self._e._run([
                            "-d", self._name,
                            "-u", "root",
                            "--", "bash", "-lc",
                            f"id -u {safe_user} >/dev/null 2>&1 && printf '%s' '{escaped_conf}' > /etc/wsl.conf",
                        ], check=False, timeout=30)
                        self._e.shutdown()
                    self._e.set_default(self._name)
                except Exception as exc:  # noqa: BLE001
                    self.error = str(exc)

        worker = _RepairOracleWorker(self._engine, name, install_dir, export_file, parent=self)

        def _on_done() -> None:
            if worker.error:
                self._log_t("[ERROR] Oracle repair failed: {error}", color="#F44336", error=worker.error)
            else:
                self._config_mgr.register_installed_distro(
                    InstalledDistro(
                        name=name,
                        distro_id="online:" + name.lower(),
                        install_dir=install_dir,
                        installed_at=datetime.now().isoformat(),
                        username=remembered_user,
                    )
                )
                if remembered_user:
                    self._probed_default_users[name] = remembered_user
                    self._fallback_user_distros.discard(name.strip().lower())
                self._log_t("[OK] Oracle repair completed for '{name}'.", name=name)
                self._refresh_distros()

        worker.finished.connect(_on_done)
        self._track_worker(worker, "repair oracle existing")

    def _do_repair_suse_existing(self, name: str = "") -> None:
        if not name:
            name = self._action_combo.currentText()
        name = name.strip()
        if not name:
            return
        lowered = name.lower()
        if lowered not in ("suse-linux-enterprise-15-sp6", "suse linux enterprise 15 sp6"):
            QMessageBox.warning(
                self,
                t("Repair SLE 15 SP6 Image"),
                t("This action is intended only for SUSE-Linux-Enterprise-15-SP6."),
            )
            return

        reply = QMessageBox.question(
            self,
            t("Repair SLE 15 SP6 Image"),
            t(
                "This will repair '{name}' by exporting it, unregistering it, and importing it into your configured install directory.\n\nContinue?",
                name=name,
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        install_dir = str(Path(self._config_mgr.config.install_dir) / name)
        export_file = str(Path(self._config_mgr.config.download_dir) / f"{name}.tar")
        existing = self._config_mgr.find_installed(name)
        remembered_user = (existing.username if existing else "").strip()
        if not remembered_user:
            remembered_user = self._default_shell_user(name).strip()

        self._log_t("[REPAIR] Exporting '{name}' to {path}", name=name, path=export_file)
        self._log_t("[REPAIR] Re-import target dir: {path}", path=install_dir)

        from PySide6.QtCore import QThread

        class _RepairSuseWorker(QThread):
            def __init__(self, engine, distro_name, idir, efile, parent=None):
                super().__init__(parent)
                self._e = engine
                self._name = distro_name
                self._idir = idir
                self._efile = efile
                self.error: str = ""

            def run(self):
                try:
                    Path(self._efile).parent.mkdir(parents=True, exist_ok=True)
                    try:
                        self._e.terminate(self._name)
                    except Exception:
                        pass
                    try:
                        self._e.shutdown()
                    except Exception:
                        pass
                    self._e.export_distro(self._name, self._efile)
                    self._e.unregister_distro(self._name)
                    if Path(self._idir).exists():
                        shutil.rmtree(self._idir, ignore_errors=True)
                    self._e.import_distro(self._name, self._idir, self._efile, version=2)
                    if remembered_user:
                        safe_user = shlex.quote(remembered_user)
                        wsl_conf = f"[user]\ndefault={remembered_user}\n"
                        escaped_conf = wsl_conf.replace("'", "'\\''")
                        self._e._run([
                            "-d", self._name,
                            "-u", "root",
                            "--", "bash", "-lc",
                            f"id -u {safe_user} >/dev/null 2>&1 && printf '%s' '{escaped_conf}' > /etc/wsl.conf",
                        ], check=False, timeout=30)
                        self._e.shutdown()
                    self._e.set_default(self._name)
                except Exception as exc:  # noqa: BLE001
                    self.error = str(exc)

        worker = _RepairSuseWorker(self._engine, name, install_dir, export_file, parent=self)

        def _on_done() -> None:
            if worker.error:
                self._log_t("[ERROR] SLE 15 SP6 repair failed: {error}", color="#F44336", error=worker.error)
            else:
                self._config_mgr.register_installed_distro(
                    InstalledDistro(
                        name=name,
                        distro_id="online:" + name.lower(),
                        install_dir=install_dir,
                        installed_at=datetime.now().isoformat(),
                        username=remembered_user,
                    )
                )
                if remembered_user:
                    self._probed_default_users[name] = remembered_user
                    self._fallback_user_distros.discard(name.strip().lower())
                self._log_t("[OK] SLE 15 SP6 repair completed for '{name}'.", name=name)
                self._refresh_distros()

        worker.finished.connect(_on_done)
        self._track_worker(worker, "repair suse existing")

    def _update_repair_buttons_visibility(self) -> None:
        selected = (self._action_combo.currentText() or "").strip().lower()
        is_oracle = "oraclelinux" in selected
        is_suse = selected in ("suse-linux-enterprise-15-sp6", "suse linux enterprise 15 sp6")
        normalized = re.sub(r"[^a-z0-9]", "", selected)
        has_winget = False
        for cfg in self._distros_cfg.values():
            display = re.sub(r"[^a-z0-9]", "", str(cfg.get("display_name", "")).lower())
            online_name = re.sub(r"[^a-z0-9]", "", str(cfg.get("online_name", "")).lower())
            if normalized and normalized in (display, online_name) and cfg.get("winget_id"):
                has_winget = True
                break
        if hasattr(self, "_btn_repair_oracle"):
            self._btn_repair_oracle.setVisible(is_oracle)
        if hasattr(self, "_btn_repair_suse"):
            self._btn_repair_suse.setVisible(is_suse)
        if hasattr(self, "_btn_install_winget"):
            self._btn_install_winget.setEnabled(has_winget and self._is_admin)

    # =========================================================================
    # Install Wizard
    # =========================================================================

    def _open_install_wizard(self) -> None:
        if not self._begin_operation("install"):
            return
        from ui.dialogs import InstallWizard
        wizard = InstallWizard(
            distros=self._distros_cfg,
            install_dir=self._config_mgr.config.install_dir,
            download_dir=self._config_mgr.config.download_dir,
            parent=self,
        )
        if wizard.exec() != QDialog.DialogCode.Accepted:
            self._end_operation("install")
            return

        distro_id = wizard.selected_distro_id
        if distro_id not in self._distros_cfg:
            self._end_operation("install")
            QMessageBox.critical(self, t("Error"), t("Unknown distro id: {distro_id}", distro_id=distro_id))
            return

        distro_cfg = dict(self._distros_cfg[distro_id])
        distro_cfg["systemd"] = wizard.enable_systemd

        if distro_cfg.get("install_method") == "wsl_online":
            # Keep one coherent path for all online installs so directories,
            # cache handling, and user injection behave consistently.
            self._start_online_install_in_external_powershell(distro_cfg, wizard)
            return

        if wizard.run_in_external_powershell:
            QMessageBox.warning(
                self,
                t("External install not available"),
                t("Separate PowerShell install is available only for online WSL catalog distros."),
            )

        self._log_t("\n=== Installing {name} ===", name=distro_cfg["display_name"])

        worker = InstallWorker(
            engine=self._engine,
            config_mgr=self._config_mgr,
            distro_id=distro_id,
            distro_cfg=distro_cfg,
            wsl_name=wizard.wsl_name,
            install_dir=wizard.install_dir,
            download_dir=wizard.download_dir,
            username=wizard.username,
            password=wizard.password,
            run_system_update=wizard.run_system_update,
            wsl_version=wizard.wsl_version,
            parent=self,
        )
        worker.log_message.connect(self._log)
        worker.error_occurred.connect(lambda e: self._log(e, color="#F44336"))
        worker.stage_changed.connect(self._set_stage)
        worker.progress.connect(self._on_progress)
        worker.install_finished.connect(lambda n: (
            self._set_stage(t("Ready")),
            self._refresh_distros(),
        ))
        worker.finished.connect(lambda: self._end_operation("install"))
        self._track_worker(worker, "install pipeline")

    def _start_online_install_in_external_powershell(self, distro_cfg: dict, wizard) -> None:
        online_name = str(distro_cfg.get("online_name", "")).strip()
        if not online_name:
            self._end_operation("install")
            QMessageBox.critical(self, t("Error"), t("Missing online distro name."))
            return
        source_display_name = str(distro_cfg.get("display_name", online_name)).strip()
        username = wizard.username.strip()
        password = wizard.password
        oracle_mode = online_name.lower().startswith("oraclelinux_")
        source_legacy_name = online_name.replace("OracleLinux_", "Oracle Linux ").replace("_", ".")
        disable_no_launch = bool(distro_cfg.get("legacy_non_interactive_disable", False))

        target_name = wizard.wsl_name.strip() or online_name
        install_dir = str(Path(wizard.install_dir) / target_name)
        download_dir = wizard.download_dir.strip()
        export_file = str(Path(download_dir) / f"{target_name}.tar")
        run_update = wizard.run_system_update
        wsl_version = wizard.wsl_version

        pkg_manager = str(distro_cfg.get("pkg_manager", "apt"))
        packages = distro_cfg.get("packages", []) or []
        pkg_list = ""
        sudo_group = str(distro_cfg.get("sudo_group", "sudo"))

        export_path = Path(export_file)
        cache_state = "MISS"
        if not oracle_mode:
            if export_path.exists():
                try:
                    subprocess.run(
                        ["tar.exe", "-tf", str(export_path)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=True,
                    )
                    cache_state = "HIT"
                except Exception:  # noqa: BLE001
                    cache_state = "STALE"

        if oracle_mode:
            self._log_t("[ORACLE MODE] Using direct install flow (no export/import cache).", color="#64B5F6")
            self._set_stage(t("Oracle direct install"))
            self._set_cache_status(f"{target_name} DIRECT", "none")
        elif cache_state == "HIT":
            self._log_t("[CACHE HIT] Reusing existing export: {path}", color="#4CAF50", path=export_file)
            self._set_stage(t("Cache HIT"))
            self._set_cache_status(f"{target_name} HIT", "hit")
        elif cache_state == "STALE":
            self._log_t(
                "[CACHE STALE] Invalid export found, it will be regenerated: {path}",
                color="#FFC107",
                path=export_file,
            )
            self._set_stage(t("Cache STALE"))
            self._set_cache_status(f"{target_name} STALE", "stale")
        else:
            self._log_t("[CACHE MISS] No export cache found, source distro will be prepared.", color="#64B5F6")
            self._set_stage(t("Cache MISS"))
            self._set_cache_status(f"{target_name} MISS", "miss")

        def _ps_sq(value: str) -> str:
            return value.replace("'", "''")

        update_cmd = ""
        if run_update:
            if pkg_manager == "apt":
                update_cmd = "DEBIAN_FRONTEND=noninteractive apt-get update && DEBIAN_FRONTEND=noninteractive apt-get upgrade -y"
            elif pkg_manager == "dnf":
                update_cmd = "dnf upgrade --refresh -y"
            elif pkg_manager == "pacman":
                update_cmd = "pacman-key --init && pacman-key --populate archlinux && pacman -Syu --noconfirm"
            elif pkg_manager == "apk":
                update_cmd = "apk update && apk upgrade"
            elif pkg_manager == "zypper":
                update_cmd = "zypper --non-interactive refresh && zypper --non-interactive update"
            else:
                update_cmd = "true"

        install_pkgs_cmd = ""
        if packages:
            pkg_list = " ".join(shlex.quote(str(p)) for p in packages)
            if pkg_manager == "apt":
                install_pkgs_cmd = f"DEBIAN_FRONTEND=noninteractive apt-get install -y {pkg_list}"
            elif pkg_manager == "dnf":
                install_pkgs_cmd = f"dnf install -y {pkg_list}"
            elif pkg_manager == "pacman":
                install_pkgs_cmd = f"pacman -S --noconfirm {pkg_list}"
            elif pkg_manager == "apk":
                install_pkgs_cmd = f"apk add {pkg_list}"
            elif pkg_manager == "zypper":
                install_pkgs_cmd = f"zypper --non-interactive install --no-recommends {pkg_list}"
            else:
                install_pkgs_cmd = "true"

        if run_update and update_cmd != "true":
            update_cmd = (
                "if command -v apt-get >/dev/null 2>&1; then "
                "DEBIAN_FRONTEND=noninteractive apt-get update && DEBIAN_FRONTEND=noninteractive apt-get upgrade -y; "
                "elif command -v dnf >/dev/null 2>&1; then "
                "dnf upgrade --refresh -y; "
                "elif command -v pacman >/dev/null 2>&1; then "
                "pacman-key --init && pacman-key --populate archlinux && pacman -Syu --noconfirm; "
                "elif command -v apk >/dev/null 2>&1; then "
                "apk update && apk upgrade; "
                "elif command -v zypper >/dev/null 2>&1; then "
                "zypper --non-interactive refresh && zypper --non-interactive update; "
                "else echo 'No supported package manager found.' >&2; exit 1; fi"
            )

        if packages and install_pkgs_cmd != "true":
            install_pkgs_cmd = (
                "if command -v apt-get >/dev/null 2>&1; then "
                f"DEBIAN_FRONTEND=noninteractive apt-get install -y {pkg_list}; "
                "elif command -v dnf >/dev/null 2>&1; then "
                f"dnf install -y {pkg_list}; "
                "elif command -v pacman >/dev/null 2>&1; then "
                f"pacman -S --noconfirm {pkg_list}; "
                "elif command -v apk >/dev/null 2>&1; then "
                f"apk add {pkg_list}; "
                "elif command -v zypper >/dev/null 2>&1; then "
                f"zypper --non-interactive install --no-recommends {pkg_list}; "
                "else echo 'No supported package manager found.' >&2; exit 1; fi"
            )

        post_lines: list[str] = []
        # Configure user first so account/default-user settings are applied even
        # when long update operations fail or are interrupted.
        if username:
            safe_user = shlex.quote(username)
            safe_group = shlex.quote(sudo_group)
            post_lines.append(f"id -u {safe_user} >/dev/null 2>&1 || useradd -m -s /bin/bash {safe_user}")
            post_lines.append(
                "_tmpf=$(mktemp) "
                f"&& printf '%s:%s\\n' {safe_user} \"$WSL_MANAGER_INITIAL_PASS\" > \"$_tmpf\" "
                "&& chpasswd < \"$_tmpf\" "
                "&& rm -f \"$_tmpf\""
            )
            post_lines.append(
                f"getent group {safe_group} >/dev/null 2>&1 || groupadd {safe_group} ; "
                f"usermod -aG {safe_group} {safe_user}"
            )
            wsl_conf = f"[user]\ndefault={username}\n"
            escaped_conf = wsl_conf.replace("'", "'\\''")
            post_lines.append(f"printf '%s' '{escaped_conf}' > /etc/wsl.conf")
        if update_cmd:
            post_lines.append(update_cmd)
        if install_pkgs_cmd:
            post_lines.append(install_pkgs_cmd)

        script_path = Path(tempfile.gettempdir()) / f"wsl_manager_install_{online_name}.ps1"
        post_cmd_array = ""
        post_block = ""
        if post_lines:
            post_cmd_array = "\n".join(
                f"    '{_ps_sq(cmd)}'" + ("," if i < len(post_lines) - 1 else "")
                for i, cmd in enumerate(post_lines)
            )
            post_block = (
                "Write-Host 'Running post-install configuration...' -ForegroundColor Cyan\n"
                "if ($InitialPass) { $env:WSL_MANAGER_INITIAL_PASS = $InitialPass }\n"
                "$PostCmds = @(\n"
                f"{post_cmd_array}\n"
                ")\n"
                "foreach ($PostCmd in $PostCmds) {\n"
                "    $PostCmd = $PostCmd -replace \"`r\",\"\"\n"
                "    wsl.exe -d $PostConfigDistro -u root -- bash -lc \"$PostCmd\"\n"
                "    if ($LASTEXITCODE -ne 0) { throw \"Post-install failed with exit code $LASTEXITCODE\" }\n"
                "}\n"
                "Remove-Item Env:\\WSL_MANAGER_INITIAL_PASS -ErrorAction SilentlyContinue\n"
            )

        home_block = ""
        if username:
            home_block = (
                "Write-Host 'Applying default user/home startup...' -ForegroundColor Cyan\n"
                "wsl.exe --shutdown\n"
                f"wsl.exe -d '{target_name}' -u '{username}' --cd '/home/{username}' -- bash -lc 'pwd && whoami'\n"
                "if ($LASTEXITCODE -ne 0) { Write-Warning \"Home startup validation failed with exit code $LASTEXITCODE\" }\n"
            )

        if oracle_mode:
            script_text = (
                "$ErrorActionPreference = 'Stop'\n"
                f"$SourceDistro = '{_ps_sq(online_name)}'\n"
                f"$SourceDisplayName = '{_ps_sq(source_display_name)}'\n"
                f"$SourceLegacyName = '{_ps_sq(source_legacy_name)}'\n"
                f"$InitialUser = '{_ps_sq(username)}'\n"
                "$InitialPass = $env:WSL_MANAGER_INITIAL_PASS\n"
                "Remove-Item Env:\\WSL_MANAGER_INITIAL_PASS -ErrorAction SilentlyContinue\n"
                f"$DistroName = '{_ps_sq(target_name)}'\n"
                f"$InstallDir = '{_ps_sq(install_dir)}'\n"
                f"$DownloadDir = '{_ps_sq(download_dir)}'\n"
                f"$ExportFile = '{_ps_sq(export_file)}'\n"
                "$LogDir = Join-Path $DownloadDir 'logs'\n"
                "New-Item -ItemType Directory -Force $LogDir | Out-Null\n"
                "$Ts = Get-Date -Format 'yyyyMMdd_HHmmss'\n"
                "$SafeName = ($DistroName -replace '[^a-zA-Z0-9._-]','_')\n"
                "$LogFile = Join-Path $LogDir (\"install_{0}_{1}.log\" -f $SafeName, $Ts)\n"
                "Start-Transcript -Path $LogFile -Force | Out-Null\n"
                "Write-Host (\"Saving detailed log to: {0}\" -f $LogFile) -ForegroundColor DarkGray\n"
                "Write-Host (\"Target distro: {0}\" -f $DistroName) -ForegroundColor DarkGray\n"
                "Write-Host (\"Install dir: {0}\" -f $InstallDir) -ForegroundColor DarkGray\n"
                "Write-Host (\"Export tar: {0}\" -f $ExportFile) -ForegroundColor DarkGray\n"
                "try {\n"
                "$InstalledBefore = wsl.exe --list --quiet\n"
                "$BeforeNames = @()\n"
                "foreach ($ln in ($InstalledBefore -split \"`n\")) {\n"
                "    $n = $ln.Trim()\n"
                "    if ($n) { $BeforeNames += $n }\n"
                "}\n"
                "New-Item -ItemType Directory -Force $InstallDir | Out-Null\n"
                "New-Item -ItemType Directory -Force $DownloadDir | Out-Null\n"
                "$SourceExportName = $null\n"
                "if ($BeforeNames -contains $SourceDistro) {\n"
                "    $SourceExportName = $SourceDistro\n"
                "} elseif ($BeforeNames -contains $SourceLegacyName) {\n"
                "    $SourceExportName = $SourceLegacyName\n"
                "} elseif ($BeforeNames -contains $SourceDisplayName) {\n"
                "    $SourceExportName = $SourceDisplayName\n"
                "}\n"
                "if (-not $SourceExportName) {\n"
                "    Write-Host 'Installing Oracle source distro (legacy-compatible)...' -ForegroundColor Cyan\n"
                "    Write-Host 'Oracle setup is interactive on this Windows build.' -ForegroundColor Yellow\n"
                "    Write-Host 'When prompted, create the temporary Oracle user in this window to continue.' -ForegroundColor Yellow\n"
                "    if ($InitialUser) { Write-Host ('Use this username when prompted: {0}' -f $InitialUser) -ForegroundColor Yellow }\n"
                "    Write-Host 'When the Oracle shell opens, type exit so the manager can continue exporting/importing.' -ForegroundColor Yellow\n"
                "    wsl.exe --install -d $SourceDistro\n"
                "    if ($LASTEXITCODE -ne 0) { throw (\"wsl --install (oracle mode) failed with exit code {0}\" -f $LASTEXITCODE) }\n"
                "    $AfterNames = @()\n"
                "    $ResolveDeadline = (Get-Date).AddSeconds(120)\n"
                "    do {\n"
                "        $InstalledAfter = wsl.exe --list --quiet\n"
                "        $AfterNames = @()\n"
                "        foreach ($ln in ($InstalledAfter -split \"`n\")) {\n"
                "            $n = $ln.Trim()\n"
                "            if ($n) { $AfterNames += $n }\n"
                "        }\n"
                "        if (($AfterNames -contains $SourceDistro) -or ($AfterNames -contains $SourceLegacyName) -or ($AfterNames -contains $SourceDisplayName)) { break }\n"
                "        Start-Sleep -Milliseconds 500\n"
                "    } while ((Get-Date) -lt $ResolveDeadline)\n"
                "    if ($AfterNames -contains $SourceDistro) {\n"
                "        $SourceExportName = $SourceDistro\n"
                "    } elseif ($AfterNames -contains $SourceLegacyName) {\n"
                "        $SourceExportName = $SourceLegacyName\n"
                "    } elseif ($AfterNames -contains $SourceDisplayName) {\n"
                "        $SourceExportName = $SourceDisplayName\n"
                "    } else {\n"
                "        foreach ($n in $AfterNames) {\n"
                "            if (-not ($BeforeNames -contains $n)) {\n"
                "                $SourceExportName = $n\n"
                "                break\n"
                "            }\n"
                "        }\n"
                "    }\n"
                "} else {\n"
                "    Write-Host ('Reusing existing Oracle source distro: {0}' -f $SourceExportName) -ForegroundColor Cyan\n"
                "}\n"
                "if (-not $SourceExportName) {\n"
                "    throw 'Could not determine Oracle source distro name.'\n"
                "}\n"
                "Write-Host ('Stopping Oracle source distro before export: {0}' -f $SourceExportName) -ForegroundColor Cyan\n"
                "$null = wsl.exe --terminate $SourceExportName 2>$null\n"
                "wsl.exe --shutdown\n"
                "$PostConfigDistro = $SourceExportName\n"
                f"{post_block}"
                "wsl.exe --shutdown\n"
                "if (($DistroName -ne $SourceExportName) -and (($BeforeNames -contains $DistroName) -or ((wsl.exe --list --quiet) -match [regex]::Escape($DistroName)))) {\n"
                "    Write-Host 'Removing previous target distro if present...' -ForegroundColor Cyan\n"
                "    $null = wsl.exe --unregister $DistroName 2>$null\n"
                "}\n"
                "Write-Host (\"Exporting Oracle source distro: {0}\" -f $SourceExportName) -ForegroundColor Cyan\n"
                "$null = Remove-Item -Force $ExportFile -ErrorAction SilentlyContinue\n"
                "wsl.exe --export $SourceExportName $ExportFile\n"
                "if ($LASTEXITCODE -ne 0) { throw (\"wsl --export failed for source distro '{0}' with exit code {1}\" -f $SourceExportName, $LASTEXITCODE) }\n"
                "Write-Host 'Unregistering temporary Oracle source distro...' -ForegroundColor Cyan\n"
                "$null = wsl.exe --unregister $SourceExportName 2>$null\n"
                "Write-Host 'Importing Oracle target distro...' -ForegroundColor Cyan\n"
                f"wsl.exe --import $DistroName $InstallDir $ExportFile --version {wsl_version}\n"
                "if ($LASTEXITCODE -ne 0) { throw \"wsl --import (oracle mode) failed with exit code $LASTEXITCODE\" }\n"
                "wsl.exe --set-default $DistroName\n"
                "if ($LASTEXITCODE -ne 0) { throw \"wsl --set-default failed with exit code $LASTEXITCODE\" }\n"
                f"{home_block}"
                "Write-Host ''\n"
                "Write-Host 'Installation completed.' -ForegroundColor Green\n"
                "Write-Host 'Press any key to close this window.' -ForegroundColor Yellow\n"
                "}\n"
                "finally {\n"
                "    Remove-Item Env:\\WSL_MANAGER_INITIAL_PASS -ErrorAction SilentlyContinue\n"
                "    Stop-Transcript | Out-Null\n"
                "    Write-Host (\"Log saved to: {0}\" -f $LogFile) -ForegroundColor DarkGray\n"
                "    [void][System.Console]::ReadKey($true)\n"
                "}\n"
            )
        else:
            script_text = (
                "$ErrorActionPreference = 'Stop'\n"
                f"$SourceDistro = '{_ps_sq(online_name)}'\n"
                f"$SourceDisplayName = '{_ps_sq(source_display_name)}'\n"
                f"$DisableNoLaunch = {'$true' if disable_no_launch else '$false'}\n"
                "$InitialPass = $env:WSL_MANAGER_INITIAL_PASS\n"
                "Remove-Item Env:\\WSL_MANAGER_INITIAL_PASS -ErrorAction SilentlyContinue\n"
                f"$DistroName = '{_ps_sq(target_name)}'\n"
                f"$InstallDir = '{_ps_sq(install_dir)}'\n"
                f"$DownloadDir = '{_ps_sq(download_dir)}'\n"
                f"$ExportFile = '{_ps_sq(export_file)}'\n"
                "$LogDir = Join-Path $DownloadDir 'logs'\n"
                "New-Item -ItemType Directory -Force $LogDir | Out-Null\n"
                "$Ts = Get-Date -Format 'yyyyMMdd_HHmmss'\n"
                "$SafeName = ($DistroName -replace '[^a-zA-Z0-9._-]','_')\n"
                "$LogFile = Join-Path $LogDir (\"install_{0}_{1}.log\" -f $SafeName, $Ts)\n"
                "Start-Transcript -Path $LogFile -Force | Out-Null\n"
                "Write-Host (\"Saving detailed log to: {0}\" -f $LogFile) -ForegroundColor DarkGray\n"
                "Write-Host (\"Target distro: {0}\" -f $DistroName) -ForegroundColor DarkGray\n"
                "Write-Host (\"Install dir: {0}\" -f $InstallDir) -ForegroundColor DarkGray\n"
                "Write-Host (\"Export tar: {0}\" -f $ExportFile) -ForegroundColor DarkGray\n"
                "try {\n"
                "$Installed = wsl.exe --list --quiet\n"
                "$InstalledNames = @()\n"
                "foreach ($ln in ($Installed -split \"`n\")) {\n"
                "    $n = $ln.Trim()\n"
                "    if ($n) { $InstalledNames += $n }\n"
                "}\n"
                "$SourceExportName = $null\n"
                "New-Item -ItemType Directory -Force $InstallDir | Out-Null\n"
                "New-Item -ItemType Directory -Force $DownloadDir | Out-Null\n"
                "$UseCachedExport = $false\n"
                "if (Test-Path $ExportFile) {\n"
                "    Write-Host 'Found existing exported tar. Validating...' -ForegroundColor Cyan\n"
                "    tar.exe -tf $ExportFile *> $null\n"
                "    if ($LASTEXITCODE -eq 0) {\n"
                "        $UseCachedExport = $true\n"
                "        Write-Host '[CACHE HIT] Cached export is valid. Reusing it (no re-download).' -ForegroundColor Green\n"
                "    } else {\n"
                "        Write-Host '[CACHE STALE] Cached export is invalid. Rebuilding export...' -ForegroundColor Yellow\n"
                "        Remove-Item -Force $ExportFile -ErrorAction SilentlyContinue\n"
                "    }\n"
                "}\n"
                "if (-not $UseCachedExport) {\n"
                "    Write-Host '[CACHE MISS] No reusable export cache found. Building one now.' -ForegroundColor Cyan\n"
                "    Write-Host 'Preparing temporary source distro...' -ForegroundColor Cyan\n"
                "    if (($InstalledNames -contains $SourceDistro) -or ($InstalledNames -contains $SourceDisplayName) -or ($InstalledNames -contains ($SourceDistro -replace '_', ' '))) {\n"
                "        Write-Host 'Source distro already present. Reusing it for export.' -ForegroundColor Cyan\n"
                "    } else {\n"
                "        if ($DisableNoLaunch) {\n"
                "            Write-Host 'Legacy non-interactive mode disabled for this distro. Running interactive install...' -ForegroundColor Yellow\n"
                "            Write-Host 'If a shell opens, complete temporary setup and type exit to continue.' -ForegroundColor Yellow\n"
                "            wsl.exe --install -d $SourceDistro\n"
                "            if ($LASTEXITCODE -ne 0) { throw \"wsl --install (interactive legacy mode) failed with exit code $LASTEXITCODE\" }\n"
                "        } else {\n"
                "            Write-Host 'Installing official source distro (no launch)...' -ForegroundColor Cyan\n"
                "            wsl.exe --install -d $SourceDistro --no-launch\n"
                "            if ($LASTEXITCODE -ne 0) { throw \"wsl --install failed with exit code $LASTEXITCODE\" }\n"
                "            $ProbeInstalled = wsl.exe --list --quiet\n"
                "            $ProbeNames = @()\n"
                "            foreach ($ln in ($ProbeInstalled -split \"`n\")) {\n"
                "                $n = $ln.Trim()\n"
                "                if ($n) { $ProbeNames += $n }\n"
                "            }\n"
                "            if (-not (($ProbeNames -contains $SourceDistro) -or ($ProbeNames -contains $SourceDisplayName) -or ($ProbeNames -contains ($SourceDistro -replace '_', ' ')))) {\n"
                "                Write-Host 'Legacy install path detected. Completing interactive first boot...' -ForegroundColor Yellow\n"
                "                Write-Host 'If a shell opens, complete temporary setup and type exit to continue.' -ForegroundColor Yellow\n"
                "                wsl.exe --install -d $SourceDistro\n"
                "                if ($LASTEXITCODE -ne 0) { throw \"wsl --install (legacy fallback) failed with exit code $LASTEXITCODE\" }\n"
                "            }\n"
                "        }\n"
                "    }\n"
                "    $InstalledAfter = wsl.exe --list --quiet\n"
                "    $InstalledAfterNames = @()\n"
                "    foreach ($ln in ($InstalledAfter -split \"`n\")) {\n"
                "        $n = $ln.Trim()\n"
                "        if ($n) { $InstalledAfterNames += $n }\n"
                "    }\n"
                "    if ($InstalledAfterNames -contains $SourceDistro) {\n"
                "        $SourceExportName = $SourceDistro\n"
                "    } elseif ($InstalledAfterNames -contains $SourceDisplayName) {\n"
                "        $SourceExportName = $SourceDisplayName\n"
                "    } elseif ($InstalledAfterNames -contains ($SourceDistro -replace '_', ' ')) {\n"
                "        $SourceExportName = ($SourceDistro -replace '_', ' ')\n"
                "    } else {\n"
                "        foreach ($n in $InstalledAfterNames) {\n"
                "            if (-not ($InstalledNames -contains $n)) {\n"
                "                $SourceExportName = $n\n"
                "                break\n"
                "            }\n"
                "        }\n"
                "    }\n"
                "    if (-not $SourceExportName) {\n"
                "        throw (\"Could not determine source distro name for export. Available names: {0}\" -f ($InstalledAfterNames -join ', '))\n"
                "    }\n"
                "    Write-Host 'Exporting source distro...' -ForegroundColor Cyan\n"
                "    wsl.exe --export $SourceExportName $ExportFile\n"
                "    if ($LASTEXITCODE -ne 0) { throw (\"wsl --export failed for source distro '{0}' with exit code {1}\" -f $SourceExportName, $LASTEXITCODE) }\n"
                "    Write-Host 'Keeping exported tar for next runs (cache enabled).' -ForegroundColor Green\n"
                "}\n"
                "if ($DistroName -eq $SourceExportName) {\n"
                "    $null = wsl.exe --unregister $SourceExportName 2>$null\n"
                "}\n"
                "Write-Host 'Removing previous target distro if present...' -ForegroundColor Cyan\n"
                "$null = wsl.exe --unregister $DistroName 2>$null\n"
                "Write-Host 'Importing target distro...' -ForegroundColor Cyan\n"
                f"wsl.exe --import $DistroName $InstallDir $ExportFile --version {wsl_version}\n"
                "if ($LASTEXITCODE -ne 0) { throw \"wsl --import failed with exit code $LASTEXITCODE\" }\n"
                "$PostConfigDistro = $DistroName\n"
                f"{post_block}"
                "wsl.exe --set-default $DistroName\n"
                "if ($LASTEXITCODE -ne 0) { throw \"wsl --set-default failed with exit code $LASTEXITCODE\" }\n"
                f"{home_block}"
                "Write-Host ''\n"
                "Write-Host 'Installation completed.' -ForegroundColor Green\n"
                "Write-Host 'Press any key to close this window.' -ForegroundColor Yellow\n"
                "}\n"
                "finally {\n"
                "    Remove-Item Env:\\WSL_MANAGER_INITIAL_PASS -ErrorAction SilentlyContinue\n"
                "    Stop-Transcript | Out-Null\n"
                "    Write-Host (\"Log saved to: {0}\" -f $LogFile) -ForegroundColor DarkGray\n"
                "    [void][System.Console]::ReadKey($true)\n"
                "}\n"
            )
        script_path.write_text(script_text, encoding="utf-8")

        ps = shutil.which("pwsh.exe") or shutil.which("powershell.exe") or "powershell.exe"
        try:
            env = os.environ.copy()
            if username:
                env["WSL_MANAGER_INITIAL_PASS"] = password
            proc = subprocess.Popen(
                [
                    ps,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script_path),
                ],
                creationflags=subprocess.CREATE_NEW_CONSOLE,
                env=env,
            )
            aliases = {target_name, online_name, source_display_name, source_legacy_name}
            for alias in aliases:
                if alias:
                    self._external_install_procs[alias.strip().lower()] = proc
            self._config_mgr.register_installed_distro(
                InstalledDistro(
                    name=target_name,
                    distro_id="online:" + online_name.lower(),
                    install_dir=install_dir,
                    installed_at=datetime.now().isoformat(),
                    username=username,
                )
            )
            self._log(
                t(
                    "Opened separate PowerShell install console for '{name}'. Use Refresh after it finishes.",
                    name=online_name,
                )
            )
            self._set_stage(t("External install running"))
            self._end_operation("install")
        except Exception as exc:  # noqa: BLE001
            self._end_operation("install")
            QMessageBox.critical(self, t("PowerShell launch failed"), str(exc))

    # =========================================================================
    # Settings actions
    # =========================================================================

    def _save_settings(self) -> bool:
        cfg = self._config_mgr.config
        cfg.install_dir      = self._cfg_install_edit.text().strip()
        cfg.download_dir     = self._cfg_dl_edit.text().strip()
        cfg.remote_catalog_url = self._remote_catalog_url_edit.text().strip()
        cfg.run_as_admin = self._run_as_admin_check.isChecked()
        cfg.check_for_updates = self._check_for_updates_check.isChecked()
        cfg.update_repo_url = self._update_repo_url_edit.text().strip()
        cfg.memory_limit_gb  = self._mem_spin.value()
        cfg.swap_size_gb     = self._swap_spin.value()
        cfg.processors       = self._cpu_spin.value()
        cfg.localhost_forwarding = self._localhost_forwarding_check.isChecked()
        cfg.vm_idle_timeout_sec = self._vm_idle_timeout_spin.value()
        cfg.diagnostic_log_tail_lines = self._settings_tab.diagnostic_tail_spin.value()
        try:
            self._config_mgr.save()
        except ConfigValidationError as exc:
            QMessageBox.warning(self, t("Invalid settings"), str(exc))
            self._log_t("[WARNING] Settings were not saved: {error}", color="#FFA500", error=exc)
            return False
        self._log_t("Settings saved.")
        return True

    def _export_diagnostic_bundle(self) -> None:
        """Write diagnostic ZIP (Settings); see :func:`utils.diagnostic_bundle.write_diagnostic_zip`."""
        path, _sel = QFileDialog.getSaveFileName(
            self,
            t("Save diagnostic bundle"),
            str(Path.home() / "WSLManagerPro-diagnostic.zip"),
            t("ZIP archives (*.zip)"),
        )
        if not path:
            return
        if not path.lower().endswith(".zip"):
            path = f"{path}.zip"
        app = QApplication.instance()
        app_version = app.applicationVersion() if app is not None else ""

        wsl_run = None
        if self._wsl_ok and self._engine is not None:

            def _run(args: list[str]) -> tuple[int, str, str]:
                return self._engine._run(args, timeout=WSL_DIAGNOSTIC_TIMEOUT)

            wsl_run = _run

        tail_lines = self._settings_tab.diagnostic_tail_spin.value()
        try:
            write_diagnostic_zip(
                Path(path),
                app_version=app_version or "unknown",
                log_plain=self._log_console.toPlainText(),
                log_tail_lines=tail_lines,
                wsl_run=wsl_run,
            )
        except OSError as exc:
            QMessageBox.warning(self, t("Export failed"), str(exc))
            return
        self._log_t("Diagnostic bundle written to: {path}", path=path)
        QMessageBox.information(
            self,
            t("Diagnostic bundle"),
            t("Created:\n{path}\n\nSee README.txt inside the archive.", path=path),
        )

    def _apply_wslconfig(self) -> None:
        if not self._begin_operation(".wslconfig write"):
            return
        if not self._save_settings():
            self._end_operation(".wslconfig write")
            return
        preview = self._engine.build_wslconfig_text(
            memory_gb=self._mem_spin.value(),
            swap_gb=self._swap_spin.value(),
            processors=self._cpu_spin.value(),
            localhost_forwarding=self._localhost_forwarding_check.isChecked(),
            vm_idle_timeout=self._vm_idle_timeout_spin.value(),
        )
        reply = QMessageBox.question(
            self,
            t("Preview .wslconfig"),
            t("This action overwrites the full .wslconfig file.\n\nPreview:\n\n{preview}\n\nContinue?", preview=preview),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            self._end_operation(".wslconfig write")
            return
        worker = WslConfigWorker(
            engine=self._engine,
            memory_gb=self._mem_spin.value(),
            swap_gb=self._swap_spin.value(),
            processors=self._cpu_spin.value(),
            localhost_forwarding=self._localhost_forwarding_check.isChecked(),
            vm_idle_timeout=self._vm_idle_timeout_spin.value(),
            parent=self,
        )
        worker.log_message.connect(self._log)
        worker.error_occurred.connect(lambda e: self._log(e, color="#F44336"))
        worker.config_written.connect(
            lambda path: QMessageBox.information(
                self,
                t(".wslconfig written"),
                t(
                    "Resource limits written to:\n{path}\n\nRun 'wsl --shutdown' and restart your distributions to apply.",
                    path=path,
                ),
            )
        )
        worker.finished.connect(lambda: self._end_operation(".wslconfig write"))
        self._track_worker(worker, ".wslconfig write")

    # =========================================================================
    # Log console helpers
    # =========================================================================

    def _log(self, text: str, color: str = "") -> None:
        """
        Append *text* to the log console (GUI thread).

        Also writes the same line to the rotating file logger (``utils.app_logging``).
        Do not pass passwords or secrets here.
        """
        text = self._normalize_log_text(text)
        lvl = log_level_for_ui_line(text, color)
        get_logger().log(lvl, "%s", text)
        entry_color = color or COLOR_TEXT
        self._log_lines.append((text, entry_color))
        if len(self._log_lines) > LOG_LINE_HARD_LIMIT:
            self._log_lines = self._log_lines[-LOG_LINE_HARD_LIMIT:]
        self._apply_log_filter()

    def _set_stage(self, stage: str) -> None:
        self._stage_label.setText(f"  {stage}  ")

    def _apply_log_filter(self) -> None:
        pattern = self._log_filter_edit.text().strip().lower() if hasattr(self, "_log_filter_edit") else ""
        self._log_console.clear()
        for line, color in self._log_lines:
            if pattern and pattern not in line.lower():
                continue
            cursor = self._log_console.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self._log_console.setTextCursor(cursor)
            self._log_console.setTextColor(QColor(color))
            self._log_console.insertPlainText(line + "\n")
        self._log_console.setTextColor(QColor(COLOR_TEXT))
        self._log_console.ensureCursorVisible()

    def _copy_all_logs(self) -> None:
        QApplication.clipboard().setText("\n".join(line for line, _color in self._log_lines))

    def _copy_selected_logs(self) -> None:
        selected = self._log_console.textCursor().selectedText().replace("\u2029", "\n")
        QApplication.clipboard().setText(selected or self._log_console.toPlainText())

    def _on_progress(self, done: int, total: int) -> None:
        if total > 0:
            pct = int(done * 100 / total)
            mb_done  = done  / (1024 * 1024)
            mb_total = total / (1024 * 1024)
            self._set_stage(
                t(
                    "Downloading {pct}%  ({done_mb:.1f} / {total_mb:.1f} MB)",
                    pct=pct,
                    done_mb=mb_done,
                    total_mb=mb_total,
                )
            )
        else:
            kb = done / 1024
            self._set_stage(t("Downloading ... {kb:.0f} KB", kb=kb))

    def _default_shell_user(self, name: str) -> str:
        installed = self._config_mgr.find_installed(name)
        if installed and installed.username:
            configured = installed.username.strip()
            if configured and self._wsl_user_exists(name, configured):
                return configured
        probed = self._probe_default_user(name)
        if probed and probed != "root":
            return probed
        try:
            rc, stdout, _stderr = self._engine._run(
                [
                    "-d", name,
                    "--", "bash", "-lc", "id -un",
                ],
                timeout=WSL_SHELL_USER_TIMEOUT,
            )
            if rc == 0:
                candidate = stdout.strip().splitlines()
                if candidate:
                    user = candidate[-1].strip()
                    if user and user != "root":
                        return user
        except Exception:  # noqa: BLE001
            pass
        return ""

    def _probe_default_user(self, distro_name: str) -> str:
        """Best-effort probe of distro's default user from inside Linux."""
        engine = self._engine
        if engine is None:
            return ""
        try:
            rc, stdout, _stderr = engine._run(
                [
                    "-d", distro_name,
                    "--", "bash", "-lc", "id -un",
                ],
                timeout=WSL_DEFAULT_USER_TIMEOUT,
            )
            if rc == 0:
                lines = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
                if lines:
                    return lines[-1]
        except Exception:  # noqa: BLE001
            pass
        return ""

    def _wsl_user_exists(self, distro_name: str, username: str) -> bool:
        user = username.strip()
        if not user:
            return False
        try:
            quoted_user = shlex.quote(user)
            rc, _out, _err = self._engine._run(
                [
                    "-d", distro_name,
                    "-u", "root",
                    "--", "bash", "-lc", f"id -u {quoted_user} >/dev/null 2>&1",
                ],
                timeout=WSL_USER_EXISTS_TIMEOUT,
            )
            return rc == 0
        except Exception:  # noqa: BLE001
            return False

    def _set_cache_status(self, text: str, level: str = "none") -> None:
        self._cache_status_value = text
        self._cache_status_level = level
        colors = {
            "hit": "#4CAF50",
            "miss": "#64B5F6",
            "stale": "#FFC107",
            "none": "#d4d4d4",
        }
        self._cache_label.setText(f"  {t('Cache: {value}', value=text)}  ")
        self._cache_label.setStyleSheet(f"color: {colors.get(level, '#d4d4d4')};")

    def _normalize_log_text(self, text: str) -> str:
        replacements = {
            "…": "...",
            "→": "->",
            "✓": "[OK]",
            "⚠": "[WARN]",
            "●": "*",
            "＋": "+",
            "⟳": "[refresh]",
            "⬛": "[stop]",
            "—": "-",
            "–": "-",
        }
        normalized = text
        for old, new in replacements.items():
            normalized = normalized.replace(old, new)
        return normalized

    # =========================================================================
    # File browser helpers
    # =========================================================================

    def _browse_dir(self, line_edit: QLineEdit) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select directory", line_edit.text() or "")
        if path:
            line_edit.setText(path)

    def _browse_file(self, line_edit: QLineEdit, title: str, filter_: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, title, line_edit.text() or "", filter_)
        if path:
            line_edit.setText(path)

    def _browse_save(self, line_edit: QLineEdit, title: str, filter_: str) -> None:
        path, _ = QFileDialog.getSaveFileName(self, title, line_edit.text() or "", filter_)
        if path:
            line_edit.setText(path)

    # =========================================================================
    # Helpers
    # =========================================================================

    def _load_distros_catalog(self) -> dict:
        catalog_path = Path(__file__).parent.parent / "distros.json"
        result = load_catalog(
            catalog_path,
            remote_url=self._config_mgr.config.remote_catalog_url,
        )
        self._catalog_source = result.source
        self._catalog_warnings = list(result.warnings)
        return result.entries

    def _build_install_catalog(self) -> dict:
        """
        Build the Install wizard catalog from ``wsl --list --online``.
        Falls back to ``distros.json`` when online catalog is unavailable.
        """
        if not self._wsl_ok:
            return dict(self._static_distros_cfg)

        try:
            online_distros = self._engine.list_online_distros()
        except WslCommandError:
            return dict(self._static_distros_cfg)

        if not online_distros:
            return dict(self._static_distros_cfg)

        catalog: dict[str, dict] = {}
        used_ids: set[str] = set()

        for online in online_distros:
            distro_id = self._make_online_distro_id(online.name, used_ids)
            inferred = self._infer_pkg_profile(online.name)
            cfg: dict = {
                "display_name": online.friendly_name or online.name,
                "description": f"Official WSL catalog distro: {online.name}",
                "install_method": "wsl_online",
                "online_name": online.name,
                "pkg_manager": inferred["pkg_manager"],
                "sudo_group": inferred["sudo_group"],
                "packages": inferred["packages"],
                "systemd": inferred["systemd"],
            }

            matched = self._find_static_metadata_for_online(online.name)
            if matched:
                for key in ("pkg_manager", "sudo_group", "packages", "systemd", "legacy_non_interactive_disable"):
                    if key in matched:
                        cfg[key] = matched[key]

            catalog[distro_id] = cfg

        return catalog

    def _infer_pkg_profile(self, online_name: str) -> dict:
        """Best-effort package manager profile for WSL online catalog distros."""
        n = online_name.lower()
        if "suse" in n:
            return {
                "pkg_manager": "zypper",
                "sudo_group": "wheel",
                "packages": ["curl", "git", "nano", "procps", "sudo", "wget", "ca-certificates"],
                "systemd": True,
            }
        if "elxr" in n:
            return {
                "pkg_manager": "apt",
                "sudo_group": "sudo",
                "packages": ["curl", "git", "nano", "procps", "sudo", "wget", "ca-certificates"],
                "systemd": True,
            }
        if "fedora" in n or "almalinux" in n or "oraclelinux" in n:
            return {
                "pkg_manager": "dnf",
                "sudo_group": "wheel",
                "packages": ["curl", "git", "nano", "procps-ng", "sudo", "wget", "ca-certificates"],
                "systemd": True,
            }
        if "arch" in n:
            return {
                "pkg_manager": "pacman",
                "sudo_group": "wheel",
                "packages": ["curl", "git", "nano", "procps-ng", "sudo", "wget", "ca-certificates"],
                "systemd": True,
            }
        if "alpine" in n:
            return {
                "pkg_manager": "apk",
                "sudo_group": "wheel",
                "packages": ["bash", "curl", "git", "nano", "procps", "sudo", "wget", "ca-certificates", "shadow"],
                "systemd": False,
            }
        return {
            "pkg_manager": "apt",
            "sudo_group": "sudo",
            "packages": ["curl", "git", "nano", "procps", "sudo", "wget", "ca-certificates"],
            "systemd": True,
        }

    def _make_online_distro_id(self, online_name: str, used_ids: set[str]) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", online_name.lower()).strip("-") or "distro"
        candidate = base
        i = 2
        while candidate in used_ids:
            candidate = f"{base}-{i}"
            i += 1
        used_ids.add(candidate)
        return candidate

    def _find_static_metadata_for_online(self, online_name: str) -> Optional[dict]:
        needle = online_name.lower()
        for cfg in self._static_distros_cfg.values():
            explicit_name = str(cfg.get("online_name", "")).strip().lower()
            if explicit_name and explicit_name == needle:
                return cfg

        normalized = re.sub(r"[^a-z0-9]", "", needle)
        for cfg in self._static_distros_cfg.values():
            display = re.sub(r"[^a-z0-9]", "", str(cfg.get("display_name", "")).lower())
            if display and (normalized in display or display in normalized):
                return cfg
        return None

    def _announce_startup_issues(self) -> None:
        infos = []
        infos.extend(self._config_mgr.startup_infos)
        warnings = []
        warnings.extend(self._config_mgr.startup_warnings)
        warnings.extend(self._catalog_warnings)
        if not infos and not warnings:
            return

        self._startup_messages = list(infos) + list(warnings)
        for info in infos:
            self._log(f"[INFO] {info}", color=COLOR_INFO)
        for warning in warnings:
            self._log(f"[WARNING] {warning}", color=COLOR_WARNING)

        if warnings:
            QMessageBox.warning(
                self,
                t("Configuration warnings"),
                t("WSL Manager Pro loaded with safe fallbacks.\n\n") + "\n".join(warnings),
            )

    def _set_catalog_status(self, source: str) -> None:
        self._catalog_status_source = source
        colors = {
            "local": "#64B5F6",
            "remote-merged": "#4CAF50",
            "remote-fallback": "#FFC107",
        }
        text = {
            "local": "local",
            "remote-merged": "remote merged",
            "remote-fallback": "remote fallback",
        }.get(source, source)
        self._catalog_label.setText(f"  {t('Catalog: {source}', source=text)}  ")
        self._catalog_label.setStyleSheet(f"color: {colors.get(source, '#d4d4d4')};")

    def closeEvent(self, event) -> None:
        self._refresh_timer.stop()
        for _alias, proc in list(self._shell_procs.items()):
            self._terminate_tracked_process(proc)
        self._shell_procs.clear()
        for _alias, proc in list(self._external_install_procs.items()):
            self._terminate_tracked_process(proc)
        self._external_install_procs.clear()

        for worker in list(self._active_workers):
            self._log(
                t(
                    "[DEBUG] Close snapshot: {name} ({label}) running={running}",
                    name=worker.__class__.__name__,
                    label=self._worker_label(worker),
                    running=str(worker.isRunning()).lower(),
                ),
                color=COLOR_MUTED,
            )
            cancel = getattr(worker, "cancel", None)
            if callable(cancel):
                try:
                    cancel()
                except Exception:
                    pass
            if worker.isRunning():
                worker.requestInterruption()

        deadline = time.monotonic() + 8.0
        for worker in list(self._active_workers):
            if worker.isRunning():
                remaining_ms = max(100, int((deadline - time.monotonic()) * 1000))
                worker.wait(remaining_ms)
        for worker in list(self._active_workers):
            if worker.isRunning():
                self._log(
                    t(
                        "[WARN] Forcing shutdown of busy background worker '{name}' ({label}).",
                        name=worker.__class__.__name__,
                        label=self._worker_label(worker),
                    ),
                    color="#FFC107",
                )
                worker.terminate()
                worker.wait(500)
        event.accept()
