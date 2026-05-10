"""
Tests for :mod:`core.catalog_loader`.

Covers:
* Valid local catalog loading with minimal entries.
* Skipping of invalid entries (wrong types, missing fields) with warnings.
* Optional ``checksum_file_pattern`` acceptance.
* Remote catalog merge (remote overrides local, fallback on network error).
* Partial remote catalog with some valid and some invalid entries.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from core.catalog_loader import load_catalog


def _write_catalog(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_load_catalog_local_valid_minimal(tmp_path: Path) -> None:
    catalog_path = tmp_path / "distros.json"
    _write_catalog(
        catalog_path,
        {
            "ubuntu": {
                "display_name": "Ubuntu",
                "description": "Stable Ubuntu",
                "url": "https://example.test/ubuntu.tar.gz",
                "extract_type": "tar.gz",
            }
        },
    )

    result = load_catalog(catalog_path)
    assert result.source == "local"
    assert result.entries["ubuntu"]["url"] == "https://example.test/ubuntu.tar.gz"
    assert result.warnings == []


def test_load_catalog_skips_invalid_entries(tmp_path: Path) -> None:
    catalog_path = tmp_path / "distros.json"
    _write_catalog(
        catalog_path,
        {
            "good-online": {
                "display_name": "Good",
                "description": "Official distro",
                "install_method": "wsl_online",
                "online_name": "Ubuntu",
            },
            "bad-online": {
                "display_name": "Broken",
                "description": "Missing online name",
                "install_method": "wsl_online",
            },
            "bad-extract": {
                "display_name": "Broken 2",
                "description": "Bad type",
                "url": "https://example.test/bad.tar",
                "extract_type": "rar",
            },
        },
    )

    result = load_catalog(catalog_path)
    assert list(result.entries) == ["good-online"]
    assert any("bad-online" in warning for warning in result.warnings)
    assert any("bad-extract" in warning for warning in result.warnings)


def test_load_catalog_accepts_checksum_url_without_pattern(tmp_path: Path) -> None:
    catalog_path = tmp_path / "distros.json"
    _write_catalog(
        catalog_path,
        {
            "alpine": {
                "display_name": "Alpine",
                "description": "Lightweight distro",
                "url": "https://example.test/alpine.tar.gz",
                "extract_type": "tar.gz",
                "checksum_url": "https://example.test/alpine.tar.gz.sha256",
                "checksum_file_pattern": None,
            }
        },
    )

    result = load_catalog(catalog_path)
    assert result.entries["alpine"]["checksum_url"] == "https://example.test/alpine.tar.gz.sha256"
    assert result.entries["alpine"]["checksum_file_pattern"] is None


def test_load_catalog_remote_merge_overrides_local(tmp_path: Path) -> None:
    catalog_path = tmp_path / "distros.json"
    _write_catalog(
        catalog_path,
        {
            "ubuntu": {
                "display_name": "Ubuntu local",
                "description": "Local description",
                "url": "https://example.test/local.tar.gz",
                "extract_type": "tar.gz",
            }
        },
    )

    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "ubuntu": {
            "display_name": "Ubuntu remote",
            "description": "Remote override",
            "url": "https://example.test/remote.tar.gz",
            "extract_type": "tar.gz",
        },
        "debian": {
            "display_name": "Debian",
            "description": "Remote add",
            "url": "https://example.test/debian.tar",
            "extract_type": "tar",
        },
    }

    with patch("core.catalog_loader.requests.get", return_value=response):
        result = load_catalog(catalog_path, remote_url="https://catalog.test/distros.json")

    assert result.source == "remote-merged"
    assert result.entries["ubuntu"]["description"] == "Remote override"
    assert "debian" in result.entries
    assert any("without signature verification" in warning for warning in result.warnings)


def test_load_catalog_remote_failure_falls_back_to_local(tmp_path: Path) -> None:
    catalog_path = tmp_path / "distros.json"
    _write_catalog(
        catalog_path,
        {
            "ubuntu": {
                "display_name": "Ubuntu",
                "description": "Local only",
                "url": "https://example.test/local.tar.gz",
                "extract_type": "tar.gz",
            }
        },
    )

    with patch("core.catalog_loader.requests.get", side_effect=requests.RequestException("boom")):
        result = load_catalog(catalog_path, remote_url="https://catalog.test/distros.json")

    assert result.source == "remote-fallback"
    assert list(result.entries) == ["ubuntu"]
    assert any("remote catalog fetch failed" in warning for warning in result.warnings)


def test_load_catalog_remote_partial_invalid_keeps_valid_entries(tmp_path: Path) -> None:
    catalog_path = tmp_path / "distros.json"
    _write_catalog(
        catalog_path,
        {
            "ubuntu": {
                "display_name": "Ubuntu",
                "description": "Local entry",
                "url": "https://example.test/local.tar.gz",
                "extract_type": "tar.gz",
            }
        },
    )

    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "good": {
            "display_name": "Fedora",
            "description": "Valid remote entry",
            "url": "https://example.test/fedora.tar.xz",
            "extract_type": "tar.xz",
        },
        "bad": {
            "display_name": "Broken",
            "description": "",
            "url": "https://example.test/bad.tar.gz",
            "extract_type": "tar.gz",
        },
    }

    with patch("core.catalog_loader.requests.get", return_value=response):
        result = load_catalog(catalog_path, remote_url="https://catalog.test/distros.json")

    assert result.source == "remote-merged"
    assert "good" in result.entries
    assert "bad" not in result.entries
    assert any("remote catalog: skipped 'bad'" in warning for warning in result.warnings)
