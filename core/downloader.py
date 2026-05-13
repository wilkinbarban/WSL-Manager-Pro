"""
core/downloader.py
==================

Thread-friendly (synchronous, non-GUI-blocking) download manager with:

* **Resume support** — HTTP Range requests so interrupted downloads pick up
  where they left off.
* **Checksum verification** — SHA-256 / SHA-512 / MD5 integrity checks
  against expected digests or checksum index files (e.g., Ubuntu
  ``SHA256SUMS``).
* **Cancellation** — Cooperative cancellation via :class:`threading.Event`,
  suitable for use from a :class:`~PySide6.QtCore.QThread`.
* **Archive extraction** — APPX (ZIP-based) and Arch Linux bootstrap
  (``tar.gz`` / ``tar.zst``) extraction and repackaging for
  ``wsl --import``.

Designed to be called from :mod:`utils.worker_threads` workers so that
progress callbacks can emit Qt signals without blocking the GUI thread.

Exceptions
----------
* :class:`DownloadError` — Non-cancellation failures (HTTP errors, I/O).
* :class:`DownloadCancelled` — Transfer aborted via cancel event.
* :class:`ChecksumMismatch` — Expected hash ≠ actual hash.
"""
from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import Callable, Optional

import requests

from core.constants import (
    DOWNLOAD_CHUNK_SIZE,
    DOWNLOAD_CONNECT_TIMEOUT,
    DOWNLOAD_MAX_RETRIES,
    DOWNLOAD_READ_TIMEOUT,
)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class DownloadError(IOError):
    """Raised when a download fails for a non-cancellation reason."""


class DownloadCancelled(Exception):
    """Raised when a download is cancelled via the cancel event."""


class ChecksumMismatch(ValueError):
    """Raised when a downloaded file's checksum does not match expected."""
    def __init__(self, expected: str, actual: str):
        super().__init__(f"Checksum mismatch.\n  expected: {expected}\n  actual  : {actual}")
        self.expected = expected
        self.actual = actual


# ---------------------------------------------------------------------------
# DownloadManager
# ---------------------------------------------------------------------------

ProgressCallback = Callable[[int, int], None]   # (bytes_done, total_bytes)


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def _safe_extract_zip(zip_file, output_dir: str) -> None:
    """Extract a ZIP archive without allowing members to escape output_dir."""
    dest_root = Path(output_dir).resolve()
    for member in zip_file.infolist():
        target = (dest_root / member.filename).resolve()
        if not _is_relative_to(target, dest_root):
            raise DownloadError(f"Unsafe ZIP member path: {member.filename}")
    zip_file.extractall(output_dir)


def _safe_extract_tar(tar_file, output_dir: str) -> None:
    """Extract a TAR archive without allowing path traversal."""
    dest_root = Path(output_dir).resolve()
    for member in tar_file.getmembers():
        target = (dest_root / member.name).resolve()
        if not _is_relative_to(target, dest_root):
            raise DownloadError(f"Unsafe TAR member path: {member.name}")
        if member.islnk():
            link_target = (dest_root / member.linkname).resolve()
            if not _is_relative_to(link_target, dest_root):
                raise DownloadError(f"Unsafe TAR hardlink target: {member.name}")
    tar_file.extractall(output_dir)


