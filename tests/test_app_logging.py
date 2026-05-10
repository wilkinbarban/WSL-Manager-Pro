"""
Tests for :mod:`utils.app_logging`.

Covers:
* ``log_level_for_ui_line`` — Mapping UI colour/text hints to logging levels.
* ``configure_logging`` — Rotating file handler creation, idempotency, and
  log message persistence.
"""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

import pytest

from utils import app_logging as al


def test_log_level_for_ui_line() -> None:
    assert al.log_level_for_ui_line("hello", "") == logging.INFO
    assert al.log_level_for_ui_line("[ERROR] x", "") == logging.ERROR
    assert al.log_level_for_ui_line("x", "#F44336") == logging.ERROR
    assert al.log_level_for_ui_line("[WARNING] y", "") == logging.WARNING


def test_configure_logging_creates_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(al, "log_dir", lambda: tmp_path / "logs")
    log = al.get_logger()
    log.handlers.clear()
    al.configure_logging()
    log2 = al.configure_logging()
    assert log2 is log
    assert any(isinstance(h, logging.handlers.RotatingFileHandler) for h in log.handlers)
    log.info("test_message_unique_12345")
    files = list((tmp_path / "logs").glob("*.log"))
    assert files, "app.log should exist"
    assert any(b"test_message_unique_12345" in p.read_bytes() for p in files)
