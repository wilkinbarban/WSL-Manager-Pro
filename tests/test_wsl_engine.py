"""
Tests for selected pure helpers in :mod:`core.wsl_engine`
(no external ``wsl.exe`` calls — uses mocks where needed).

Covers:
* ``build_wslconfig_text`` — Generated ``.wslconfig`` content with
  advanced fields (localhostForwarding, vmIdleTimeout).
* ``build_post_install_steps`` — Sudoers configuration for Arch (wheel group).
* ``install_via_winget`` — ``WslCommandError`` raised on non-zero exit.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.wsl_engine import WslCommandError, WslEngine


def test_build_wslconfig_text_contains_advanced_fields() -> None:
    engine = object.__new__(WslEngine)
    content = engine.build_wslconfig_text(
        memory_gb=8,
        swap_gb=4,
        processors=6,
        localhost_forwarding=False,
        vm_idle_timeout=120,
    )
    assert "memory=8GB" in content
    assert "swap=4GB" in content
    assert "processors=6" in content
    assert "localhostForwarding=false" in content
    assert "vmIdleTimeout=120" in content


def test_build_post_install_steps_adds_sudoers_for_arch() -> None:
    engine = object.__new__(WslEngine)
    steps = engine.build_post_install_steps(
        pkg_manager="pacman",
        packages=["sudo", "git"],
        username="devuser",
        password="secret",
        sudo_group="wheel",
        run_system_update=True,
        enable_systemd=False,
    )
    labels = [label for label, _cmd in steps]
    assert "Configuring passwordless sudo" in labels
    sudoers_cmd = dict(steps)["Configuring passwordless sudo"]
    assert "/etc/sudoers.d/devuser" in sudoers_cmd


class _FakeStdout:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines
        self._index = 0

    def readline(self) -> bytes:
        if self._index >= len(self._lines):
            return b""
        line = self._lines[self._index]
        self._index += 1
        return line


class _FakePopen:
    def __init__(self, lines: list[bytes], rc: int) -> None:
        self.stdout = _FakeStdout(lines)
        self._rc = rc

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def wait(self) -> int:
        return self._rc


def test_install_via_winget_raises_on_nonzero_exit() -> None:
    engine = object.__new__(WslEngine)
    engine._powershell_exe = lambda: "powershell.exe"  # type: ignore[method-assign]
    fake = _FakePopen([b"winget log line\r\n"], rc=1)
    with patch("core.wsl_engine.subprocess.Popen", return_value=fake):
        with pytest.raises(WslCommandError, match="winget install failed"):
            list(engine.install_via_winget("Contoso.Distro"))
