"""
Unit tests for :mod:`core.wsl_list_parser` (no ``wsl.exe`` required).

Covers:
* ``parse_wsl_list_verbose`` — English table, UTF-16 LE BOM handling,
  default star marker, Spanish/Portuguese header skipping, informational
  line ignoring.
* ``parse_wsl_list_online`` — Minimal valid output, empty result when
  header row not found.
"""
from __future__ import annotations

from core.wsl_list_parser import parse_wsl_list_online, parse_wsl_list_verbose


def test_parse_verbose_english_table() -> None:
    stdout = """\
  NAME                   STATE           VERSION
* Ubuntu                 Running         2
  Debian                 Stopped         1
"""
    rows = parse_wsl_list_verbose(stdout)
    assert len(rows) == 2
    assert rows[0] == ("Ubuntu", "Running", 2, True)
    assert rows[1] == ("Debian", "Stopped", 1, False)


def test_parse_verbose_bom_and_default_star() -> None:
    stdout = (
        "\ufeff  NAME                   STATE           VERSION\n"
        "* MyDistro               Running         2\n"
    )
    rows = parse_wsl_list_verbose(stdout)
    assert len(rows) == 1
    assert rows[0][0] == "MyDistro"
    assert rows[0][3] is True


def test_parse_verbose_spanish_header_not_distro() -> None:
    """Localized header must not become a fake distro row."""
    stdout = """\
  NOMBRE              ESTADO            VERSIÓN
* Ubuntu              En ejecución      2
"""
    rows = parse_wsl_list_verbose(stdout)
    assert len(rows) == 1
    assert rows[0][0] == "Ubuntu"


def test_parse_verbose_informational_line_ignored() -> None:
    stdout = """\
There are no installed distributions.

Use 'wsl.exe --list --online' to list available distributions
"""
    assert parse_wsl_list_verbose(stdout) == []


def test_parse_online_minimal() -> None:
    stdout = """\
The following is a list of valid distributions that can be installed.

NAME                                   FRIENDLY NAME
Ubuntu                                 Ubuntu
Debian                                 Debian GNU/Linux
"""
    rows = parse_wsl_list_online(stdout)
    assert ("Ubuntu", "Ubuntu") in rows
    assert ("Debian", "Debian GNU/Linux") in rows


def test_parse_online_no_header_returns_empty() -> None:
    assert parse_wsl_list_online("random text\nno table here\n") == []
