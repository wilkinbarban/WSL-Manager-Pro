"""
main.py
=======
Entry point for WSL Manager Pro.

Responsibilities
----------------
1. Ensure the project root is on sys.path so absolute imports work.
2. Detect the current platform (Windows native vs WSL-hosted).
3. Check for administrator / root privileges.
   - Windows: auto-elevate via ShellExecute "runas" if not admin.
   - WSL/Linux: show a warning but allow limited operation.
4. Bootstrap the QApplication with a dark stylesheet (``resources/styles/dark.qss``).
5. Configure rotating file logging (``utils.app_logging.configure_logging``).
6. Launch MainWindow.

Usage
-----
    python main.py
"""
from __future__ import annotations

import importlib.metadata as importlib_metadata
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure project root is importable regardless of working directory
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Privilege helpers
# ---------------------------------------------------------------------------

def _is_admin() -> bool:
    """Return True when the process has Windows Administrator privileges."""
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _elevate_windows() -> None:
    """
    Re-launch the current script with the 'runas' verb so Windows prompts
    for elevation.  The current process then exits immediately.
    """
    import ctypes

    script    = str(Path(sys.argv[0]).resolve())
    args      = " ".join(f'"{a}"' for a in sys.argv[1:])
    params    = f'"{script}" {args}'.strip()

    ctypes.windll.shell32.ShellExecuteW(
        None,             # hwnd
        "runas",          # verb
        sys.executable,   # file
        params,           # parameters
        None,             # directory
        1,                # SW_SHOWNORMAL
    )
    sys.exit(0)


def _relaunch_with_workspace_venv() -> bool:
    """
    Re-run this script with ``.venv/Scripts/python.exe`` when available.

    Returns True when a relaunch was triggered, False otherwise.
    """
    venv_python = ROOT / ".venv" / "Scripts" / "python.exe"
    if not venv_python.exists():
        return False
    try:
        if Path(sys.executable).resolve() == venv_python.resolve():
            return False
    except OSError:
        pass

    result = subprocess.run([
        str(venv_python),
        str(Path(__file__).resolve()),
        *sys.argv[1:],
    ])
    raise SystemExit(result.returncode)


def _resolve_app_icon_path() -> str:
    """Return the best available application icon path."""
    ico_path = _resource_path("assets", "icon.ico")
    if ico_path.exists():
        return str(ico_path)
    png_path = _resource_path("assets", "icon.png")
    if png_path.exists():
        return str(png_path)
    return ""


def _resource_path(*parts: str) -> Path:
    """Resolve bundled resources for source and PyInstaller builds."""
    base_path = getattr(sys, "_MEIPASS", ROOT)
    return Path(base_path, *parts)


def _set_windows_app_id() -> None:
    """Help Windows associate the taskbar button with this app icon."""
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "WSLManagerPro.Desktop"
        )
    except Exception:
        return


# ---------------------------------------------------------------------------
# Dark stylesheet (external file — ROADMAP phase A4)
# ---------------------------------------------------------------------------

_FALLBACK_DARK_QSS = """
QMainWindow, QDialog, QWidget {
    background-color: #1e1e1e;
    color: #d4d4d4;
    font-family: "Segoe UI", "Ubuntu", "Helvetica Neue", sans-serif;
    font-size: 13px;
}
"""


def _load_dark_stylesheet() -> str:
    """Load ``resources/styles/dark.qss`` from the project root."""
    path = _resource_path("resources", "styles", "dark.qss")
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return _FALLBACK_DARK_QSS


def _parse_requirement_name(requirement_line: str) -> str:
    """
    Extract a distribution name from a ``requirements.txt`` line.

    Examples:
      - ``PySide6>=6.6.0`` -> ``PySide6``
      - ``requests[security]==2.31.0`` -> ``requests``
    """
    line = requirement_line.split("#", 1)[0].strip()
    if not line or line.startswith("-"):
        return ""
    line = line.split(";", 1)[0].strip()
    if not line:
        return ""
    name = re.split(r"[<>=!~\s]", line, maxsplit=1)[0].strip()
    return name.split("[", 1)[0].strip()


