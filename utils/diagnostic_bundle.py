"""
utils/diagnostic_bundle.py
===========================

Build a ZIP diagnostic bundle for troubleshooting (ROADMAP C2).

The bundle is designed to be self-contained and safe to share — it contains
**no secrets by design**:

* Only the last *N* lines of the in-app log console are captured
  (configurable; default 200).
* WSL commands run via a caller-supplied *wsl_run* callback so the bundle
  builder has no direct subprocess access.
* The ``README.txt`` inside the ZIP explains what each file is and includes
  a privacy note about manually reviewing log content before sharing.

Bundle contents
---------------
* ``README.txt`` — Generation timestamp, app version, command status notes,
  privacy disclaimer.
* ``log_tail.txt`` — Last *N* lines of the in-memory log console.
* ``wsl_version.txt`` — Output of ``wsl --version``.
* ``wsl_status.txt`` — Output of ``wsl --status``.

If WSL is unavailable, the ``README.txt`` notes the error and the
corresponding ``*.txt`` files are empty or contain error information.

Type aliases
------------
.. py:data:: WslRun
    :type: Callable[[list[str]], tuple[int, str, str]]

    Callback signature for running ``wsl.exe`` meta-commands.  Receives a
    list of arguments (without the ``wsl.exe`` prefix) and returns a tuple
    of ``(returncode, stdout, stderr)``.
"""

from __future__ import annotations

import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

#: Callback type for executing ``wsl.exe`` meta-commands.
#: Parameters: ``args: list[str]`` — arguments to pass after ``wsl``.
#: Returns: ``(returncode: int, stdout: str, stderr: str)``.
WslRun = Callable[[list[str]], tuple[int, str, str]]


def tail_plain_text(text: str, max_lines: int) -> str:
    """Return at most the last *max_lines* lines of *text*.

    If *text* has fewer than *max_lines* lines, it is returned unchanged.

    Args:
        text: Multi-line string.
        max_lines: Maximum number of trailing lines to keep.

    Returns:
        The tail of *text* as a single string.
    """
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    return "\n".join(lines[-max_lines:])


def _run_wsl(wsl_run: Optional[WslRun], args: list[str]) -> tuple[str, str]:
    """Execute a ``wsl.exe`` meta-command via the caller-supplied callback.

    Args:
        wsl_run: The WSL run callback, or ``None`` if WSL is unavailable.
        args: Arguments to pass after ``wsl`` (e.g. ``["--version"]``).

    Returns:
        A tuple of ``(combined_output, error_note)``:
        * *combined_output* — stdout + stderr joined, or ``""`` on failure.
        * *error_note* — Empty string on success, or a description of what
          went wrong (included in the bundle's ``README.txt``).
    """
    if wsl_run is None:
        return "", "WSL engine not available (wsl.exe missing or not initialized)."
    try:
        rc, out, err = wsl_run(args)
        parts = []
        if (out or "").strip():
            parts.append(out.strip())
        if (err or "").strip():
            parts.append(f"[stderr]\n{err.strip()}")
        body = "\n\n".join(parts) if parts else "(no output)"
        if rc != 0:
            return body, f"non-zero exit code {rc}"
        return body, ""
    except Exception as exc:  # noqa: BLE001 — bundle must always be creatable
        return "", f"{type(exc).__name__}: {exc}"


def write_diagnostic_zip(
    zip_path: Path,
    *,
    app_version: str,
    log_plain: str,
    log_tail_lines: int,
    wsl_run: Optional[WslRun],
) -> None:
    """Write a diagnostic ZIP to *zip_path*.

    Collects the following and packages them into a ZIP archive:

    * ``README.txt`` — Metadata, privacy note, WSL command status.
    * ``log_tail.txt`` — Last *log_tail_lines* lines of the log console.
    * ``wsl_version.txt`` — ``wsl --version`` output.
    * ``wsl_status.txt`` — ``wsl --status`` output.

    WSL commands that fail are noted in ``README.txt``; the corresponding
    text files may contain partial error output rather than valid results.

    Args:
        zip_path: Destination path for the ``.zip`` file.  Parent directory
            is created if it does not exist.
        app_version: Application version string (e.g. ``"1.0.0"``).
        log_plain: Full text of the in-memory log console.
        log_tail_lines: Number of trailing log lines to include.
        wsl_run: Callback for executing ``wsl.exe`` commands, or ``None``
            if WSL is unavailable.
    """
    zip_path = Path(zip_path)
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    # Collect WSL diagnostic output
    ver_body, ver_err = _run_wsl(wsl_run, ["--version"])
    st_body, st_err = _run_wsl(wsl_run, ["--status"])

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    readme: list[str] = [
        "WSL Manager Pro — diagnostic bundle",
        f"Generated (UTC): {now_utc}",
        f"App version: {app_version}",
        "",
        "Files:",
        "  log_tail.txt    — last N lines of the in-app log console",
        "  wsl_version.txt — wsl --version",
        "  wsl_status.txt  — wsl --status",
        "",
        "Privacy:",
        "  The app does not log passwords in normal operation. If you pasted",
        "  secrets into the console, remove them before sharing this ZIP.",
        "",
        "Command notes:",
    ]
    if ver_err:
        readme.append(f"  wsl --version: {ver_err}")
    else:
        readme.append("  wsl --version: OK")
    if st_err:
        readme.append(f"  wsl --status: {st_err}")
    else:
        readme.append("  wsl --status: OK")

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.txt", "\n".join(readme) + "\n")
        zf.writestr("log_tail.txt", tail_plain_text(log_plain, log_tail_lines) + "\n")
        zf.writestr("wsl_version.txt", ver_body + "\n")
        zf.writestr("wsl_status.txt", st_body + "\n")
