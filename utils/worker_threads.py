"""
utils/worker_threads.py
=======================

:class:`~PySide6.QtCore.QThread`-based worker classes that keep the UI
responsive during long-running operations such as downloads, WSL imports,
exports, post-install scripts, and system updates.

Communication pattern
---------------------
Workers execute on background threads and communicate with the main (GUI)
thread exclusively through **Qt signals** (thread-safe in PySide6)::

    Worker thread  ── signal ──▶  Main thread slot
    ─────────────────────────────────────────────────
    log_message(str)        → append to log console
    error_occurred(str)     → show error in log + status bar
    progress(int, int)      → update progress bar
    stage_changed(str)      → update status label
    finished_ok()           → notify completion + cleanup

Cooperative cancellation
------------------------
Long-running workers inherit from :class:`CancellableWorker`, which provides
a :class:`threading.Event`.  Subclasses check ``cancel_event.is_set()``
between chunks or logical steps and return early when requested.  Cancellation
does **not** forcibly kill external processes already launched elsewhere.

Worker classes
--------------
* :class:`BaseWorker` — Abstract base; wraps errors into ``error_occurred``.
* :class:`CancellableWorker` — Base with cooperative cancellation.
* :class:`RefreshWorker` — Polls ``wsl --list --verbose``.
* :class:`UserStatusProbeWorker` — Probes default users for non-running distros.
* :class:`WslCommandWorker` — Runs arbitrary commands inside a distro.
* :class:`ExportWorker` — Exports a distro to a ``.tar`` file.
* :class:`ImportWorker` — Imports a ``.tar`` as a new distro.
* :class:`DownloadWorker` — Downloads a file with progress and resume.
* :class:`PostInstallWorker` — Runs the post-install provisioning pipeline.
* :class:`InstallWorker` — Orchestrates the full 5-step install pipeline.
* :class:`WslConfigWorker` — Generates and writes ``.wslconfig``.
* :class:`WingetInstallWorker` — Streams ``winget install`` output.
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal

from core.constants import WSL_PROBE_USER_TIMEOUT
from core.downloader import (
    ChecksumMismatch,
    DownloadCancelled,
    DownloadError,
    DownloadManager,
)
from core.wsl_engine import WslCommandError, WslEngine
from utils.config_manager import ConfigManager, InstalledDistro
from utils.i18n import t

# ---------------------------------------------------------------------------
# Base workers
# ---------------------------------------------------------------------------

class BaseWorker(QThread):
    """Abstract base for all background worker threads.

    Subclasses implement :meth:`_run_task` and use :meth:`_emit_log` /
    :meth:`_emit_error` for consistent log formatting.  Unhandled exceptions
    in :meth:`_run_task` are caught by :meth:`run` and emitted via
    :attr:`error_occurred` so the user always sees a meaningful message.

    Signals
    -------
    log_message : Signal(str)
        Emitted for each informational log line.
    error_occurred : Signal(str)
        Emitted when an error should be shown prominently.
    finished_ok : Signal()
        Emitted only on clean completion (no unhandled exception).
    """

    log_message    = Signal(str)
    error_occurred = Signal(str)
    finished_ok    = Signal()

    def run(self) -> None:
        """Entry point called by QThread.  Catches exceptions → error_occurred."""
        try:
            self._run_task()
        except WslCommandError as exc:
            self.error_occurred.emit(f"[WSL ERROR] {exc}")
        except Exception as exc:                         # noqa: BLE001
            self.error_occurred.emit(f"[ERROR] {exc}")

    def _run_task(self) -> None:
        """Override in subclasses — do the actual work here."""
        raise NotImplementedError

    def _emit_log(self, text: str) -> None:
        """Split *text* on newlines and emit each line via :attr:`log_message`."""
        for line in text.splitlines() or [""]:
            self.log_message.emit(line)

    def _emit_error(self, text: str) -> None:
        """Emit *text* via :attr:`error_occurred`."""
        self.error_occurred.emit(text)


class CancellableWorker(BaseWorker):
    """Worker base with cooperative cancellation support.

    Provides a :class:`threading.Event` that subclasses can check
    periodically.  Call :meth:`cancel` from the main thread to request
    cancellation; the worker should check :attr:`cancel_event` at safe
    boundaries and return early.

    .. note::

        Cancellation is **cooperative** — it does not forcibly kill external
        processes.  Workers launched via :class:`WslEngine` (which uses
        ``subprocess.Popen``) are not automatically terminated.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cancel = threading.Event()

    def cancel(self) -> None:
        """Signal the worker to stop at the next safe boundary."""
        self._cancel.set()

    @property
    def cancel_event(self) -> threading.Event:
        """The cancellation event for cooperative checking."""
        return self._cancel


