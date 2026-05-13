"""
ui/tabs/settings_tab.py
========================

Settings tab providing configuration for default directories, startup
options, WSL 2 resource limits (``.wslconfig``), and diagnostic export.

The layout is split into two columns:
* **Left (stretch)** — Default Directories (install dir, download dir,
  remote catalog URL) and Startup options (run as admin, check for updates,
  update repo URL).
* **Right (fixed width)** — WSL 2 Resource Limits (memory, swap, processors,
  localhost forwarding, VM idle timeout) with an advanced options toggle.

A footer section provides Save and diagnostic export controls.

Exposed widgets (for MainWindow wiring)
---------------------------------------
**Paths:** ``cfg_install_edit``, ``btn_browse_install``, ``cfg_dl_edit``,
``btn_browse_download``, ``remote_catalog_url_edit``.

**Startup:** ``run_as_admin_check``, ``check_for_updates_check``,
``update_repo_url_edit``.

**WSL2 Limits:** ``mem_spin``, ``swap_spin``, ``cpu_spin``,
``localhost_forwarding_check``, ``vm_idle_timeout_spin``,
``advanced_toggle``, ``advanced_container``, ``btn_apply_wslconfig``.

**Diagnostics:** ``diagnostic_tail_spin``, ``btn_export_diagnostics``.

**Footer:** ``btn_save``.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from utils.config_manager import ConfigManager
from utils.i18n import get_i18n, t


class SettingsTab(QWidget):
    """Configuration form for default paths, startup options, and WSL 2 limits.

    All interactive widgets are public so :class:`~ui.main_window.MainWindow`
    can read/write values during save and wire browse buttons to directory
    pickers.
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

        self.dir_group = QGroupBox("Default Directories")
        dir_form = QVBoxLayout(self.dir_group)
        dir_form.setContentsMargins(14, 14, 14, 14)
        dir_form.setSpacing(10)

        paths_card, paths_layout = self._make_section_card("Paths")
        self.lbl_install_dir = QLabel("WSL installation directory:")
        paths_layout.addWidget(self.lbl_install_dir)
        install_row = QHBoxLayout()
        install_row.setSpacing(8)
        self.cfg_install_edit = QLineEdit(self._config_mgr.config.install_dir)
        self.btn_browse_install = QPushButton("Browse...")
        self._compact_button(self.btn_browse_install, 86)
        install_row.addWidget(self.cfg_install_edit)
        install_row.addWidget(self.btn_browse_install)
        paths_layout.addLayout(install_row)

        self.lbl_download_dir = QLabel("Download cache directory:")
        paths_layout.addWidget(self.lbl_download_dir)
        dl_row = QHBoxLayout()
        dl_row.setSpacing(8)
        self.cfg_dl_edit = QLineEdit(self._config_mgr.config.download_dir)
        self.btn_browse_download = QPushButton("Browse...")
        self._compact_button(self.btn_browse_download, 86)
        dl_row.addWidget(self.cfg_dl_edit)
        dl_row.addWidget(self.btn_browse_download)
        paths_layout.addLayout(dl_row)

        self.lbl_remote_catalog = QLabel("Remote distro catalog URL (optional):")
        paths_layout.addWidget(self.lbl_remote_catalog)
        self.remote_catalog_url_edit = QLineEdit(self._config_mgr.config.remote_catalog_url)
        paths_layout.addWidget(self.remote_catalog_url_edit)

        startup_card, startup_layout = self._make_section_card("Startup")
        self.run_as_admin_check = QCheckBox("Run with administrator privileges when possible")
        self.run_as_admin_check.setChecked(self._config_mgr.config.run_as_admin)
        startup_layout.addWidget(self.run_as_admin_check)

        self.check_for_updates_check = QCheckBox("Check for updates on startup (optional)")
        self.check_for_updates_check.setChecked(self._config_mgr.config.check_for_updates)
        startup_layout.addWidget(self.check_for_updates_check)

        self.lbl_update_repo = QLabel("GitHub repository URL for updates (optional):")
        startup_layout.addWidget(self.lbl_update_repo)
        self.update_repo_url_edit = QLineEdit(self._config_mgr.config.update_repo_url)
        startup_layout.addWidget(self.update_repo_url_edit)

        dir_form.addWidget(paths_card)
        dir_form.addWidget(startup_card)

        self.wsl_group = QGroupBox("WSL2 Resource Limits  (.wslconfig)")
        wsl_form = QVBoxLayout(self.wsl_group)
        wsl_form.setContentsMargins(14, 14, 14, 14)
        wsl_form.setSpacing(10)
        wsl_form.setAlignment(Qt.AlignmentFlag.AlignTop)

        limits_card, limits_layout = self._make_section_card("Limits")
        limits_card.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        mem_row = QHBoxLayout()
        self.lbl_memory = QLabel("Memory:")
        mem_row.addWidget(self.lbl_memory)
        self.mem_spin = QSpinBox()
        self.mem_spin.setRange(1, 256)
        self.mem_spin.setSuffix(" GB")
        self.mem_spin.setValue(self._config_mgr.config.memory_limit_gb)
        self.mem_spin.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.mem_spin.setMaximumWidth(98)
        mem_row.addWidget(self.mem_spin)
        mem_row.addStretch()
        limits_layout.addLayout(mem_row)

        swap_row = QHBoxLayout()
        self.lbl_swap = QLabel("Swap:")
        swap_row.addWidget(self.lbl_swap)
        self.swap_spin = QSpinBox()
        self.swap_spin.setRange(0, 128)
        self.swap_spin.setSuffix(" GB")
        self.swap_spin.setValue(self._config_mgr.config.swap_size_gb)
        self.swap_spin.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.swap_spin.setMaximumWidth(98)
        swap_row.addWidget(self.swap_spin)
        swap_row.addStretch()
        limits_layout.addLayout(swap_row)

        cpu_row = QHBoxLayout()
        self.lbl_processors = QLabel("Processors:")
        cpu_row.addWidget(self.lbl_processors)
        self.cpu_spin = QSpinBox()
        self.cpu_spin.setRange(1, 256)
        self.cpu_spin.setSuffix(" core(s)")
        self.cpu_spin.setValue(self._config_mgr.config.processors)
        self.cpu_spin.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.cpu_spin.setMaximumWidth(98)
        cpu_row.addWidget(self.cpu_spin)
        cpu_row.addStretch()
        limits_layout.addLayout(cpu_row)

        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setChecked(False)
        limits_layout.addWidget(self.advanced_toggle)

        self.advanced_container = QWidget()
        advanced_layout = QVBoxLayout(self.advanced_container)
        advanced_layout.setContentsMargins(8, 6, 8, 0)
        advanced_layout.setSpacing(8)

        self.localhost_forwarding_check = QCheckBox("Enable localhostForwarding")
        self.localhost_forwarding_check.setChecked(self._config_mgr.config.localhost_forwarding)
        advanced_layout.addWidget(self.localhost_forwarding_check)

        timeout_row = QHBoxLayout()
        self.lbl_vm_idle = QLabel("vmIdleTimeout:")
        timeout_row.addWidget(self.lbl_vm_idle)
        self.vm_idle_timeout_spin = QSpinBox()
        self.vm_idle_timeout_spin.setRange(1, 1440)
        self.vm_idle_timeout_spin.setSuffix(" s")
        self.vm_idle_timeout_spin.setValue(self._config_mgr.config.vm_idle_timeout_sec)
        self.vm_idle_timeout_spin.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.vm_idle_timeout_spin.setMaximumWidth(98)
        timeout_row.addWidget(self.vm_idle_timeout_spin)
        timeout_row.addStretch()
        advanced_layout.addLayout(timeout_row)

        self.advanced_container.setVisible(False)
        self.advanced_toggle.toggled.connect(self.advanced_container.setVisible)
        limits_layout.addWidget(self.advanced_container)

        self.btn_apply_wslconfig = QPushButton("Apply & Write .wslconfig")
        self._compact_button(self.btn_apply_wslconfig, 190)
        limits_layout.addWidget(self.btn_apply_wslconfig, alignment=Qt.AlignmentFlag.AlignRight)
        limits_wrap = QHBoxLayout()
        limits_wrap.setContentsMargins(0, 0, 0, 0)
        limits_wrap.setSpacing(0)
        limits_wrap.addWidget(
            limits_card,
            0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
        )
        limits_wrap.addStretch()
        wsl_form.addLayout(limits_wrap)
        wsl_form.addStretch(1)
        top_split = QSplitter(Qt.Orientation.Horizontal)
        top_split.setChildrenCollapsible(False)
        top_split.setHandleWidth(4)
        top_split.addWidget(self.dir_group)
        top_split.addWidget(self.wsl_group)
        top_split.setStretchFactor(0, 4)
        top_split.setStretchFactor(1, 1)
        top_split.setSizes([900, 380])
        layout.addWidget(top_split)

        self.diag_group = QGroupBox("Diagnostics & support")
        diag_form = QVBoxLayout(self.diag_group)
        diag_form.setContentsMargins(14, 14, 14, 14)
        diag_form.setSpacing(10)

        support_card, support_layout = self._make_section_card("Support")
        self.diag_description = QLabel(
            "Export a ZIP with app version, last log lines, and wsl --version / "
            "--status (see README.txt inside the archive)."
        )
        self.diag_description.setWordWrap(True)
        support_layout.addWidget(self.diag_description)

        tail_row = QHBoxLayout()
        self.lbl_log_tail = QLabel("Log tail lines:")
        tail_row.addWidget(self.lbl_log_tail)
        self.diagnostic_tail_spin = QSpinBox()
        self.diagnostic_tail_spin.setRange(50, 5000)
        self.diagnostic_tail_spin.setSingleStep(50)
        self.diagnostic_tail_spin.setValue(self._config_mgr.config.diagnostic_log_tail_lines)
        tail_row.addWidget(self.diagnostic_tail_spin)
        tail_row.addStretch()
        support_layout.addLayout(tail_row)

        self.btn_export_diagnostics = QPushButton("Export diagnostic bundle...")
        self._compact_button(self.btn_export_diagnostics, 190)
        support_layout.addWidget(self.btn_export_diagnostics, alignment=Qt.AlignmentFlag.AlignRight)
        diag_form.addWidget(support_card)
        layout.addWidget(self.diag_group)

        footer = QHBoxLayout()
        footer.addStretch()
        self.btn_save = QPushButton("Save Settings")
        self._compact_button(self.btn_save, 150)
        footer.addWidget(self.btn_save)
        layout.addLayout(footer)
        layout.addStretch()

        scroll.setWidget(content)
        root_layout.addWidget(scroll)
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        for key, label in self._section_titles.items():
            label.setText(t(key))
        self.dir_group.setTitle(t("Default Directories"))
        self.lbl_install_dir.setText(t("WSL installation directory:"))
        self.btn_browse_install.setText(t("Browse..."))
        self.lbl_download_dir.setText(t("Download cache directory:"))
        self.btn_browse_download.setText(t("Browse..."))
        self.lbl_remote_catalog.setText(t("Remote distro catalog URL (optional):"))
        self.remote_catalog_url_edit.setPlaceholderText("https://example.com/distros.json")
        self.remote_catalog_url_edit.setToolTip(
            t("Optional remote distros.json source. Loaded without signature verification in this phase.")
        )
        self.run_as_admin_check.setText(t("Run with administrator privileges when possible"))
        self.check_for_updates_check.setText(t("Check for updates on startup (optional)"))
        self.lbl_update_repo.setText(t("GitHub repository URL for updates (optional):"))
        self.update_repo_url_edit.setPlaceholderText(
            "https://github.com/wilkinbarban/WSL-Manager-Pro/releases"
        )
        self.wsl_group.setTitle(t("WSL2 Resource Limits  (.wslconfig)"))
        self.lbl_memory.setText(t("Memory:"))
        self.lbl_swap.setText(t("Swap:"))
        self.lbl_processors.setText(t("Processors:"))
        self.advanced_toggle.setText(t("Advanced"))
        self.advanced_toggle.setToolTip(
            t("Shows extra .wslconfig fields. This app overwrites the full file after preview.")
        )
        self.localhost_forwarding_check.setText(t("Enable localhostForwarding"))
        self.localhost_forwarding_check.setToolTip(
            t("Forwards localhost ports between Windows and WSL.")
        )
        self.lbl_vm_idle.setText(t("vmIdleTimeout:"))
        self.vm_idle_timeout_spin.setToolTip(t("Time before the WSL VM can idle out."))
        self.btn_apply_wslconfig.setText(t("Apply & Write .wslconfig"))
        self.diag_group.setTitle(t("Diagnostics & support"))
        self.diag_description.setText(
            t(
                "Export a ZIP with app version, last log lines, and wsl --version / "
                "--status (see README.txt inside the archive)."
            )
        )
        self.lbl_log_tail.setText(t("Log tail lines:"))
        self.btn_export_diagnostics.setText(t("Export diagnostic bundle..."))
        self.btn_save.setText(t("Save Settings"))
