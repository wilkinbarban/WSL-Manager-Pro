"""
Tests for :mod:`utils.i18n` runtime internationalisation.

Covers:
* English fallback when key is not in the catalog.
* Translation of known keys in Spanish and Portuguese.
* Invalid language code falling back to English.
* UTF-8 encoding integrity (no mojibake markers in bundles).
"""
from __future__ import annotations

import json
from pathlib import Path

from utils.i18n import get_i18n, t


def test_i18n_falls_back_to_key_for_english() -> None:
    i18n = get_i18n()
    i18n.set_language("en")
    assert t("Install") == "Install"


def test_i18n_translates_known_key() -> None:
    i18n = get_i18n()
    i18n.set_language("es")
    assert t("Install") == "Instalar"
    i18n.set_language("pt")
    assert t("Settings") == "Configurações"


def test_i18n_invalid_language_falls_back_to_english() -> None:
    i18n = get_i18n()
    i18n.set_language("xx")
    assert i18n.language == "en"


def test_i18n_bundles_have_no_mojibake_markers() -> None:
    markers = (chr(0x00C3), chr(0x00C2), chr(0x00E2), chr(0xFFFD))
    for lang in ("es", "pt"):
        path = Path(f"resources/i18n/{lang}.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        for key, value in data.items():
            assert not any(marker in key for marker in markers)
            assert isinstance(value, str)
            assert not any(marker in value for marker in markers)


def test_i18n_english_catalog_covers_translated_keys() -> None:
    base = json.loads(Path("resources/i18n/en.json").read_text(encoding="utf-8"))
    assert base
    for lang in ("es", "pt"):
        data = json.loads(Path(f"resources/i18n/{lang}.json").read_text(encoding="utf-8"))
        assert set(data) <= set(base)
