"""
ui/tabs/manage_tab.py
=====================

Manage tab providing import/export controls and quick-action buttons for
WSL distribution management.

The layout is split into two columns:
* **Left (stretch)** — Import from tar and Export to tar sections.
* **Right (fixed width)** — Quick Actions panel with a distro selector
  combo box and action buttons (Set Default, Terminate, Shutdown All,
  Open Shell, Full System Update, winget Install, Repair buttons,
  Unregister, Deep Clean).

Public attributes (widgets) mirror the former ``MainWindow`` naming
convention so the main window can wire ``clicked`` handlers directly
without changes throughout ``main_window.py``.

Exposed widgets (for MainWindow wiring)
---------------------------------------
**Import section:**
* ``import_tar_edit``, ``btn_browse_tar`` — Tar file path.
* ``import_name_edit`` — WSL registration name.
* ``import_dir_edit``, ``btn_browse_import_dir`` — Install directory.
* ``btn_import`` — Trigger import.

**Export section:**
* ``export_combo`` — Distro selector.
* ``export_path_edit``, ``btn_browse_export`` — Save path.
* ``btn_export`` — Trigger export.

**Quick Actions:**
* ``action_combo`` — Target distro selector.
* ``btn_set_default``, ``btn_terminate``, ``btn_shutdown``,
  ``btn_open_user_shell``, ``btn_open_root_shell``, ``btn_full_update``,
  ``btn_install_winget``, ``btn_repair_oracle``, ``btn_repair_suse``,
  ``btn_unregister``, ``btn_deep_clean``.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from utils.config_manager import ConfigManager
from utils.i18n import get_i18n, t


class ManageTab(QWidget):
    """Import/export controls and quick-action buttons for distro management.

    All interactive widgets are exposed as public attributes so
    :class:`~ui.main_window.MainWindow` can connect signals and read/write
    values directly during the wiring phase (``_wire_manage_tab``).
    """

    def __init__(self, config_mgr: ConfigManager, parent=None) -> None:
        super().__init__(parent)
        self._config_mgr = config_mgr
        self._section_titles: dict[str, QLabel] = {}
        self._build_ui()
        get_i18n().language_changed.connect(lambda _lang: self.retranslate_ui())

    def _compact_button(self, button: QPushButton, max_width: int | None = None) -> None:
        button.setObjectName("compactButton")
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.setMinimumHeight(26)
        button.setMaximumHeight(28)
        if max_width is not None:
            button.setMaximumWidth(max_width)

    def _make_section_card(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("formCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        label = QLabel(title)
        label.setObjectName("sectionTitle")
        self._section_titles[title] = label
        layout.addWidget(label)
        return card, layout

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        self.ie_group = QGroupBox("Import / Export")
        ie_layout = QVBoxLayout(self.ie_group)
        ie_layout.setContentsMargins(14, 14, 14, 14)
        ie_layout.setSpacing(10)

        import_card, import_layout = self._make_section_card("Import")
        self.lbl_import_rootfs = QLabel("Import rootfs archive:")
        import_layout.addWidget(self.lbl_import_rootfs)
        import_row = QHBoxLayout()
        import_row.setSpacing(8)
        self.import_tar_edit = QLineEdit()
        self.btn_browse_tar = QPushButton("Browse...")
        self._compact_button(self.btn_browse_tar, 86)
        import_row.addWidget(self.import_tar_edit)
        import_row.addWidget(self.btn_browse_tar)
        import_layout.addLayout(import_row)

        self.lbl_import_name = QLabel("WSL name for import:")
        import_layout.addWidget(self.lbl_import_name)
        self.import_name_edit = QLineEdit()
        import_layout.addWidget(self.import_name_edit)

        self.lbl_install_dir = QLabel("Install directory:")
        import_layout.addWidget(self.lbl_install_dir)
        import_dir_row = QHBoxLayout()
        import_dir_row.setSpacing(8)
        self.import_dir_edit = QLineEdit(self._config_mgr.config.install_dir)
        self.btn_browse_import_dir = QPushButton("Browse...")
        self._compact_button(self.btn_browse_import_dir, 86)
        import_dir_row.addWidget(self.import_dir_edit)
        import_dir_row.addWidget(self.btn_browse_import_dir)
        import_layout.addLayout(import_dir_row)

        self.btn_import = QPushButton("Import Distribution")
        self._compact_button(self.btn_import, 190)
        import_layout.addWidget(self.btn_import, alignment=Qt.AlignmentFlag.AlignRight)

        export_card, export_layout = self._make_section_card("Export")
        self.lbl_export_distro = QLabel("Export distribution:")
        export_layout.addWidget(self.lbl_export_distro)
        self.export_combo = QComboBox()
        export_layout.addWidget(self.export_combo)

        self.lbl_save_as = QLabel("Save as:")
        export_layout.addWidget(self.lbl_save_as)
        export_path_row = QHBoxLayout()
        export_path_row.setSpacing(8)
        self.export_path_edit = QLineEdit()
        self.btn_browse_export = QPushButton("Browse...")
        self._compact_button(self.btn_browse_export, 86)
        export_path_row.addWidget(self.export_path_edit)
        export_path_row.addWidget(self.btn_browse_export)
        export_layout.addLayout(export_path_row)

        self.btn_export = QPushButton("Export Distribution")
        self._compact_button(self.btn_export, 190)
        export_layout.addWidget(self.btn_export, alignment=Qt.AlignmentFlag.AlignRight)

        ie_layout.addWidget(import_card)
        ie_layout.addWidget(export_card)

        self.qa_group = QGroupBox("Quick Actions")
        qa_layout = QVBoxLayout(self.qa_group)
        qa_layout.setContentsMargins(14, 14, 14, 14)
        qa_layout.setSpacing(10)
        quick_card_width = 350

        target_card, target_layout = self._make_section_card("Target")
        target_card.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        target_card.setMinimumWidth(quick_card_width)
        target_card.setMaximumWidth(quick_card_width)
        self.lbl_target_distro = QLabel("Target distribution:")
        target_layout.addWidget(self.lbl_target_distro)
        target_row = QHBoxLayout()
        target_row.setSpacing(8)
        self.action_combo = QComboBox()
        self.action_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.action_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.action_combo.setMinimumContentsLength(1)
        target_row.addWidget(self.action_combo)
        target_row.addStretch()
        target_layout.addLayout(target_row)
        target_wrap = QHBoxLayout()
        target_wrap.setContentsMargins(0, 0, 0, 0)
        target_wrap.setSpacing(0)
        target_wrap.addWidget(target_card, 0, Qt.AlignmentFlag.AlignLeft)
        target_wrap.addStretch()
        qa_layout.addLayout(target_wrap)

        actions_card, actions_card_layout = self._make_section_card("Actions")
        actions_card.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        actions_card.setMinimumWidth(quick_card_width)
        actions_card.setMaximumWidth(quick_card_width)
        actions_grid = QGridLayout()
        actions_grid.setHorizontalSpacing(8)
        actions_grid.setVerticalSpacing(8)

        self.btn_set_default = QPushButton("Set as Default")
        self._compact_button(self.btn_set_default)
        actions_grid.addWidget(self.btn_set_default, 0, 0)

        self.btn_terminate = QPushButton("Terminate")
        self._compact_button(self.btn_terminate)
        actions_grid.addWidget(self.btn_terminate, 1, 0)

        self.btn_shutdown = QPushButton("Shutdown All")
        self._compact_button(self.btn_shutdown)
        actions_grid.addWidget(self.btn_shutdown, 2, 0)

        self.btn_open_user_shell = QPushButton("Open Shell (user)")
        self._compact_button(self.btn_open_user_shell)
        actions_grid.addWidget(self.btn_open_user_shell, 3, 0)

        self.btn_open_root_shell = QPushButton("Open Shell (root)")
        self._compact_button(self.btn_open_root_shell)
        actions_grid.addWidget(self.btn_open_root_shell, 4, 0)

        self.btn_full_update = QPushButton("Full System Update")
        self._compact_button(self.btn_full_update)
        actions_grid.addWidget(self.btn_full_update, 5, 0)

        self.btn_install_winget = QPushButton("Install via winget")
        self._compact_button(self.btn_install_winget)
        actions_grid.addWidget(self.btn_install_winget, 6, 0)

        self.btn_repair_oracle = QPushButton("Repair Oracle Existing")
        self._compact_button(self.btn_repair_oracle)
        self.btn_repair_oracle.setVisible(False)
        actions_grid.addWidget(self.btn_repair_oracle, 7, 0)

        self.btn_repair_suse = QPushButton("Repair SLE 15 SP6 Image")
        self._compact_button(self.btn_repair_suse)
        self.btn_repair_suse.setVisible(False)
        actions_grid.addWidget(self.btn_repair_suse, 8, 0)

        self.btn_unregister = QPushButton("Unregister (Delete)")
        self.btn_unregister.setObjectName("dangerButton")
        self.btn_unregister.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_unregister.setMinimumHeight(26)
        self.btn_unregister.setMaximumHeight(28)
        actions_grid.addWidget(self.btn_unregister, 9, 0)

        self.btn_deep_clean = QPushButton("Deep Clean WSL / Cache")
        self._compact_button(self.btn_deep_clean)
        actions_grid.addWidget(self.btn_deep_clean, 10, 0)
        actions_grid.setColumnStretch(0, 1)
        actions_card_layout.addLayout(actions_grid)
        actions_wrap = QHBoxLayout()
        actions_wrap.setContentsMargins(0, 0, 0, 0)
        actions_wrap.setSpacing(0)
        actions_wrap.addWidget(actions_card, 0, Qt.AlignmentFlag.AlignLeft)
        actions_wrap.addStretch()
        qa_layout.addLayout(actions_wrap)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(4)
        split.addWidget(self.ie_group)
        split.addWidget(self.qa_group)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 1)
        split.setSizes([860, 420])
        layout.addWidget(split)
        layout.addStretch()

        scroll.setWidget(content)
        root_layout.addWidget(scroll)
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        for key, label in self._section_titles.items():
            label.setText(t(key))
        self.ie_group.setTitle(t("Import / Export"))
        self.qa_group.setTitle(t("Quick Actions"))
        self.lbl_import_rootfs.setText(t("Import rootfs archive:"))
        self.import_tar_edit.setPlaceholderText(t("Path to .tar / .tar.gz"))
        self.btn_browse_tar.setText(t("Browse..."))
        self.lbl_import_name.setText(t("WSL name for import:"))
        self.import_name_edit.setPlaceholderText(t("e.g. MyUbuntu"))
        self.lbl_install_dir.setText(t("Install directory:"))
        self.btn_browse_import_dir.setText(t("Browse..."))
        self.btn_import.setText(t("Import Distribution"))
        self.lbl_export_distro.setText(t("Export distribution:"))
        self.lbl_save_as.setText(t("Save as:"))
        self.export_path_edit.setPlaceholderText(t("e.g. C:\\Backup\\ubuntu.tar"))
        self.btn_browse_export.setText(t("Browse..."))
        self.btn_export.setText(t("Export Distribution"))
        self.lbl_target_distro.setText(t("Target distribution:"))
        self.btn_set_default.setText(t("Set as Default"))
        self.btn_terminate.setText(t("Terminate"))
        self.btn_shutdown.setText(t("Shutdown All"))
        self.btn_open_user_shell.setText(t("Open Shell (user)"))
        self.btn_open_root_shell.setText(t("Open Shell (root)"))
        self.btn_full_update.setText(t("Full System Update"))
        self.btn_full_update.setToolTip(t("Run distro-wide package update/upgrade"))
        self.btn_install_winget.setText(t("Install via winget"))
        self.btn_install_winget.setToolTip(
            t("Install the selected catalog distro through winget when supported")
        )
        self.btn_repair_oracle.setText(t("Repair Oracle Existing"))
        self.btn_repair_oracle.setToolTip(
            t("Export current Oracle distro, unregister it, and import it into the configured install directory.")
        )
        self.btn_repair_suse.setText(t("Repair SLE 15 SP6 Image"))
        self.btn_repair_suse.setToolTip(
            t("Export current SUSE-Linux-Enterprise-15-SP6 distro, unregister it, and import it into the configured install directory.")
        )
        self.btn_unregister.setText(t("Unregister (Delete)"))
        self.btn_deep_clean.setText(t("Deep Clean WSL / Cache"))
        self.btn_deep_clean.setToolTip(
            t("Shut down WSL, remove cache/log/temp files, and prune stale manager records")
        )
