"""
ui
==

User interface package for WSL Manager Pro.

Contains the PySide6 (Qt 6) graphical interface components:

* **main_window** — :class:`MainWindow` (QMainWindow) orchestrating all tabs,
  workers, toolbar, status bar, and log console.
* **dialogs** — Modal dialogs: :class:`InstallWizard` (5-page guided install),
  :class:`UserCreationDialog`, :class:`DirectoryDialog`,
  :class:`SwapConfigDialog`.
* **icons** — Lazily-built :class:`~PySide6.QtGui.QIcon` factory for distro
  status indicators.
* **theme** — Centralised colour constants for UI and log styling.
* **tabs/** — Three tab widgets: :class:`DashboardTab` (distro list table),
  :class:`ManageTab` (import/export/actions), :class:`SettingsTab`
  (configuration).
"""
