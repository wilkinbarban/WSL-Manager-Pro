"""
Unit tests for :mod:`core.downloader` with mocked HTTP (no external network).

Covers:
* ``verify_checksum`` — Match and mismatch scenarios.
* ``download`` — Full download (HTTP 200) with checksum verification.
* ``download`` — Resume download (HTTP 206) appending to partial file.
* ``download`` — HTTP error (500) raising ``DownloadError``.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.downloader import ChecksumMismatch, DownloadError, DownloadManager


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_verify_checksum_match_and_mismatch(tmp_path: Path) -> None:
    data = b"hello-wsl-test"
    path = tmp_path / "f.bin"
    path.write_bytes(data)
    good = _sha256_hex(data)
    DownloadManager.verify_checksum(str(path), good, "sha256")
    with pytest.raises(ChecksumMismatch):
        DownloadManager.verify_checksum(str(path), "0" * 64, "sha256")


def test_download_full_200_with_checksum(tmp_path: Path) -> None:
    body = b"full-payload"
    digest = _sha256_hex(body)
    dest = tmp_path / "out.bin"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Length": str(len(body))}

    def iter_content(chunk_size: int = 0):
        yield body

    mock_resp.iter_content = iter_content
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = lambda *a: None

    with patch("core.downloader.requests.get", return_value=mock_resp) as get:
        dm = DownloadManager()
        out = dm.download("http://example.test/file", str(dest), checksum=digest, algo="sha256")
    get.assert_called_once()
    assert out.read_bytes() == body


def test_download_resume_206_appends(tmp_path: Path) -> None:
    prefix = b"aaa"
    suffix = b"bbb"
    dest = tmp_path / "partial.bin"
    dest.write_bytes(prefix)
    full = prefix + suffix
    digest = _sha256_hex(full)

    mock_resp = MagicMock()
    mock_resp.status_code = 206
    mock_resp.headers = {"Content-Length": str(len(suffix))}

    def iter_content(chunk_size: int = 0):
        yield suffix

    mock_resp.iter_content = iter_content
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = lambda *a: None

    with patch("core.downloader.requests.get", return_value=mock_resp):
        dm = DownloadManager()
        out = dm.download(
            "http://example.test/resume",
            str(dest),
            checksum=digest,
            algo="sha256",
            resume_bytes=len(prefix),
        )
    assert out.read_bytes() == full


def test_download_http_error_raises(tmp_path: Path) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = lambda *a: None

    with patch("core.downloader.requests.get", return_value=mock_resp):
        dm = DownloadManager()
        with pytest.raises(DownloadError, match="HTTP 500"):
            dm.download("http://example.test/bad", str(tmp_path / "x.bin"))
