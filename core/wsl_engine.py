"""
core/wsl_engine.py
==================

Low-level interface to ``wsl.exe``, ``winget``, ``dism``, and PowerShell on
Windows.  This is the **sole** module that spawns operating-system processes;
all other modules interact with WSL exclusively through this engine.

All public methods that run long processes return **generators** that yield
decoded output lines in real time, keeping the UI responsive when consumed
from a :class:`~PySide6.QtCore.QThread` worker.  Short-running meta-commands
(``--list``, ``--set-default``, ``--terminate``) use synchronous
:meth:`_run` and return ``(returncode, stdout, stderr)`` tuples.

Requirements
------------
* Windows 10 build 19041+ (WSL 2 support).
* ``wsl.exe`` must be in ``%SystemRoot%\\System32``.
* ``winget`` must be available for Windows package manager installs.
* Optional: ``zstandard`` Python library for ``.zst`` decompression
  (handled in :mod:`core.downloader`, not here).

Key classes
-----------
* :class:`WslEngine` — High-level facade around ``wsl.exe``.
* :class:`DistroInfo` — Parsed distro state from ``wsl --list --verbose``.
* :class:`OnlineDistro` — Entry from the WSL online catalog.
* :class:`WslCommandError` — Raised when a subprocess exits non-zero.
* :class:`WslNotFoundError` — Raised when ``wsl.exe`` cannot be located.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Generator, Optional

from core.constants import (
    WSL_IMPORT_EXPORT_TIMEOUT,
    WSL_SET_VERSION_TIMEOUT,
    WSL_VALIDATE_USER_TIMEOUT,
)
from core.wsl_list_parser import parse_wsl_list_online, parse_wsl_list_verbose

# ---------------------------------------------------------------------------
# Cross-platform helpers for subprocess creation flags
# ---------------------------------------------------------------------------

#: ``subprocess.CREATE_NO_WINDOW`` is Windows-only.  On Linux/macOS this
#: constant does not exist, so we fall back to 0 (no flags).
#: Used by :meth:`WslEngine._run`, :meth:`WslEngine._popen_stream`,
#: :meth:`WslEngine._popen_stream_checked`, :meth:`WslEngine.install_via_winget`,
#: and :meth:`WslEngine.install_via_dism`.
_NO_WINDOW_FLAG: int = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class DistroInfo:
    """Parsed state of a single registered WSL distribution.

    Produced by :meth:`WslEngine.list_distros` from
    ``wsl --list --verbose --all`` output.

    Attributes
    ----------
    name : str
        WSL registration name (e.g. ``"Ubuntu-24.04"``).
    state : str
        ``"Running"``, ``"Stopped"``, ``"Installing"``, or a localised
        equivalent from the Windows locale.
    version : int
        WSL version number: ``1`` or ``2``.
    is_default : bool
        ``True`` if this distro is the system default (marked with ``*``
        in ``wsl --list`` output).
    """

    name: str
    state: str      # "Running" | "Stopped" | "Installing"
    version: int    # WSL version 1 or 2
    is_default: bool = False

    @property
    def is_running(self) -> bool:
        """``True`` when the distro is currently running."""
        return self.state.lower() == "running"

    @property
    def is_stopped(self) -> bool:
        """``True`` when the distro is stopped or has an empty state string."""
        return self.state.lower() in ("stopped", "")


@dataclass
class OnlineDistro:
    """Entry returned by ``wsl --list --online`` (the Microsoft Store catalog).

    Attributes
    ----------
    name : str
        Catalog identifier used with ``wsl --install -d <name>``
        (e.g. ``"Ubuntu"``, ``"Debian"``).
    friendly_name : str
        Human-readable display name (e.g. ``"Ubuntu 24.04 LTS"``).
    """

    name: str
    friendly_name: str


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class WslNotFoundError(RuntimeError):
    """Raised when ``wsl.exe`` cannot be located on the system.

    This typically means WSL is not installed or the Windows installation
    is corrupted.  The application can still start in limited mode (view
    settings, browse catalogs) but all WSL operations will be unavailable.
    """


class WslCommandError(RuntimeError):
    """Raised when a WSL subprocess exits with a non-zero return code.

    Attributes
    ----------
    returncode : int
        The exit code returned by the subprocess.
    stderr : str
        Captured stderr output (or merged stdout, if stderr was redirected).
    """

    def __init__(self, message: str, returncode: int = -1, stderr: str = ""):
        super().__init__(message)
        self.returncode: int = returncode
        self.stderr: str = stderr


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class WslEngine:
    """High-level facade around ``wsl.exe``.

    Instantiation automatically detects the correct path to ``wsl.exe`` for
    both Windows-native and WSL-hosted execution contexts.

    All public methods are **synchronous** (they block the calling thread).
    Methods that may run for more than a few seconds return generators so
    callers can stream output to the UI and remain responsive.

    Usage::

        engine = WslEngine()
        distros = engine.list_distros()
        for distro in distros:
            print(distro.name, distro.is_running)
    """

    def __init__(self) -> None:
        self._wsl_exe: str = self._resolve_wsl_exe()

    # =========================================================================
    # Internal helpers
    # =========================================================================

    def _resolve_wsl_exe(self) -> str:
        """Locate ``wsl.exe`` on the current Windows system.

        Search order:
        1. ``%SystemRoot%\\System32\\wsl.exe`` (64-bit native).
        2. ``%SystemRoot%\\SysNative\\wsl.exe`` (32-bit redirected).
        3. ``PATH`` lookup via :func:`shutil.which`.

        Returns:
            The absolute path to ``wsl.exe`` as a string.

        Raises:
            WslNotFoundError: If ``wsl.exe`` cannot be found at any of the
                expected locations.
        """
        candidates: list[Path] = [
            Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "wsl.exe",
            Path(os.environ.get("SystemRoot", r"C:\Windows")) / "SysNative" / "wsl.exe",
        ]
        for path in candidates:
            if path.exists():
                return str(path)

        # Last resort: search PATH
        found = shutil.which("wsl.exe") or shutil.which("wsl")
        if found:
            return found

        raise WslNotFoundError(
            "wsl.exe not found. Please ensure Windows Subsystem for Linux is installed."
        )

    def _decode_wsl_output(self, raw: bytes) -> str:
        """Decode raw bytes from ``wsl.exe`` stdout/stderr.

        ``wsl.exe`` meta-commands (``--list``, ``--version``) output
        **UTF-16 LE** on Windows.  Command execution piped through bash
        (``wsl -d <distro> -- bash -c '...'``) outputs **UTF-8**.

        Strategy: try UTF-16 LE first (with BOM stripping), then fall back
        to UTF-8 with replacement characters for non-decodable bytes.

        Args:
            raw: Raw bytes captured from subprocess stdout or stderr.

        Returns:
            Decoded string with ``\\r\\n`` and ``\\r`` normalised to ``\\n``.
        """
        try:
            text = raw.decode("utf-16-le")
            return text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
        except (UnicodeDecodeError, ValueError):
            pass
        return raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")

    def _run(
        self,
        args: list[str],
        check: bool = False,
        timeout: Optional[int] = None,
    ) -> tuple[int, str, str]:
        """Execute ``wsl.exe`` synchronously with *args*.

        This is used for short-running meta-commands (``--list``,
        ``--set-default``, ``--terminate``, etc.).  For long-running
        commands that produce streaming output, use :meth:`_popen_stream`
        or :meth:`_popen_stream_checked` instead.

        Args:
            args: Arguments to pass to ``wsl.exe`` (without the executable
                path itself).
            check: If ``True``, raise :class:`WslCommandError` when the exit
                code is non-zero.
            timeout: Subprocess timeout in seconds.  ``None`` means no limit.

        Returns:
            A tuple of ``(returncode, stdout_text, stderr_text)``.

        Raises:
            WslCommandError: If *check* is ``True`` and the exit code ≠ 0,
                or if the subprocess times out.
            WslNotFoundError: If ``wsl.exe`` is not accessible.
        """
        cmd = [self._wsl_exe] + [str(a) for a in args]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout,
                creationflags=_NO_WINDOW_FLAG,
            )
        except subprocess.TimeoutExpired as exc:
            raise WslCommandError(f"WSL command timed out after {timeout}s") from exc
        except FileNotFoundError as exc:
            raise WslNotFoundError(
                f"wsl.exe not accessible at '{self._wsl_exe}'."
            ) from exc

        stdout = self._decode_wsl_output(result.stdout)
        stderr = self._decode_wsl_output(result.stderr)

        if check and result.returncode not in (0,):
            msg = stderr.strip() or stdout.strip() or f"exit code {result.returncode}"
            raise WslCommandError(
                f"WSL command failed: {msg}",
                returncode=result.returncode,
                stderr=stderr,
            )
        return result.returncode, stdout, stderr

    def _popen_stream(self, args: list[str]) -> Generator[str, None, None]:
        """Open a ``wsl.exe`` subprocess and yield decoded stdout lines in real time.

        stderr is merged into stdout (``STDOUT``) so callers receive all
        output through a single channel.  The process exit code is **not**
        checked — use :meth:`_popen_stream_checked` for that.

        Args:
            args: Arguments to pass to ``wsl.exe``.

        Yields:
            Decoded stdout/stderr lines, one per iteration, with trailing
            ``\\r\\n`` stripped.
        """
        cmd = [self._wsl_exe] + [str(a) for a in args]
        with subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=_NO_WINDOW_FLAG,
        ) as proc:
            assert proc.stdout is not None
            for raw_line in iter(proc.stdout.readline, b""):
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                yield line
            proc.wait()

    def _popen_stream_checked(self, args: list[str]) -> Generator[str, None, None]:
        """Same as :meth:`_popen_stream` but raises on non-zero exit code.

        All output lines are buffered internally so that the full error
        context (last 8 lines) can be included in the exception message.

        Args:
            args: Arguments to pass to ``wsl.exe``.

        Yields:
            Decoded stdout/stderr lines, one per iteration.

        Raises:
            WslCommandError: If the subprocess exits with a non-zero code.
        """
        cmd = [self._wsl_exe] + [str(a) for a in args]
        output_lines: list[str] = []
        with subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=_NO_WINDOW_FLAG,
        ) as proc:
            assert proc.stdout is not None
            for raw_line in iter(proc.stdout.readline, b""):
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                output_lines.append(line)
                yield line
            rc = proc.wait()

        if rc != 0:
            msg = "\n".join(output_lines[-8:]).strip() or f"exit code {rc}"
            raise WslCommandError(
                f"WSL command failed: {msg}",
                returncode=rc,
                stderr=msg,
            )

    # =========================================================================
    # Distro management
    # =========================================================================

    def list_distros(self) -> list[DistroInfo]:
        """Return every registered WSL distribution on this machine.

        Parses ``wsl --list --verbose --all`` via
        :func:`~core.wsl_list_parser.parse_wsl_list_verbose`.

        The expected output format on Windows is::

            \ufeff  NAME            STATE           VERSION
            * Ubuntu-24.04    Running         2
              Debian          Stopped         1

        Returns:
            A list of :class:`DistroInfo` objects, one per registered distro.
            Returns an empty list if no distros exist or if WSL is not
            available.
        """
        _rc, stdout, _stderr = self._run(["--list", "--verbose", "--all"])
        return [
            DistroInfo(name=n, state=s, version=v, is_default=d)
            for n, s, v, d in parse_wsl_list_verbose(stdout)
        ]

    def list_online_distros(self) -> list[OnlineDistro]:
        """Return the official WSL online catalog.

        Parses ``wsl --list --online`` via
        :func:`~core.wsl_list_parser.parse_wsl_list_online`.

        Returns:
            A list of :class:`OnlineDistro` objects from the Microsoft Store
            catalog.  Raises :class:`WslCommandError` if the command fails.

        Raises:
            WslCommandError: If ``wsl --list --online`` exits non-zero
                (e.g., no internet connection).
        """
        _rc, stdout, _stderr = self._run(["--list", "--online"], check=True)
        return [
            OnlineDistro(name=n, friendly_name=fn)
            for n, fn in parse_wsl_list_online(stdout)
        ]

    def install_online_distro(self, distro_name: str) -> Generator[str, None, None]:
        """Install a distribution directly from the WSL online catalog.

        Equivalent to: ``wsl --install -d <distro_name>``.
        The distro is downloaded from the Microsoft Store and registered
        automatically.

        Args:
            distro_name: Catalog name as shown by ``wsl --list --online``
                (e.g. ``"Ubuntu"``, ``"Debian"``).

        Yields:
            Real-time stdout/stderr lines from the install process.

        Raises:
            WslCommandError: If the installation fails (non-zero exit).
        """
        yield from self._popen_stream_checked(["--install", "-d", distro_name])

    def import_distro(
        self,
        name: str,
        install_dir: str,
        tar_path: str,
        version: int = 2,
    ) -> tuple[int, str, str]:
        """Import a rootfs tarball as a new WSL distribution.

        Equivalent to::

            wsl --import <name> <install_dir> <tar_path> --version <v>

        The *install_dir* is created if it does not already exist.

        Args:
            name: The WSL registration name for the new distro.
            install_dir: Directory where the distro's VHDX and config will
                be stored.
            tar_path: Path to the rootfs ``.tar`` or ``.tar.gz`` archive.
            version: WSL version (``1`` or ``2``).  Defaults to ``2``.

        Returns:
            ``(returncode, stdout, stderr)`` tuple.

        Raises:
            WslCommandError: On non-zero exit (e.g., name already in use,
                invalid tar, disk full).
        """
        Path(install_dir).mkdir(parents=True, exist_ok=True)
        return self._run(
            ["--import", name, install_dir, tar_path, "--version", str(version)],
            check=True,
            timeout=WSL_IMPORT_EXPORT_TIMEOUT,
        )

    def export_distro(self, name: str, output_path: str) -> tuple[int, str, str]:
        """Export a distribution to a ``.tar`` archive.

        Equivalent to: ``wsl --export <name> <output_path>``.
        The resulting tar can be imported on another machine or used as a
        backup.

        Args:
            name: WSL registration name of the distro to export.
            output_path: Destination path for the ``.tar`` file.

        Returns:
            ``(returncode, stdout, stderr)`` tuple.

        Raises:
            WslCommandError: On non-zero exit (e.g., distro not found,
                permission denied, disk full).
        """
        return self._run(
            ["--export", name, output_path],
            check=True,
            timeout=WSL_IMPORT_EXPORT_TIMEOUT,
        )

    def unregister_distro(self, name: str) -> tuple[int, str, str]:
        """Unregister (permanently delete) a WSL distribution.

        .. warning::

            This **permanently deletes** the distro's VHDX and all data
            inside it.  There is no recycle bin.  Consider exporting first
            if you need a backup.

        Args:
            name: WSL registration name of the distro to delete.

        Returns:
            ``(returncode, stdout, stderr)`` tuple.

        Raises:
            WslCommandError: On non-zero exit.
        """
        return self._run(["--unregister", name], check=True)

    def set_default(self, name: str) -> tuple[int, str, str]:
        """Set *name* as the system-default WSL distribution.

        The default distro is the one launched when ``wsl`` is invoked
        without a ``-d`` flag.

        Args:
            name: WSL registration name.

        Returns:
            ``(returncode, stdout, stderr)`` tuple.

        Raises:
            WslCommandError: On non-zero exit (e.g., distro not found).
        """
        return self._run(["--set-default", name], check=True)

    def set_version(self, name: str, version: int) -> tuple[int, str, str]:
        """Convert a distro between WSL 1 and WSL 2.

        .. note::

            Converting to WSL 2 requires a full filesystem copy and may
            take several minutes for large distros.

        Args:
            name: WSL registration name.
            version: Target WSL version (``1`` or ``2``).

        Returns:
            ``(returncode, stdout, stderr)`` tuple.

        Raises:
            WslCommandError: On non-zero exit or timeout.
        """
        return self._run(
            ["--set-version", name, str(version)],
            check=True,
            timeout=WSL_SET_VERSION_TIMEOUT,
        )

    def terminate(self, name: str) -> tuple[int, str, str]:
        """Terminate a running distribution without unregistering it.

        Equivalent to ``wsl --terminate <name>``.  The distro's state
        becomes ``"Stopped"`` but all data is preserved.

        Args:
            name: WSL registration name.

        Returns:
            ``(returncode, stdout, stderr)`` tuple.
        """
        return self._run(["--terminate", name])

    def shutdown(self) -> tuple[int, str, str]:
        """Shut down **all** running WSL distributions and the WSL 2 VM.

        Equivalent to ``wsl --shutdown``.  This is useful before applying
        ``.wslconfig`` changes or freeing memory.

        Returns:
            ``(returncode, stdout, stderr)`` tuple.
        """
        return self._run(["--shutdown"])

    def mount_disk(self, disk_path: str, options: str = "") -> tuple[int, str, str]:
        """Mount a physical disk or VHD into all WSL 2 distributions.

        Equivalent to ``wsl --mount <disk_path> [--options <options>]``.
        Requires administrator privileges.

        Args:
            disk_path: Path to the physical disk or ``.vhdx`` file.
            options: Optional mount options string (e.g. ``"ro"`` for
                read-only).

        Returns:
            ``(returncode, stdout, stderr)`` tuple.

        Raises:
            WslCommandError: On non-zero exit (e.g., no admin rights,
                invalid disk).
        """
        args = ["--mount", disk_path]
        if options:
            args += ["--options", options]
        return self._run(args, check=True)

    # =========================================================================
    # Real-time command execution
    # =========================================================================

    def run_command(self, distro: str, command: str) -> Generator[str, None, None]:
        """Execute a shell command inside *distro* as the default user.

        The command is executed via ``bash -c``, so shell features
        (pipes, redirects, variable expansion) work as expected.
        Output lines are yielded in real time.

        Usage::

            for line in engine.run_command("Ubuntu-24.04", "apt list --upgradable"):
                print(line)

        Args:
            distro: WSL registration name of the target distro.
            command: Shell command string to execute.

        Yields:
            Decoded stdout/stderr lines, one per iteration.
        """
        yield from self._popen_stream(["-d", distro, "--", "bash", "-c", command])

    def run_command_as_root(self, distro: str, command: str) -> Generator[str, None, None]:
        """Same as :meth:`run_command` but executes as root (uid 0).

        Uses ``wsl -u root`` to elevate privileges inside the distro.
        This is used for post-install configuration, package installation,
        and any operation that requires superuser access.

        Args:
            distro: WSL registration name of the target distro.
            command: Shell command string to execute as root.

        Yields:
            Decoded stdout/stderr lines, one per iteration.
        """
        yield from self._popen_stream(["-d", distro, "-u", "root", "--", "bash", "-c", command])

    # =========================================================================
    # Windows tool integration
    # =========================================================================

    @staticmethod
    def _powershell_exe() -> str:
        """Return the path to the best available PowerShell executable.

        Prefers ``pwsh.exe`` (PowerShell 7+) over ``powershell.exe``
        (Windows PowerShell 5.1), falling back to whichever is on PATH.

        Returns:
            Absolute path to a PowerShell executable as a string.

        Raises:
            FileNotFoundError: If neither ``pwsh.exe`` nor
                ``powershell.exe`` can be found on PATH.
        """
        ps = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
        if not ps:
            raise FileNotFoundError(
                "PowerShell not found. Ensure pwsh.exe or powershell.exe is in PATH."
            )
        return ps

    def install_via_winget(self, package_id: str) -> Generator[str, None, None]:
        """Install a Windows package via ``winget`` (runs through PowerShell).

        Uses silent/accept flags to avoid interactive prompts.  The
        ``winget`` output is streamed line-by-line.

        Args:
            package_id: The ``winget`` package identifier (e.g.
                ``"Canonical.Ubuntu.2404"``).

        Yields:
            Real-time stdout/stderr lines from the winget process.

        Raises:
            WslCommandError: If winget exits with a non-zero code.
        """
        ps_cmd = (
            f"winget install --id '{package_id}'"
            " --accept-package-agreements"
            " --accept-source-agreements"
            " --silent"
        )
        cmd = [
            self._powershell_exe(),
            "-NoProfile", "-NonInteractive",
            "-Command", ps_cmd,
        ]
        output_lines: list[str] = []
        with subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=_NO_WINDOW_FLAG,
        ) as proc:
            assert proc.stdout is not None
            for raw in iter(proc.stdout.readline, b""):
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                output_lines.append(line)
                yield line
            rc = proc.wait()
        if rc != 0:
            msg = "\n".join(output_lines[-8:]).strip() or f"exit code {rc}"
            raise WslCommandError(
                f"winget install failed: {msg}",
                returncode=rc,
                stderr=msg,
            )

    def install_via_dism(self, feature_name: str) -> Generator[str, None, None]:
        """Enable an optional Windows feature via DISM (Deployment Image Servicing).

        Runs through PowerShell::

            Enable-WindowsOptionalFeature -Online -FeatureName <name> -All -NoRestart

        .. note::

            This method exists but is **not currently exposed in the UI**.
            It is reserved for future use (e.g., enabling WSL subsystem
            features programmatically).

        Args:
            feature_name: Windows feature name (e.g.
                ``"Microsoft-Windows-Subsystem-Linux"``).

        Yields:
            Real-time stdout/stderr lines from the PowerShell/DISM process.

        Raises:
            WslCommandError: If the DISM command exits non-zero.
        """
        ps_cmd = (
            f"Enable-WindowsOptionalFeature"
            f" -Online -FeatureName '{feature_name}'"
            " -All -NoRestart"
        )
        cmd = [
            self._powershell_exe(),
            "-NoProfile", "-NonInteractive",
            "-Command", ps_cmd,
        ]
        output_lines: list[str] = []
        with subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=_NO_WINDOW_FLAG,
        ) as proc:
            assert proc.stdout is not None
            for raw in iter(proc.stdout.readline, b""):
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                output_lines.append(line)
                yield line
            rc = proc.wait()
        if rc != 0:
            msg = "\n".join(output_lines[-8:]).strip() or f"exit code {rc}"
            raise WslCommandError(
                f"DISM feature enable failed: {msg}",
                returncode=rc,
                stderr=msg,
            )

    # =========================================================================
    # WSL resource configuration (.wslconfig)
    # =========================================================================

    def build_wslconfig_text(
        self,
        memory_gb: int,
        swap_gb: int,
        processors: int,
        localhost_forwarding: bool = True,
        vm_idle_timeout: int = 60,
    ) -> str:
        """Build the content of a ``.wslconfig`` file as a string.

        ``.wslconfig`` is stored at ``%USERPROFILE%\\.wslconfig`` and
        controls global WSL 2 resource limits.  Changes take effect only
        after ``wsl --shutdown``.

        Generated format::

            [wsl2]
            memory=8GB
            swap=4GB
            processors=4
            localhostForwarding=true
            vmIdleTimeout=60

        Args:
            memory_gb: Maximum RAM for the WSL 2 VM (1–256 GB).
            swap_gb: Maximum swap space (0–128 GB; 0 = no swap).
            processors: Logical CPU cores available to WSL 2 (1–256).
            localhost_forwarding: Enable ``localhost`` port forwarding from
                Windows to WSL 2.
            vm_idle_timeout: Milliseconds of inactivity before the WSL 2 VM
                shuts down automatically.

        Returns:
            The ``.wslconfig`` content as a plain string.
        """
        return (
            "[wsl2]\n"
            f"memory={memory_gb}GB\n"
            f"swap={swap_gb}GB\n"
            f"processors={processors}\n"
            f"localhostForwarding={'true' if localhost_forwarding else 'false'}\n"
            f"vmIdleTimeout={vm_idle_timeout}\n"
        )

    def generate_wslconfig(
        self,
        memory_gb: int,
        swap_gb: int,
        processors: int,
        localhost_forwarding: bool = True,
        vm_idle_timeout: int = 60,
    ) -> Path:
        """Write (or overwrite) ``%USERPROFILE%\\.wslconfig`` with resource limits.

        This is a convenience method that builds the config text via
        :meth:`build_wslconfig_text` and writes it to disk.

        Args:
            memory_gb: Maximum RAM for the WSL 2 VM (GB).
            swap_gb: Maximum swap space (GB).
            processors: Logical CPU core count.
            localhost_forwarding: Enable port forwarding.
            vm_idle_timeout: VM auto-shutdown idle timeout.

        Returns:
            The :class:`~pathlib.Path` to the written ``.wslconfig`` file.
        """
        home = self._windows_home()
        config_path = home / ".wslconfig"
        content = self.build_wslconfig_text(
            memory_gb=memory_gb,
            swap_gb=swap_gb,
            processors=processors,
            localhost_forwarding=localhost_forwarding,
            vm_idle_timeout=vm_idle_timeout,
        )
        config_path.write_text(content, encoding="utf-8")
        return config_path

    def _windows_home(self) -> Path:
        """Return the Windows user profile directory (``%USERPROFILE%``).

        Falls back to :func:`pathlib.Path.home` if the environment variable
        is not set.
        """
        return Path(os.environ.get("USERPROFILE", str(Path.home())))

    # =========================================================================
    # Post-installation pipeline
    # =========================================================================

    def build_post_install_steps(
        self,
        pkg_manager: str,
        packages: list[str],
        username: str,
        password: str,
        sudo_group: str,
        run_system_update: bool = True,
        enable_systemd: bool = True,
    ) -> list[tuple[str, str]]:
        """Build the post-installation command pipeline for a fresh distro.

        Returns a list of ``(label, shell_command)`` tuples.  Each tuple
        represents one step in the pipeline.  The commands are designed to
        be executed **as root** via :meth:`run_command_as_root`.

        **Pipeline steps (in order):**

        1. **System update** — Refresh and upgrade all packages.
        2. **Base packages** — Install the distro's default package set.
        3. **User creation** — ``useradd`` with ``/bin/bash`` shell.
        4. **Password set** — Written via a temp file to keep it off the
           process list (``ps`` never sees the plaintext password).
        5. **Sudo group** — Add user to ``wheel`` / ``sudo`` group.
        6. **``/etc/wsl.conf``** — Write automount metadata, default user,
           and systemd boot settings.
        7. **Passwordless sudo** — Write ``/etc/sudoers.d/<user>`` for
           dnf/pacman distros.
        8. **Shell fix** — (apk only) Set ``/bin/bash`` as default shell.

        **Security notes:**

        * *username* is validated against ``^[a-z_][a-z0-9_-]{0,30}$``.
        * The password is written to a temporary file inside the guest and
          **deleted immediately** after ``chpasswd`` reads it.  It is never
          visible via ``ps``.

        Args:
            pkg_manager: ``"apt"``, ``"dnf"``, ``"zypper"``, ``"pacman"``,
                or ``"apk"``.  Determines update/install command syntax.
            packages: List of package names to install (may be empty).
            username: Linux username to create.  Empty = skip user steps.
            password: Plaintext password for the new user.
            sudo_group: Name of sudo group (``"sudo"`` or ``"wheel"``).
            run_system_update: Include system update step if ``True``.
            enable_systemd: Enable ``systemd=true`` in ``/etc/wsl.conf``.

        Returns:
            A list of ``(label, shell_command)`` tuples.

        Raises:
            ValueError: If *username* does not match the allowed pattern.
        """
        if username and not re.match(r"^[a-z_][a-z0-9_-]{0,30}$", username):
            raise ValueError(
                f"Invalid username {username!r}. "
                "Use lowercase letters, digits, underscores, and hyphens only."
            )

        pkg_list = " ".join(shlex.quote(p) for p in packages)
        safe_user = shlex.quote(username)
        safe_group = shlex.quote(sudo_group)

        # Build per-package-manager commands
        if pkg_manager == "apt":
            update_cmd = (
                "DEBIAN_FRONTEND=noninteractive apt-get update -y "
                "&& DEBIAN_FRONTEND=noninteractive apt-get upgrade -y"
            )
            install_cmd = f"DEBIAN_FRONTEND=noninteractive apt-get install -y {pkg_list}"
        elif pkg_manager == "dnf":
            update_cmd = "dnf update -y"
            install_cmd = f"dnf install -y {pkg_list}"
        elif pkg_manager == "zypper":
            update_cmd = "zypper --non-interactive refresh && zypper --non-interactive update"
            install_cmd = f"zypper --non-interactive install --no-recommends {pkg_list}"
        elif pkg_manager == "pacman":
            update_cmd = (
                "pacman-key --init "
                "&& pacman-key --populate archlinux "
                "&& pacman -Syu --noconfirm"
            )
            install_cmd = f"pacman -S --noconfirm {pkg_list}"
        elif pkg_manager == "apk":
            update_cmd = "apk update && apk upgrade"
            install_cmd = f"apk add {pkg_list}"
        else:
            update_cmd = "true"
            install_cmd = "true"

        steps: list[tuple[str, str]] = []
        if run_system_update:
            steps.append(("Updating package repositories", update_cmd))

        if pkg_list:
            steps.append(("Installing base packages", install_cmd))

        # Build /etc/wsl.conf content
        wsl_conf = (
            "[automount]\n"
            "root = /mnt\n"
            'options = "metadata"\n'
        )
        if username:
            wsl_conf += "\n[user]\n"
            wsl_conf += f"default = {username}\n"
        if enable_systemd and pkg_manager in ("apt", "dnf", "zypper"):
            wsl_conf += "\n[boot]\nsystemd = true\n"

        escaped_conf = wsl_conf.replace("'", "'\\''")
        write_wsl_conf_cmd = f"printf '%s' '{escaped_conf}' > /etc/wsl.conf"

        if username:
            # Write password via temp-file to keep it off the process list
            set_password_cmd = (
                f"_tmpf=$(mktemp) "
                f"&& printf '%s\\n' {shlex.quote(username + ':' + password)} > \"$_tmpf\" "
                f"&& chpasswd < \"$_tmpf\" "
                f"&& rm -f \"$_tmpf\""
            )

            steps.extend(
                [
                    (
                        f"Creating user '{username}'",
                        f"id -u {safe_user} >/dev/null 2>&1 "
                        f"|| useradd -m -s /bin/bash {safe_user}",
                    ),
                    ("Setting password", set_password_cmd),
                    (
                        f"Adding '{username}' to group '{sudo_group}'",
                        f"getent group {safe_group} >/dev/null 2>&1 "
                        f"|| groupadd {safe_group} ; "
                        f"usermod -aG {safe_group} {safe_user}",
                    ),
                ]
            )

        steps.append(("Writing /etc/wsl.conf", write_wsl_conf_cmd))

        # Some distros need an explicit sudoers entry to make the created
        # admin account usable immediately after post-install.
        if pkg_manager in ("dnf", "pacman") and username:
            sudoers_cmd = (
                f"echo '{username} ALL=(ALL) NOPASSWD:ALL' "
                f"> /etc/sudoers.d/{username} "
                f"&& chmod 440 /etc/sudoers.d/{username}"
            )
            steps.append(("Configuring passwordless sudo", sudoers_cmd))

        # Alpine: /bin/bash may not exist before packages are installed;
        # useradd is in the 'shadow' package which is in the packages list.
        if pkg_manager == "apk" and username:
            steps.append((
                "Setting default shell for user",
                f"chsh -s /bin/bash {safe_user} 2>/dev/null || true",
            ))

        return steps

    def inject_post_install(
        self,
        distro_name: str,
        pkg_manager: str,
        packages: list[str],
        username: str,
        password: str,
        sudo_group: str,
        run_system_update: bool = True,
        enable_systemd: bool = True,
    ) -> Generator[str, None, None]:
        """Execute the full post-install pipeline inside *distro_name*.

        Builds the step list via :meth:`build_post_install_steps` and
        executes each step sequentially as root inside the distro.
        Each step is announced with a ``>>> label...`` prefix line so
        the UI can display meaningful progress.

        Args:
            distro_name: WSL registration name of the freshly imported distro.
            pkg_manager: See :meth:`build_post_install_steps`.
            packages: See :meth:`build_post_install_steps`.
            username: See :meth:`build_post_install_steps`.
            password: See :meth:`build_post_install_steps`.
            sudo_group: See :meth:`build_post_install_steps`.
            run_system_update: See :meth:`build_post_install_steps`.
            enable_systemd: See :meth:`build_post_install_steps`.

        Yields:
            Real-time stdout/stderr lines as the pipeline executes.
        """
        steps = self.build_post_install_steps(
            pkg_manager=pkg_manager,
            packages=packages,
            username=username,
            password=password,
            sudo_group=sudo_group,
            run_system_update=run_system_update,
            enable_systemd=enable_systemd,
        )
        for label, cmd in steps:
            yield f"\n>>> {label}..."
            yield from self.run_command_as_root(distro_name, cmd)
        yield "\n>>> Post-installation complete."

    def validate_user_home_start(self, distro_name: str, username: str) -> tuple[int, str, str]:
        """Verify that a user account is functional inside a distro.

        Runs a non-interactive command from the target user's home directory::

            bash -lc "pwd && whoami"

        If this succeeds, the user exists, their home directory is reachable,
        and the default shell works.  Called at the end of post-install to
        confirm the created account is usable.

        Args:
            distro_name: WSL registration name.
            username: Linux username to validate.

        Returns:
            ``(returncode, stdout, stderr)`` tuple.
        """
        return self._run(
            [
                "-d", distro_name,
                "-u", username,
                "--cd", f"/home/{username}",
                "--", "bash", "-lc", "pwd && whoami",
            ],
            timeout=WSL_VALIDATE_USER_TIMEOUT,
        )