class DownloadManager:
    """
    Download a single file with optional resume and integrity verification.

    Usage::

        dm = DownloadManager()
        cancel = threading.Event()
        dm.download(
            url="https://example.com/rootfs.tar.gz",
            dest_path="/tmp/rootfs.tar.gz",
            progress_cb=lambda done, total: print(f"{done}/{total}"),
            cancel_event=cancel,
        )
    """

    CHUNK_SIZE = DOWNLOAD_CHUNK_SIZE
    CONNECT_TIMEOUT = DOWNLOAD_CONNECT_TIMEOUT
    READ_TIMEOUT = DOWNLOAD_READ_TIMEOUT
    MAX_RETRIES = DOWNLOAD_MAX_RETRIES

    def download(
        self,
        url: str,
        dest_path: str,
        progress_cb: Optional[ProgressCallback] = None,
        checksum: Optional[str] = None,
        algo: str = "sha256",
        resume_bytes: int = 0,
        cancel_event: Optional[threading.Event] = None,
    ) -> Path:
        """
        Download *url* to *dest_path*.

        Parameters
        ----------
        url          : Remote URL to fetch.
        dest_path    : Local path to write to.  Parent directory is created.
        progress_cb  : Called with ``(bytes_done, total_bytes)`` periodically.
                       *total_bytes* is 0 when the server does not send
                       Content-Length.
        checksum     : Expected hex digest.  If provided, the file is verified
                       after a successful download.
        algo         : Hash algorithm name accepted by :mod:`hashlib`.
        resume_bytes : Number of bytes already downloaded (for resume logic).
                       Pass 0 (default) to auto-detect from an existing file.
        cancel_event : A :class:`threading.Event`; set it to abort the transfer.

        Returns the :class:`~pathlib.Path` of the downloaded file.
        Raises :class:`DownloadCancelled` if *cancel_event* is set mid-transfer.
        Raises :class:`DownloadError` on HTTP or IO errors.
        Raises :class:`ChecksumMismatch` when verification fails.
        """
        dest = Path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)

        # Determine resume offset
        if resume_bytes == 0 and dest.exists():
            resume_bytes = dest.stat().st_size

        headers: dict[str, str] = {}
        if resume_bytes > 0:
            headers["Range"] = f"bytes={resume_bytes}-"

        last_error: Optional[Exception] = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                with requests.get(
                    url,
                    headers=headers,
                    stream=True,
                    timeout=(self.CONNECT_TIMEOUT, self.READ_TIMEOUT),
                ) as resp:
                    # 416 = range not satisfiable → file already complete
                    if resp.status_code == 416:
                        if checksum:
                            self.verify_checksum(dest_path, checksum, algo)
                        return dest

                    if resp.status_code not in (200, 206):
                        raise DownloadError(
                            f"HTTP {resp.status_code} for {url}"
                        )

                    # Total size for progress reporting
                    content_length = int(resp.headers.get("Content-Length", 0))
                    total_bytes = resume_bytes + content_length if content_length else 0

                    mode = "ab" if resume_bytes > 0 and resp.status_code == 206 else "wb"
                    bytes_written = resume_bytes if mode == "ab" else 0

                    with dest.open(mode) as fh:
                        for chunk in resp.iter_content(chunk_size=self.CHUNK_SIZE):
                            if cancel_event and cancel_event.is_set():
                                raise DownloadCancelled("Download cancelled by user.")
                            if chunk:
                                fh.write(chunk)
                                bytes_written += len(chunk)
                                if progress_cb:
                                    progress_cb(bytes_written, total_bytes)

                # Success
                if checksum:
                    self.verify_checksum(dest_path, checksum, algo)
                return dest

            except DownloadCancelled:
                raise
            except ChecksumMismatch:
                raise
            except (requests.RequestException, OSError) as exc:
                last_error = exc
                if attempt < self.MAX_RETRIES:
                    # Prepare for retry — update resume offset
                    if dest.exists():
                        resume_bytes = dest.stat().st_size
                        headers["Range"] = f"bytes={resume_bytes}-"

        raise DownloadError(
            f"Download failed after {self.MAX_RETRIES} attempts: {last_error}"
        ) from last_error

    # -------------------------------------------------------------------------
    # Checksum verification
    # -------------------------------------------------------------------------

    @staticmethod
    def verify_checksum(file_path: str, expected: str, algo: str = "sha256") -> None:
        """
        Compute the hash of *file_path* and compare against *expected*.

        Raises :class:`ChecksumMismatch` when they differ.
        """
        try:
            h = hashlib.new(algo)
        except ValueError as exc:
            raise ValueError(f"Unsupported hash algorithm: {algo!r}") from exc

        with open(file_path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 17), b""):
                h.update(chunk)

        actual = h.hexdigest()
        if actual.lower() != expected.lower().split()[0]:   # strip filename if present
            raise ChecksumMismatch(expected=expected, actual=actual)

    @staticmethod
    def fetch_checksum_from_file(
        checksum_url: str,
        filename_pattern: str,
        algo: str = "sha256",
        cancel_event: Optional[threading.Event] = None,
    ) -> Optional[str]:
        """
        Download a checksum index file and extract the hash for *filename_pattern*.

        Handles both:
        * Ubuntu-style ``SHA256SUMS``: ``<hash>  <filename>``
        * Simple single-hash files:   ``<hash>  <filename>``  or just ``<hash>``

        Returns the hex digest string, or *None* if not found.
        """
        try:
            resp = requests.get(
                checksum_url,
                timeout=(15, 30),
                stream=False,
            )
            resp.raise_for_status()
        except requests.RequestException:
            return None

        if cancel_event and cancel_event.is_set():
            return None

        content = resp.text
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) == 1:
                # File contains only a bare hash
                return parts[0]
            # parts[0] = hash, parts[1] = filename (may have leading '*' or space)
            candidate_name = parts[-1].lstrip("*").strip()
            if filename_pattern in candidate_name or candidate_name in filename_pattern:
                return parts[0]

        return None

    # -------------------------------------------------------------------------
    # Archive extraction helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def extract_appx(appx_path: str, output_dir: str) -> Optional[str]:
        """Extract an APPX package (ZIP format) and locate the rootfs tar inside.

        APPX packages distributed through the Microsoft Store are standard ZIP
        archives.  This method extracts the archive and searches for the
        inner rootfs tarball (commonly ``install.tar.gz``, ``rootfs.tar.gz``,
        or ``*.tar`` files).

        Args:
            appx_path: Absolute path to the ``.appx`` file.
            output_dir: Directory to extract the APPX contents into.  Created
                if it does not exist.

        Returns:
            The absolute path to the inner rootfs tar file if found,
            or ``None`` if no matching archive was discovered.
        """
        import zipfile

        Path(output_dir).mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(appx_path, "r") as zf:
            _safe_extract_zip(zf, output_dir)

        # Search for known rootfs archive names (fast path)
        for name in ("install.tar.gz", "rootfs.tar.gz", "install.tar"):
            candidate = Path(output_dir) / name
            if candidate.exists():
                return str(candidate)

        # Broader fallback search for any .tar.gz or .tar file
        for p in Path(output_dir).rglob("*.tar.gz"):
            return str(p)
        for p in Path(output_dir).rglob("*.tar"):
            return str(p)

        return None

    @staticmethod
    def extract_arch_bootstrap(
        archive_path: str,
        output_tar_path: str,
        progress_cb: Optional[ProgressCallback] = None,
    ) -> str:
        """Extract an Arch Linux bootstrap archive and repack it for ``wsl --import``.

        The official Arch Linux bootstrap tarball contains a ``root.x86_64/``
        directory at the archive root, but ``wsl --import`` expects the
        root filesystem to be at the archive root (no top-level directory).
        This method:

        1. Decompresses the outer archive (``tar.gz`` or ``tar.zst``) to a
           temporary directory.
        2. Locates the ``root.*/`` directory inside.
        3. Repacks that directory as a plain ``tar.gz`` with ``.`` as the
           archive root (so ``wsl --import`` sees the rootfs directly).

        ``.zst`` archives are decompressed using the ``zstandard`` Python
        library (listed in ``requirements.txt``), avoiding reliance on a
        system ``tar`` that may not support ``--zstd`` on Windows.

        Args:
            archive_path: Absolute path to the Arch bootstrap archive
                (``.tar.gz`` or ``.tar.zst``).
            output_tar_path: Destination path for the repacked ``.tar.gz``.
            progress_cb: Optional progress callback (currently unused;
                reserved for future streaming decompression).

        Returns:
            The *output_tar_path* (same as the argument), confirming success.

        Raises:
            DownloadError: If the ``root.*/`` directory cannot be located
                inside the extracted archive.
        """
        import tarfile
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            # Stage 1: decompress outer archive
            if archive_path.endswith(".zst"):
                # Use the 'zstandard' Python library (in requirements.txt).
                # Avoids relying on a system 'tar' that may not support --zstd on Windows.
                import zstandard as zstd

                inner_tar = Path(tmpdir) / "arch.tar"
                with open(archive_path, "rb") as fh_in:
                    dctx = zstd.ZstdDecompressor()
                    with inner_tar.open("wb") as fh_out:
                        dctx.copy_stream(fh_in, fh_out)
                with tarfile.open(str(inner_tar), "r:") as tf:
                    _safe_extract_tar(tf, tmpdir)
            else:
                with tarfile.open(archive_path, "r:*") as tf:
                    _safe_extract_tar(tf, tmpdir)

            # Stage 2: locate the root.*/ directory inside the extracted tree
            root_dir: Optional[Path] = None
            for item in Path(tmpdir).iterdir():
                if item.is_dir() and item.name.startswith("root."):
                    root_dir = item
                    break

            if root_dir is None:
                raise DownloadError(
                    "Could not locate root directory in Arch bootstrap archive."
                )

            # Stage 3: repack as a plain tar.gz with the rootfs at archive root
            with tarfile.open(output_tar_path, "w:gz") as tf:
                tf.add(str(root_dir), arcname=".")

        return output_tar_path
