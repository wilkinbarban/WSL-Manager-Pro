"""
ui/tabs/dashboard_tab.py
========================

Dashboard tab displaying the live WSL distribution status table, a count
label, and header-level action buttons (Refresh, Re-scan Users).

The table has 7 columns: status icon, name, state, WSL version, default flag,
user configuration status, and an action button (Start/Stop).

Signals
-------
* :attr:`DashboardTab.refresh_requested` — Emitted when the Refresh button
  is clicked.  Connect from :class:`~ui.main_window.MainWindow` to
  ``_refresh_distros``.
* :attr:`DashboardTab.rescan_users_requested` — Emitted when the Re-scan
  User Status button is clicked.  Connect to ``_rescan_user_status``.
* :attr:`DashboardTab.retry_detection_requested` — Emitted when the Retry
  Detection button is clicked (shown when WSL is unavailable).  Connect to
  ``_retry_wsl_detection``.

Context menu
------------
The table's right-click context menu is delegated to
:meth:`~ui.main_window.MainWindow._show_distro_context_menu` in the main
window, keeping menu logic centralised.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from utils.i18n import get_i18n, t


class DashboardTab(QWidget):
    """Live WSL distribution status table with header-level action controls.

    Composed of:
    * A header panel with title, distro count label, Refresh button,
      and Re-scan User Status button.
    * A 7-column :class:`QTableWidget` showing each registered WSL distro.
    * An empty-state message shown when no distros are registered.

    Signals
    -------
    refresh_requested : Signal
        Emitted when the user clicks Refresh.
    rescan_users_requested : Signal
        Emitted when the user clicks Re-scan User Status.
    retry_detection_requested : Signal
        Emitted when the user clicks Retry Detection (WSL unavailable).
    """

    refresh_requested = Signal()
    rescan_users_requested = Signal()
    retry_detection_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.table = QTableWidget()
        self.distro_count_label = QLabel("")
        self.empty_state = QLabel("")
        self.empty_state.setWordWrap(True)
        self.empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_state.setStyleSheet("color: #888; padding: 16px;")
        self.retry_button = QPushButton("Retry detection")
        self.retry_button.clicked.connect(self.retry_detection_requested.emit)
        self._build_ui()
        get_i18n().language_changed.connect(lambda _lang: self.retranslate_ui())

    def _compact_button(self, button: QPushButton, max_width: int | None = None) -> None:
        button.setObjectName("compactButton")
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        if max_width is not None:
            button.setMaximumWidth(max_width)
        button.setMinimumWidth(0)
        button.setMinimumHeight(24)
        button.setMaximumHeight(28)

    def _fit_header_button_width(self, button: QPushButton, min_width: int = 84) -> None:
        """Adapt button width to translated text to avoid clipping in narrow windows."""
        metrics = QFontMetrics(button.font())
        width = metrics.horizontalAdvance(button.text()) + 30
        button.setMinimumWidth(max(min_width, width))
        button.setMaximumWidth(max(min_width, width + 24))

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 8)
        layout.setSpacing(8)

        header_panel = QFrame()
        header_panel.setObjectName("sectionPanel")
        top = QHBoxLayout()
        top.setContentsMargins(12, 8, 12, 8)
        top.setSpacing(8)
        self._title_label = QLabel("WSL Distributions")
        self._title_label.setStyleSheet("font-size: 15px; font-weight: bold;")
        self.distro_count_label.setStyleSheet("color: #888; font-size: 11px;")
        self.btn_refresh = QPushButton("Refresh")
        self._compact_button(self.btn_refresh, 78)
        self.btn_refresh.clicked.connect(self.refresh_requested.emit)
        self.btn_rescan_users = QPushButton("Re-scan User Status")
        self._compact_button(self.btn_rescan_users, 122)
        self.btn_rescan_users.setToolTip(
            "Refresh only the user-status column without waiting for auto-refresh"
        )
        self.btn_rescan_users.clicked.connect(self.rescan_users_requested.emit)
        self._fit_header_button_width(self.btn_rescan_users)
        self._fit_header_button_width(self.btn_refresh, min_width=72)
        top.addWidget(self._title_label)
        top.addWidget(self.distro_count_label)
        top.addStretch()
        top.addWidget(self.btn_rescan_users)
        top.addWidget(self.btn_refresh)
        header_panel.setLayout(top)
        layout.addWidget(header_panel)

        table_card = QFrame()
        table_card.setObjectName("formCard")
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(10, 10, 10, 10)
        table_layout.setSpacing(6)

        cols = ["", "Name the Distro", "State", "WSL", "Default", "User On/Off", "Actions"]
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        first_header = self.table.horizontalHeaderItem(0)
        if first_header is not None:
            first_header.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(40)
        header.setStretchLastSection(False)
        self.table.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.table.setColumnWidth(0, 34)
        self.table.setColumnWidth(2, 124)
        self.table.setColumnWidth(3, 64)
        self.table.setColumnWidth(4, 80)
        self.table.setColumnWidth(5, 138)
        self.table.setColumnWidth(6, 78)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table_layout.addWidget(self.table)
        layout.addWidget(table_card)

        layout.addWidget(self.empty_state)
        self._compact_button(self.retry_button, 120)
        layout.addWidget(self.retry_button, alignment=Qt.AlignmentFlag.AlignCenter)
        self.show_empty_state("", allow_retry=False)
        self.retranslate_ui()

    def show_empty_state(self, text: str, allow_retry: bool = True) -> None:
        has_text = bool(text.strip())
        self.empty_state.setVisible(has_text)
        self.empty_state.setText(text)
        self.retry_button.setVisible(has_text and allow_retry)
        self.table.setVisible(not has_text)

    def retranslate_ui(self) -> None:
        self._title_label.setText(t("WSL Distributions"))
        self.btn_refresh.setText(t("Refresh"))
        self.btn_rescan_users.setText(t("Re-scan User Status"))
        self.btn_rescan_users.setToolTip(
            t("Refresh only the user-status column without waiting for auto-refresh")
        )
        self.retry_button.setText(t("Retry detection"))
        self._fit_header_button_width(self.btn_rescan_users)
        self._fit_header_button_width(self.btn_refresh, min_width=72)
        headers = ["", t("Name the Distro"), t("State"), "WSL", t("Default"), t("User On/Off"), t("Actions")]
        self.table.setHorizontalHeaderLabels(headers)