# ---------------------------------------------------------------------------
# Refresh worker
# ---------------------------------------------------------------------------

class RefreshWorker(BaseWorker):
    """Query the current WSL distribution list and emit the result.

    Signals
    -------
    distros_updated : Signal(object)
        Emits a ``list[DistroInfo]`` after parsing ``wsl --list --verbose``.
    """

    distros_updated = Signal(object)   # list[DistroInfo]

    def __init__(self, engine: WslEngine, parent=None) -> None:
        super().__init__(parent)
        self._engine = engine

    def _run_task(self) -> None:
        distros = self._engine.list_distros()
        self.distros_updated.emit(distros)
        self.finished_ok.emit()


# ---------------------------------------------------------------------------
# User status probe worker
# ---------------------------------------------------------------------------

class UserStatusProbeWorker(BaseWorker):
    """Probe the default user for each distro without blocking the GUI.

    For each distro in *distro_names*, runs ``bash -lc 'id -un'`` to
    determine the runtime default user.  Distros in *stop_after_probe* are
    terminated after probing (to avoid leaving them running unnecessarily).

    Signals
    -------
    user_status_updated : Signal(object, object)
        Emits ``(dict[str, str], list[str])`` — a mapping of distro name →
        default user, and a list of distro names that were stopped.
    """

    user_status_updated = Signal(object, object)   # (dict[str, str], list[str])

    def __init__(
        self,
        engine: WslEngine,
        distro_names: list[str],
        stop_after_probe: Optional[set[str]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._engine = engine
        self._distro_names = distro_names
        self._stop_after_probe = {name.strip().lower() for name in (stop_after_probe or set())}

    def _run_task(self) -> None:
        results: dict[str, str] = {}
        stopped_after_probe: list[str] = []
        for distro_name in self._distro_names:
            try:
                rc, stdout, _stderr = self._engine._run(
                    ["-d", distro_name, "--", "bash", "-lc", "id -un"],
                    timeout=WSL_PROBE_USER_TIMEOUT,
                )
                if rc == 0:
                    lines = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
                    if lines:
                        results[distro_name] = lines[-1]
            except Exception:
                pass
            finally:
                if distro_name.strip().lower() in self._stop_after_probe:
                    try:
                        self._engine.terminate(distro_name)
                        stopped_after_probe.append(distro_name)
                    except Exception:
                        pass
        self.user_status_updated.emit(results, stopped_after_probe)
        self.finished_ok.emit()


# ---------------------------------------------------------------------------
# WslCommand worker
# ---------------------------------------------------------------------------

class WslCommandWorker(BaseWorker):
    """Run an arbitrary shell command inside a WSL distro and stream output.

    Used for operations like ``apt upgrade``, ``dnf update``, etc. that
    produce line-by-line output the user wants to see in real time.

    Args (constructor)
    ------------------
    engine : WslEngine
        The WSL engine instance to use.
    distro : str
        WSL registration name of the target distro.
    command : str
        Shell command string to execute.
    as_root : bool
        If ``True``, the command runs as root (``wsl -u root``).
    """

    def __init__(
        self,
        engine: WslEngine,
        distro: str,
        command: str,
        as_root: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._engine  = engine
        self._distro  = distro
        self._command = command
        self._as_root = as_root

    def _run_task(self) -> None:
        gen = (
            self._engine.run_command_as_root(self._distro, self._command)
            if self._as_root
            else self._engine.run_command(self._distro, self._command)
        )
        for line in gen:
            self.log_message.emit(line)
        self.finished_ok.emit()


# ---------------------------------------------------------------------------
# Export / Import workers
# ---------------------------------------------------------------------------

class ExportWorker(BaseWorker):
    """Export a single WSL distribution to a ``.tar`` file in a worker thread.

    Args (constructor)
    ------------------
    engine : WslEngine
    distro_name : str
        WSL registration name of the distro to export.
    output_path : str
        Destination path for the ``.tar`` file.
    """

    def __init__(self, engine: WslEngine, distro_name: str, output_path: str, parent=None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._distro_name = distro_name
        self._output_path = output_path

    def _run_task(self) -> None:
        self._engine.export_distro(self._distro_name, self._output_path)
        self.finished_ok.emit()


class ImportWorker(BaseWorker):
    """Import a ``.tar`` file as a new WSL distribution in a worker thread.

    Args (constructor)
    ------------------
    engine : WslEngine
    distro_name : str
        WSL registration name for the new distro.
    install_dir : str
        Directory where the distro's VHDX will be stored.
    tar_path : str
        Path to the rootfs ``.tar`` or ``.tar.gz`` archive.
    """

    def __init__(
        self,
        engine: WslEngine,
        distro_name: str,
        install_dir: str,
        tar_path: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._engine = engine
        self._distro_name = distro_name
        self._install_dir = install_dir
        self._tar_path = tar_path

    def _run_task(self) -> None:
        self._engine.import_distro(self._distro_name, self._install_dir, self._tar_path)
        self.finished_ok.emit()


# ---------------------------------------------------------------------------
# Download worker
# ---------------------------------------------------------------------------

class DownloadWorker(CancellableWorker):
    """Download a single file with progress reporting and resume support.

    Wraps :class:`~core.downloader.DownloadManager.download` in a QThread.
    Progress is emitted via :attr:`progress`; cancellation is cooperative.

    Signals
    -------
    progress : Signal(int, int)
        Emits ``(bytes_done, total_bytes)`` periodically during the transfer.
    """

    progress = Signal(int, int)

    def __init__(
        self,
        url: str,
        dest_path: str,
        checksum: Optional[str] = None,
        algo: str = "sha256",
        resume_bytes: int = 0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._url          = url
        self._dest_path    = dest_path
        self._checksum     = checksum
        self._algo         = algo
        self._resume_bytes = resume_bytes

    def _run_task(self) -> None:
        dm = DownloadManager()
        filename = Path(self._dest_path).name
        self.log_message.emit(t("Downloading {filename} ...", filename=filename))
        try:
            dm.download(
                url=self._url,
                dest_path=self._dest_path,
                progress_cb=lambda done, total: self.progress.emit(done, total),
                checksum=self._checksum,
                algo=self._algo,
                resume_bytes=self._resume_bytes,
                cancel_event=self.cancel_event,
            )
        except DownloadCancelled:
            self.log_message.emit(t("Download cancelled."))
            return
        except ChecksumMismatch as exc:
            self.error_occurred.emit(t("Checksum mismatch: {error}", error=exc))
            return
        except DownloadError as exc:
            self.error_occurred.emit(t("Download error: {error}", error=exc))
            return
        self.log_message.emit(t("Download complete: {path}", path=self._dest_path))
        self.finished_ok.emit()


# ---------------------------------------------------------------------------
# Post-install worker
# ---------------------------------------------------------------------------

class PostInstallWorker(CancellableWorker):
    """Run the post-installation provisioning pipeline inside a fresh distro.

    Executes system update, package installation, user creation,
    ``/etc/wsl.conf`` generation, sudo configuration, and shell setup.
    Each pipeline stage is announced via :attr:`stage_changed`.

    Signals
    -------
    stage_changed : Signal(str)
        Emitted with the current stage label (e.g. ``"Updating package repositories..."``).
    """

    stage_changed = Signal(str)

    def __init__(
        self,
        engine: WslEngine,
        distro_name: str,
        pkg_manager: str,
        packages: list[str],
        username: str,
        password: str,
        sudo_group: str,
        enable_systemd: bool,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._engine        = engine
        self._distro        = distro_name
        self._pkg_manager   = pkg_manager
        self._packages      = packages
        self._username      = username
        self._password      = password
        self._sudo_group    = sudo_group
        self._enable_systemd = enable_systemd

    def _run_task(self) -> None:
        for line in self._engine.inject_post_install(
            distro_name=self._distro,
            pkg_manager=self._pkg_manager,
            packages=self._packages,
            username=self._username,
            password=self._password,
            sudo_group=self._sudo_group,
            enable_systemd=self._enable_systemd,
        ):
            if self.cancel_event.is_set():
                self.log_message.emit(t("Post-install cancelled."))
                return
            if line.startswith(">>> "):
                self.stage_changed.emit(line[4:])
            self.log_message.emit(line)
        self.finished_ok.emit()


# ---------------------------------------------------------------------------
# Install worker — full installation pipeline orchestrator
# ---------------------------------------------------------------------------

class InstallWorker(CancellableWorker):
    """Orchestrate the full distribution installation pipeline.

    **Pipeline steps:**
    1. **Download** — Fetch the rootfs tarball (with resume support).
    2. **Extract / repackage** — Handle APPX, Arch bootstrap ZIP, etc.
    3. **Import** — ``wsl --import`` to the chosen directory.
    4. **Post-install** — User creation, package install, systemd, wsl.conf.
    5. **Register** — Record in :class:`~utils.config_manager.ConfigManager`.

    For ``wsl_online`` install methods, steps 1–3 are replaced by
    ``wsl --install -d <name>``.

    Signals
    -------
    progress : Signal(int, int)
        Download progress (bytes_done, total_bytes).
    stage_changed : Signal(str)
        Current pipeline stage label (e.g. ``"Downloading"``, ``"Importing"``).
    install_finished : Signal(str)
        Emitted with the WSL distro name on successful completion.
    """

    progress      = Signal(int, int)
    stage_changed = Signal(str)
    install_finished = Signal(str)     # emits the WSL distro name on success

    def __init__(
        self,
        engine: WslEngine,
        config_mgr: ConfigManager,
        distro_id: str,
        distro_cfg: dict,
        wsl_name: str,
        install_dir: str,
        download_dir: str,
        username: str,
        password: str,
        run_system_update: bool = True,
        wsl_version: int = 2,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._engine       = engine
        self._config_mgr   = config_mgr
        self._distro_id    = distro_id
        self._distro_cfg   = distro_cfg
        self._wsl_name     = wsl_name
        self._install_dir  = install_dir
        self._download_dir = download_dir
        self._username     = username
        self._password     = password
        self._run_system_update = run_system_update
        self._wsl_version  = wsl_version

    # ------------------------------------------------------------------

    def _run_task(self) -> None:
        cfg = self._distro_cfg

        if cfg.get("install_method") == "wsl_online":
            self._run_online_install(cfg)
            return

        # ---- Step 1: Download ----------------------------------------
        self._set_stage("Downloading")
        url      = cfg["url"]
        filename = url.split("/")[-1]
        dest     = str(Path(self._download_dir) / filename)

        # Resume support: check existing partial file
        existing_state = self._config_mgr.get_download_state(url)
        resume_bytes   = existing_state.bytes_downloaded if existing_state else 0

        # Optionally resolve checksum from remote file
        checksum: Optional[str] = None
        if cfg.get("checksum_url"):
            self._emit_log(t("Fetching checksum ..."))
            checksum = DownloadManager.fetch_checksum_from_file(
                checksum_url=cfg["checksum_url"],
                filename_pattern=str(cfg.get("checksum_file_pattern") or ""),
                algo=cfg.get("algo", "sha256"),
                cancel_event=self.cancel_event,
            )
            if checksum:
                self._emit_log(
                    t(
                        "Expected {algo}: {checksum}",
                        algo=cfg.get("algo", "sha256").upper(),
                        checksum=checksum,
                    )
                )

        dm = DownloadManager()
        try:
            dm.download(
                url=url,
                dest_path=dest,
                progress_cb=lambda done, total: self.progress.emit(done, total),
                checksum=checksum,
                algo=cfg.get("algo", "sha256"),
                resume_bytes=resume_bytes,
                cancel_event=self.cancel_event,
            )
        except DownloadCancelled:
            self._emit_log(t("Installation cancelled during download."))
            return
        except (DownloadError, ChecksumMismatch) as exc:
            self._emit_error(str(exc))
            return

        if self.cancel_event.is_set():
            return

        # ---- Step 2: Extract / repackage if needed -------------------
        extract_type = cfg.get("extract_type", "tar.gz")
        tar_path = dest

        if extract_type == "appx":
            self._set_stage("Extracting APPX")
            self._emit_log(t("Extracting APPX package ..."))
            extract_dir = dest + "_extracted"
            inner = DownloadManager.extract_appx(dest, extract_dir)
            if not inner:
                self._emit_error(t("Could not locate rootfs inside APPX package."))
                return
            tar_path = inner

        elif extract_type in ("tar.zst", "zip"):
            self._set_stage("Extracting archive")
            self._emit_log(
                t(
                    "Repackaging {extract_type} archive for WSL import ...",
                    extract_type=extract_type,
                )
            )
            repacked = dest.rsplit(".", 1)[0] + "_repacked.tar.gz"
            try:
                DownloadManager.extract_arch_bootstrap(dest, repacked,
                                                       progress_cb=None)
            except Exception as exc:  # noqa: BLE001
                self._emit_error(t("Extraction failed: {error}", error=exc))
                return
            tar_path = repacked

        if self.cancel_event.is_set():
            return

        # ---- Step 3: WSL import --------------------------------------
        self._set_stage("Importing")
        distro_install_dir = str(Path(self._install_dir) / self._wsl_name)
        self._emit_log(
            t("Importing '{name}' -> {path} ...", name=self._wsl_name, path=distro_install_dir)
        )
        try:
            self._engine.import_distro(
                name=self._wsl_name,
                install_dir=distro_install_dir,
                tar_path=tar_path,
                version=self._wsl_version,
            )
        except WslCommandError as exc:
            self._emit_error(t("Import failed: {error}", error=exc))
            return

        self._emit_log(t("WSL import successful."))

        if self.cancel_event.is_set():
            return

        # ---- Step 4: Post-install ------------------------------------
        if self._run_system_update or self._username:
            self._set_stage("Post-install")
            for line in self._engine.inject_post_install(
                distro_name=self._wsl_name,
                pkg_manager=cfg.get("pkg_manager", "apt"),
                packages=cfg.get("packages", []),
                username=self._username,
                password=self._password,
                sudo_group=cfg.get("sudo_group", "sudo"),
                run_system_update=self._run_system_update,
                enable_systemd=cfg.get("systemd", False),
            ):
                if self.cancel_event.is_set():
                    self._emit_log(t("Installation cancelled during post-install."))
                    return
                self.log_message.emit(line)

        if self._username:
            self._set_stage("Finalizing")
            try:
                self._engine.shutdown()
            except WslCommandError as exc:
                self._emit_log(t("Warning: could not shutdown WSL immediately: {error}", error=exc))
            rc, out, err = self._engine.validate_user_home_start(self._wsl_name, self._username)
            if rc != 0:
                self._emit_log(t("Warning: could not validate user home startup automatically."))
                if err.strip():
                    self._emit_log(err.strip())
            elif out.strip():
                self._emit_log(t("User/home validation: {output}", output=out.strip()))

        # ---- Step 5: Register ----------------------------------------
        self._config_mgr.register_installed_distro(
            InstalledDistro(
                name=self._wsl_name,
                distro_id=self._distro_id,
                install_dir=distro_install_dir,
                installed_at=datetime.now().isoformat(),
                username=self._username,
            )
        )
        # Clean up completed download state
        self._config_mgr.remove_download_state(url)

        self._set_stage("Complete")
        self._emit_log(t("\n[OK] '{name}' installed successfully!", name=self._wsl_name))
        self.install_finished.emit(self._wsl_name)
        self.finished_ok.emit()

    # ------------------------------------------------------------------

    def _run_online_install(self, cfg: dict) -> None:
        online_name = str(cfg.get("online_name") or self._wsl_name).strip()
        if not online_name:
            self._emit_error(t("Invalid online distro name."))
            return

        self._set_stage("Installing")
        self._emit_log(
            t("Installing '{name}' from the official WSL online catalog ...", name=online_name)
        )
        try:
            available = {
                d.name.lower()
                for d in self._engine.list_online_distros()
            }
        except WslCommandError as exc:
            self._emit_error(t("Could not validate online distro list: {error}", error=exc))
            return

        if online_name.lower() not in available:
            self._emit_error(
                t("Distro '{name}' is not available in 'wsl --list --online'.", name=online_name)
            )
            return

        try:
            for line in self._engine.install_online_distro(online_name):
                if self.cancel_event.is_set():
                    self._emit_log(t("Installation cancellation requested."))
                    return
                if line.strip():
                    self.log_message.emit(line)
        except WslCommandError as exc:
            self._emit_error(t("Online install failed: {error}", error=exc))
            return

        self._config_mgr.register_installed_distro(
            InstalledDistro(
                name=online_name,
                distro_id=self._distro_id,
                install_dir=str(Path(self._install_dir) / online_name),
                installed_at=datetime.now().isoformat(),
                username=self._username,
            )
        )

        if self._run_system_update or self._username:
            self._set_stage("Post-install")
            for line in self._engine.inject_post_install(
                distro_name=online_name,
                pkg_manager=cfg.get("pkg_manager", "apt"),
                packages=cfg.get("packages", []),
                username=self._username,
                password=self._password,
                sudo_group=cfg.get("sudo_group", "sudo"),
                run_system_update=self._run_system_update,
                enable_systemd=cfg.get("systemd", False),
            ):
                if self.cancel_event.is_set():
                    self._emit_log(t("Installation cancelled during post-install."))
                    return
                self.log_message.emit(line)

        if self._username:
            self._set_stage("Finalizing")
            try:
                self._engine.shutdown()
            except WslCommandError as exc:
                self._emit_log(t("Warning: could not shutdown WSL immediately: {error}", error=exc))
            rc, out, err = self._engine.validate_user_home_start(online_name, self._username)
            if rc != 0:
                self._emit_log(t("Warning: could not validate user home startup automatically."))
                if err.strip():
                    self._emit_log(err.strip())
            elif out.strip():
                self._emit_log(t("User/home validation: {output}", output=out.strip()))

        self._set_stage("Complete")
        self._emit_log(t("\n[OK] '{name}' installed successfully!", name=online_name))
        self.install_finished.emit(online_name)
        self.finished_ok.emit()

    # ------------------------------------------------------------------

    def _set_stage(self, label: str) -> None:
        self.stage_changed.emit(label)
        self.log_message.emit(f"\n[{label.upper()}]")


# ---------------------------------------------------------------------------
# WslConfig worker — write .wslconfig
# ---------------------------------------------------------------------------

class WslConfigWorker(BaseWorker):
    """Write (or overwrite) the Windows ``%USERPROFILE%\\.wslconfig`` file.

    Generates the file content and writes it to disk.  The changes take
    effect only after the next ``wsl --shutdown`` — this worker does **not**
    automatically shut down WSL.

    Signals
    -------
    config_written : Signal(str)
        Emitted with the absolute path of the written ``.wslconfig`` file.

    Args (constructor)
    ------------------
    engine : WslEngine
    memory_gb : int
        Maximum RAM (GB) for the WSL 2 VM.
    swap_gb : int
        Maximum swap space (GB).
    processors : int
        Logical CPU cores available.
    localhost_forwarding : bool
        Enable ``localhost`` port forwarding.
    vm_idle_timeout : int
        VM idle timeout in seconds.
    """

    config_written = Signal(str)

    def __init__(
        self,
        engine: WslEngine,
        memory_gb: int,
        swap_gb: int,
        processors: int,
        localhost_forwarding: bool,
        vm_idle_timeout: int,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._engine     = engine
        self._memory_gb  = memory_gb
        self._swap_gb    = swap_gb
        self._processors = processors
        self._localhost_forwarding = localhost_forwarding
        self._vm_idle_timeout = vm_idle_timeout

    def _run_task(self) -> None:
        path = self._engine.generate_wslconfig(
            memory_gb=self._memory_gb,
            swap_gb=self._swap_gb,
            processors=self._processors,
            localhost_forwarding=self._localhost_forwarding,
            vm_idle_timeout=self._vm_idle_timeout,
        )
        self.log_message.emit(t(".wslconfig written to: {path}", path=path))
        self.config_written.emit(str(path))
        self.finished_ok.emit()


class WingetInstallWorker(CancellableWorker):
    """Install a Windows package via ``winget`` and stream its output.

    Runs ``winget install`` through PowerShell with silent/accept flags.
    Cancellation is cooperative — the worker checks the cancel event
    between output lines.

    Args (constructor)
    ------------------
    engine : WslEngine
    package_id : str
        The ``winget`` package identifier (e.g. ``"Canonical.Ubuntu.2404"``).
    """

    def __init__(self, engine: WslEngine, package_id: str, parent=None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._package_id = package_id

    def _run_task(self) -> None:
        self._emit_log(
            t(
                "Starting winget install for '{package_id}'...",
                package_id=self._package_id,
            )
        )
        for line in self._engine.install_via_winget(self._package_id):
            if self.cancel_event.is_set():
                self._emit_log(t("winget installation cancelled."))
                return
            if line.strip():
                self.log_message.emit(line)
        self.finished_ok.emit()