def _required_python_distributions() -> list[str]:
    """Load runtime Python dependencies from ``requirements.txt``."""
    req_path = ROOT / "requirements.txt"
    if not req_path.exists():
        return []
    names: list[str] = []
    for raw in req_path.read_text(encoding="utf-8").splitlines():
        name = _parse_requirement_name(raw)
        if name:
            names.append(name)
    return names


def _detect_missing_runtime_dependencies() -> list[tuple[str, str]]:
    """
    Return missing runtime dependencies as ``(label, install_command)`` pairs.

    The checks intentionally stay fast and local:
      - Python version
      - required Python distributions from requirements.txt
      - WSL executable availability on Windows
      - npm and node_modules only when package.json exists
    """
    missing: list[tuple[str, str]] = []

    if sys.version_info < (3, 10):
        install_python_cmd = (
            "winget install -e --id Python.Python.3.12 "
            "--accept-source-agreements --accept-package-agreements"
        )
        missing.append((
            "Python 3.10+ is required.",
            install_python_cmd,
        ))

    for dist_name in _required_python_distributions():
        try:
            importlib_metadata.version(dist_name)
        except importlib_metadata.PackageNotFoundError:
            missing.append((
                f"Python package missing: {dist_name}",
                "python -m pip install -r requirements.txt",
            ))

    if os.name == "nt":
        system_root = Path(os.environ.get("SystemRoot", r"C:\\Windows"))
        wsl_candidates = [
            system_root / "System32" / "wsl.exe",
            system_root / "SysNative" / "wsl.exe",
        ]
        has_wsl = any(path.exists() for path in wsl_candidates)
        if not has_wsl and shutil.which("wsl.exe") is not None:
            has_wsl = True
        if not has_wsl:
            missing.append((
                "WSL is not installed or not available in PATH.",
                "wsl --install --no-distribution",
            ))

    package_json = ROOT / "package.json"
    if package_json.exists():
        try:
            payload = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        deps = payload.get("dependencies") or {}
        dev_deps = payload.get("devDependencies") or {}
        has_npm_deps = bool(deps) or bool(dev_deps)
        if has_npm_deps:
            if shutil.which("npm") is None:
                install_node_cmd = (
                    "winget install -e --id OpenJS.NodeJS.LTS "
                    "--accept-source-agreements --accept-package-agreements"
                )
                missing.append((
                    "npm is required by package.json but was not found.",
                    install_node_cmd,
                ))
            elif not (ROOT / "node_modules").exists():
                missing.append((
                    "Node dependencies are not installed (node_modules missing).",
                    "npm install",
                ))

    return missing


