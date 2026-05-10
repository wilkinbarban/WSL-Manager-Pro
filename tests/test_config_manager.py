"""
Tests for :mod:`utils.config_manager`.

Covers:
* Default values when config file is missing.
* Schema v1 → v2 automatic migration and persistence.
* Invalid scalar values falling back to defaults with warnings.
* Invalid nested entries (download states, installed distros) being skipped.
* ``ConfigValidationError`` raised on invalid config during save.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from utils.config_manager import (
    SCHEMA_VERSION,
    AppConfig,
    ConfigManager,
    ConfigValidationError,
)


def test_config_manager_defaults_when_file_missing(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    mgr = ConfigManager(path=cfg_path)
    assert mgr.config == AppConfig()
    assert mgr.startup_warnings == []
    assert mgr.startup_infos == []
    assert mgr.config.language == "en"


def test_config_manager_migrates_v1_to_v2(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps(
            {
                "install_dir": r"D:\WSL\Distros",
                "download_dir": r"D:\WSL\Cache",
                "language": "pt",
                "memory_limit_gb": 8,
                "swap_size_gb": 4,
                "processors": 6,
                "auto_refresh_interval_sec": 30,
                "wsl_version": 2,
                "diagnostic_log_tail_lines": 250,
            }
        ),
        encoding="utf-8",
    )

    mgr = ConfigManager(path=cfg_path)
    assert mgr.config.schema_version == SCHEMA_VERSION
    assert mgr.config.language == "pt"
    assert mgr.config.remote_catalog_url == ""
    assert mgr.config.run_as_admin is True
    assert mgr.config.check_for_updates is False
    assert mgr.config.update_repo_url == ""
    assert mgr.config.localhost_forwarding is True
    assert mgr.config.vm_idle_timeout_sec == 60
    assert any("schema v1" in info for info in mgr.startup_infos)
    persisted = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert persisted["schema_version"] == SCHEMA_VERSION


def test_config_manager_invalid_values_fallback_and_skip_bad_entries(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "language": "de",
                "install_dir": 123,
                "download_dir": "",
                "remote_catalog_url": 9,
                "run_as_admin": "yes",
                "check_for_updates": "no",
                "update_repo_url": 7,
                "memory_limit_gb": 0,
                "swap_size_gb": -1,
                "processors": 0,
                "localhost_forwarding": "true",
                "vm_idle_timeout_sec": 0,
                "auto_refresh_interval_sec": 0,
                "wsl_version": 3,
                "diagnostic_log_tail_lines": 0,
                "download_states": {
                    "https://ok.test/rootfs.tar.gz": {
                        "url": "https://ok.test/rootfs.tar.gz",
                        "dest_path": r"C:\cache\rootfs.tar.gz",
                        "bytes_downloaded": 7,
                        "total_bytes": 10,
                        "completed": False,
                    },
                    "bad": {
                        "url": "bad",
                        "dest_path": 77,
                    },
                },
                "installed_distros": [
                    {
                        "name": "Ubuntu",
                        "distro_id": "ubuntu",
                        "install_dir": r"C:\WSL\Ubuntu",
                        "installed_at": "2026-05-05T00:00:00",
                        "username": "dev",
                    },
                    {
                        "name": "Broken",
                        "distro_id": 9,
                        "install_dir": r"C:\WSL\Broken",
                        "installed_at": "2026-05-05T00:00:00",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    mgr = ConfigManager(path=cfg_path)
    assert mgr.config.install_dir == AppConfig().install_dir
    assert mgr.config.language == "en"
    assert mgr.config.download_dir == AppConfig().download_dir
    assert mgr.config.remote_catalog_url == ""
    assert mgr.config.run_as_admin is True
    assert mgr.config.check_for_updates is False
    assert mgr.config.update_repo_url == ""
    assert mgr.config.memory_limit_gb == AppConfig().memory_limit_gb
    assert mgr.config.swap_size_gb == AppConfig().swap_size_gb
    assert mgr.config.processors == AppConfig().processors
    assert mgr.config.localhost_forwarding is True
    assert mgr.config.vm_idle_timeout_sec == 60
    assert mgr.config.auto_refresh_interval_sec == AppConfig().auto_refresh_interval_sec
    assert mgr.config.wsl_version == AppConfig().wsl_version
    assert mgr.config.diagnostic_log_tail_lines == AppConfig().diagnostic_log_tail_lines
    assert list(mgr.config.download_states) == ["https://ok.test/rootfs.tar.gz"]
    assert len(mgr.config.installed_distros) == 1
    assert len(mgr.startup_warnings) >= 8


def test_config_manager_save_rejects_invalid_data(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    mgr = ConfigManager(path=cfg_path)
    mgr.config.install_dir = ""
    with pytest.raises(ConfigValidationError):
        mgr.save()
    assert not cfg_path.exists()
