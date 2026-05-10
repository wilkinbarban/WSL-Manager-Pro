"""
core/wsl_list_parser.py
=======================

Pure functions that parse the text output of ``wsl --list --verbose --all``
and ``wsl --list --online`` **without spawning subprocesses or calling
wsl.exe**.  This separation of "parse" and "execute" makes the parsers:

* Unit-testable on any operating system (no Windows/WSL dependency).
* Safe from timeouts, subprocess errors, and locale issues.
* Easy to evolve independently of the command-line interface.

Used by :class:`~core.wsl_engine.WslEngine` to convert raw stdout into
structured data (:class:`~core.wsl_engine.DistroInfo` and
:class:`~core.wsl_engine.OnlineDistro`).

Reference
---------
* ROADMAP phase B3: "Extract pure parser from WslEngine" — completed.
* ROADMAP phase H1:  "Evaluate QProcess → subprocess" — motivated by this
  separation.

Supported locales
-----------------
The header row of ``wsl --list --verbose`` is localized by Windows.  The
parser recognises headers in **English**, **Spanish**, and **Portuguese**
to avoid false-positive distro matches.
"""

from __future__ import annotations

import re
from typing import Optional


def parse_wsl_list_verbose(stdout: str) -> list[tuple[str, str, int, bool]]:
    """Parse the decoded output of ``wsl --list --verbose --all``.

    The expected input format (English example)::

        \ufeff  NAME            STATE           VERSION
        * Ubuntu-24.04    Running         2
          Debian          Stopped         1

    The optional UTF-16 LE BOM (``\\ufeff``) is handled transparently.
    The ``*`` prefix on a row marks the **default** distribution.

    Rows that look like header lines (containing "name", "state", "version"
    or their localised equivalents) are skipped.  Informational messages
    such as "Windows Subsystem for Linux has no installed distributions."
    are also ignored because they do not match the data-row regex.

    Args:
        stdout: Decoded text from ``wsl.exe --list --verbose --all``.
            May contain ``\\r\\n`` or ``\\n`` line endings.

    Returns:
        A list of ``(name, state, version, is_default)`` tuples:
        * ``name`` — Distro name (``str``), e.g. ``"Ubuntu-24.04"``.
        * ``state`` — ``"Running"``, ``"Stopped"``, or localised equivalent.
        * ``version`` — WSL version (``int``), 1 or 2.
        * ``is_default`` — ``True`` if this distro is the default.
    """
    distros: list[tuple[str, str, int, bool]] = []

    # Row regex: optional '*', name (lazy, stops before 2+ spaces),
    # state (lazy, stops before 2+ spaces), version (digits only).
    # This is intentionally tolerant of varying column widths.
    row_re = re.compile(r"^\*?\s*(.+?)\s{2,}(.+?)\s{2,}(\d+)\s*$")

    for raw_line in stdout.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue  # skip blank lines

        # --- Skip localised header rows ---
        # English:  NAME   STATE   VERSION
        # Spanish:  NOMBRE ESTADO  VERSIÓN
        # Portuguese: NOME  ESTADO  VERSÃO
        lowered = stripped.casefold()
        if (
            ("name" in lowered and "state" in lowered and "version" in lowered)
            or ("nombre" in lowered and "estado" in lowered and "versi" in lowered)
            or ("nome" in lowered and "estado" in lowered and "vers" in lowered)
        ):
            continue

        # --- Attempt data-row match ---
        m = row_re.match(stripped)
        if not m:
            continue  # informational line, separator, etc.

        # Detect default marker: '*' at the very start (after optional BOM)
        is_default = raw_line.lstrip("\ufeff").startswith("*")
        name = m.group(1).strip()
        state = m.group(2).strip()
        version = int(m.group(3))

        if name:
            distros.append((name, state, version, is_default))
    return distros


def parse_wsl_list_online(stdout: str) -> list[tuple[str, str]]:
    """Parse the decoded output of ``wsl --list --online``.

    The expected input format::

        The following is a list of valid distributions...
        NAME                                   FRIENDLY NAME
        Ubuntu                                 Ubuntu
        Debian                                 Debian GNU/Linux
        ...

    The parser searches for a header row matching ``NAME ... FRIENDLY NAME``
    (case-insensitive) and then splits subsequent rows on 2+ consecutive
    spaces to separate the catalog name from the friendly name.

    Args:
        stdout: Decoded text from ``wsl.exe --list --online``.

    Returns:
        A list of ``(catalog_name, friendly_name)`` pairs, or an empty list
        if the header row was not found (e.g., empty output, connection error).
    """
    lines = stdout.splitlines()
    start_idx: Optional[int] = None

    # Locate the header row: "NAME" followed by "FRIENDLY NAME" (any case)
    for idx, raw_line in enumerate(lines):
        if re.match(r"^\s*name\s+friendly\s+name\s*$", raw_line, re.IGNORECASE):
            start_idx = idx + 1
            break

    if start_idx is None:
        return []  # header not found — no data to parse

    distros: list[tuple[str, str]] = []
    for raw_line in lines[start_idx:]:
        line = raw_line.strip()
        if not line:
            continue  # skip blank lines
        # Split on 2+ spaces to separate columns (names never contain double spaces)
        parts = re.split(r"\s{2,}", line)
        if len(parts) < 2:
            continue  # not enough columns
        name = parts[0].strip()
        friendly_name = parts[1].strip()
        if name:
            distros.append((name, friendly_name))
    return distros