def _format_dependency_error_message(missing: list[tuple[str, str]]) -> tuple[str, str]:
    """Build user-facing summary and command list for missing dependencies."""
    lines = [
        "WSL Manager Pro cannot start because required dependencies are missing.",
        "",
        "Missing dependencies:",
    ]
    for label, _cmd in missing:
        lines.append(f"- {label}")

    commands: list[str] = []
    for _label, cmd in missing:
        if cmd not in commands:
            commands.append(cmd)
    if "PowerShell -ExecutionPolicy Bypass -File .\\install.ps1" not in commands:
        commands.insert(0, "PowerShell -ExecutionPolicy Bypass -File .\\install.ps1")

    command_lines = ["Recommended commands:"] + [f"- {cmd}" for cmd in commands]
    return "\n".join(lines), "\n".join(command_lines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Bootstrap and launch the WSL Manager Pro application.

    **Startup sequence (in order):**

    1. **App ID** — Set the Windows taskbar AppUserModelID for proper
       icon grouping.
    2. **PySide6 import** — If PySide6 is missing, attempt to relaunch with
       the workspace ``.venv`` Python interpreter.
    3. **QApplication** — Create the Qt application instance.
    4. **Dependency check** — Detect missing runtime dependencies (Python
       version, required packages, WSL availability).  Show a critical
       error dialog and exit if any are missing.
    5. **Font scaling** — Apply DPI-aware font adjustments based on the
       primary screen's logical DPI.
    6. **Dark stylesheet** — Load ``resources/styles/dark.qss``; fall back
       to a minimal embedded stylesheet if the file is missing.
    7. **App icon** — Resolve the application icon (``.ico`` preferred,
       ``.png`` fallback).
    8. **Logging** — Configure the rotating file logger
       (:func:`~utils.app_logging.configure_logging`).
    9. **Config** — Load or create :class:`~utils.config_manager.ConfigManager`;
       auto-save if schema migration was needed.
    10. **i18n** — Initialise the language manager and sync with the
        persisted language preference.
    11. **Admin elevation** — If not running as administrator and the
        config requests it, prompt the user to relaunch elevated.
        If they decline, disable the ``run_as_admin`` setting.
    12. **MainWindow** — Create and show the main application window.
    13. **Event loop** — Enter the Qt event loop; exit when the window
        closes.

    This function does not return normally — it calls
    :func:`sys.exit` with the Qt return code.
    """
    _set_windows_app_id()
    try:
        from PySide6.QtGui import QFont, QIcon
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ModuleNotFoundError as exc:
        if exc.name == "PySide6" and _relaunch_with_workspace_venv():
            return
        raise

    app = QApplication(sys.argv)
    app.setApplicationName("WSL Manager Pro")
    app.setOrganizationName("WSLManagerPro")
    app.setApplicationVersion("1.0.0")

    missing_deps = _detect_missing_runtime_dependencies()
    if missing_deps:
        summary, commands = _format_dependency_error_message(missing_deps)
        QMessageBox.critical(
            None,
            "Missing Dependencies",
            f"{summary}\n\n{commands}",
        )
        print(summary)
        print()
        print(commands)
        raise SystemExit(1)

    app_font = QFont(app.font())
    # Qt may report pointSize as -1 on some Windows configurations when
    # the system font metrics haven't been fully initialised yet.
    # We defensively provide a sensible default before QApplication
    # distributes the font to child widgets, preventing
    # "QFont::setPointSize: Point size <= 0 (-1)" warnings later.
    pt = app_font.pointSize()
    if pt <= 0:
        if app_font.pixelSize() > 0:
            screen = app.primaryScreen()
            dpi = screen.logicalDotsPerInch() if screen is not None else 96.0
            inferred_pt = max(1, int(round(app_font.pixelSize() * 72.0 / max(1.0, dpi))))
            app_font.setPointSize(inferred_pt)
        else:
            app_font.setPointSize(10)
        app.setFont(app_font)
    app.setStyleSheet(_load_dark_stylesheet())
    icon_path = _resolve_app_icon_path()
    if icon_path:
        app.setWindowIcon(QIcon(icon_path))

    from utils.app_logging import configure_logging
    from utils.config_manager import ConfigManager
    from utils.i18n import get_i18n, t

    configure_logging()
    config_mgr = ConfigManager()
    i18n = get_i18n()
    i18n.set_language(config_mgr.config.language)

    is_admin = _is_admin()
    run_as_admin = config_mgr.config.run_as_admin

    if not is_admin and run_as_admin:
        reply = QMessageBox.question(
            None,
            t("Run WSL Manager Pro as administrator?"),
            (
                t("Administrator mode is recommended for install, winget, and system changes.\n\n"
                  "Choose Yes to relaunch elevated.\n"
                  "Choose No to continue in limited read-only mode.")
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply == QMessageBox.StandardButton.Yes:
            _elevate_windows()
            return
        config_mgr.config.run_as_admin = False
        config_mgr.save()

    from ui.main_window import MainWindow

    window = MainWindow(is_admin=is_admin)
    if icon_path:
        window.setWindowIcon(QIcon(icon_path))
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
