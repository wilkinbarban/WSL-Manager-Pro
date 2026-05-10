"""
ui/tabs
=======

Tab widget package extracted from :class:`~ui.main_window.MainWindow`
(ROADMAP phase A — UI modularisation).

Each tab is a self-contained :class:`~PySide6.QtWidgets.QWidget` that
communicates with the main window through Qt signals rather than direct
method calls, keeping the tabs decoupled from the application orchestrator.

Tab widgets
-----------
* :class:`DashboardTab` — Live WSL distro status table with refresh and
  user-probing controls.
* :class:`ManageTab` — Import/export, quick actions (set default, terminate,
  shell, update, cleanup), and winget install.
* :class:`SettingsTab` — Configuration for paths, startup options,
  WSL 2 resource limits, and diagnostic export.
"""
from __future__ import annotations

from .dashboard_tab import DashboardTab
from .manage_tab import ManageTab
from .settings_tab import SettingsTab

__all__ = ["DashboardTab", "ManageTab", "SettingsTab"]
