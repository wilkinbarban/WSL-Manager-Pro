"""
Tests for :mod:`utils.diagnostic_bundle`.

Covers:
* ``tail_plain_text`` — Returning last N lines of text.
* ``write_diagnostic_zip`` — ZIP structure with WSL unavailable (``wsl_run=None``).
* ``write_diagnostic_zip`` — ZIP structure with mocked WSL command outputs,
  including error handling.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

from utils.diagnostic_bundle import tail_plain_text, write_diagnostic_zip


def test_tail_plain_text() -> None:
    text = "\n".join(f"line{i}" for i in range(10))
    out = tail_plain_text(text, 3)
    assert out.splitlines() == ["line7", "line8", "line9"]


def test_write_diagnostic_zip_minimal(tmp_path: Path) -> None:
    z = tmp_path / "d.zip"
    write_diagnostic_zip(
        z,
        app_version="9.9.9-test",
        log_plain="alpha\nbeta\ngamma\n",
        log_tail_lines=10,
        wsl_run=None,
    )
    with zipfile.ZipFile(z, "r") as zf:
        names = set(zf.namelist())
        assert names == {"README.txt", "log_tail.txt", "wsl_version.txt", "wsl_status.txt"}
        readme = zf.read("README.txt").decode("utf-8")
        assert "9.9.9-test" in readme
        assert "WSL engine not available" in readme


def test_write_diagnostic_zip_wsl_mock(tmp_path: Path) -> None:
    def fake_run(args: list[str]) -> tuple[int, str, str]:
        if args == ["--version"]:
            return 0, "WSL version: 2.2.2\n", ""
        if args == ["--status"]:
            return 1, "", "no distro"
        return 99, "", "bad"

    z = tmp_path / "d2.zip"
    write_diagnostic_zip(
        z,
        app_version="1.0.0",
        log_plain="ok",
        log_tail_lines=5,
        wsl_run=fake_run,
    )
    with zipfile.ZipFile(z, "r") as zf:
        assert "WSL version: 2.2.2" in zf.read("wsl_version.txt").decode()
        readme = zf.read("README.txt").decode()
        assert "non-zero exit code 1" in readme or "wsl --status" in readme
