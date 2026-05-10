"""
core/catalog_loader.py
======================

Validates and loads WSL distribution catalogs from local JSON files and
optionally merges them with remote catalogs fetched via HTTP.

The catalog schema enforces strict typing for each distro entry:
  * ``install_method`` — ``"rootfs"`` (direct download) or ``"wsl_online"``
    (use ``wsl --install -d <name>``).
  * ``extract_type`` — One of ``tar``, ``tar.gz``, ``tar.xz``, ``tar.zst``,
    ``appx``, ``zip`` (for ``rootfs`` method only).
  * ``pkg_manager`` — ``apt``, ``dnf``, ``zypper``, ``pacman``, ``apk``.
  * ``algo`` — Checksum algorithm: ``sha256``, ``sha512``, ``md5``.
  * ``checksum_url`` / ``checksum_file_pattern`` — Integrity verification.
  * ``packages`` — Default packages to install post-import.
  * ``systemd`` — Whether systemd boot support is available.
  * ``legacy_non_interactive_disable`` — Metadata for distros that require
    interactive first-boot (e.g., Oracle Linux, SUSE Enterprise).

Invalid entries are **skipped** with warnings rather than aborting the
entire load, ensuring the application can still start with a partially
valid catalog.

Key functions
-------------
* :func:`load_catalog` — Main entry point combining local + remote catalogs.
* :func:`validate_catalog` — Validates a raw dict payload.
* :func:`_normalize_catalog_entry` — Per-entry validation and coercion.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import requests

from core.constants import CATALOG_TIMEOUT

#: Valid values for ``extract_type`` field in distro catalog entries.
#: Determines how the downloaded archive is unpacked during import.
ALLOWED_EXTRACT_TYPES: set[str] = {"tar", "tar.gz", "tar.xz", "tar.zst", "appx", "zip"}

#: Valid values for ``install_method`` field in distro catalog entries.
#: ``"rootfs"`` = download tarball + ``wsl --import``.
#: ``"wsl_online"`` = ``wsl --install -d <name>`` from Microsoft Store catalog.
ALLOWED_INSTALL_METHODS: set[str] = {"rootfs", "wsl_online"}


@dataclass
class CatalogLoadResult:
    """Validated catalog entries plus load metadata.

    Attributes
    ----------
    entries : dict[str, dict[str, Any]]
        Keyed by distro ID (e.g. ``"ubuntu-2404"``), each value is a
        normalised distro config dict.
    warnings : list[str]
        Human-readable warnings collected during validation (skipped entries,
        parse errors, etc.).
    source : str
        Load source identifier:
        * ``"local"`` — only the on-disk ``distros.json`` was used.
        * ``"remote-merged"`` — local + remote catalog merged successfully.
        * ``"remote-fallback"`` — remote fetch failed; local catalog used.
    """

    entries: dict[str, dict[str, Any]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    source: str = "local"


def _require_string(
    value: Any,
    field_name: str,
    *,
    allow_empty: bool = False,
) -> str:
    """Validate that *value* is a non-empty (by default) string.

    Args:
        value: The raw value from the catalog JSON.
        field_name: Name of the field (used in error messages).
        allow_empty: If ``True``, empty strings are accepted.

    Returns:
        The stripped string.

    Raises:
        ValueError: If *value* is not a ``str``, or if it is empty and
            *allow_empty* is ``False``.
    """
    if not isinstance(value, str):
        raise ValueError(f"'{field_name}' must be a string.")
    result = value.strip()
    if not allow_empty and not result:
        raise ValueError(f"'{field_name}' must not be empty.")
    return result


def _optional_string(value: Any, field_name: str) -> Optional[str]:
    """Validate an optional string field.

    Args:
        value: The raw value from the catalog JSON.
        field_name: Name of the field (used in error messages).

    Returns:
        The stripped string, or ``None`` if *value* is ``None`` or missing.

    Raises:
        ValueError: If *value* is not ``None`` and not a valid non-empty string.
    """
    if value is None:
        return None
    return _require_string(value, field_name)


def _normalize_catalog_entry(key: str, raw_entry: Any) -> dict[str, Any]:
    """Normalise and validate a single distribution catalog entry.

    Enforces the catalog schema:

    * ``install_method`` must be ``"rootfs"`` or ``"wsl_online"``.
    * For ``rootfs``: ``url`` and ``extract_type`` are required.
    * For ``wsl_online``: ``online_name`` is required (must match the
      exact name shown by ``wsl --list --online``).
    * Optional fields are coerced or omitted when absent.
    * ``packages`` is validated as a list of non-empty strings.
    * Boolean fields (``systemd``, ``legacy_non_interactive_disable``) are
      type-checked.

    Args:
        key: The catalog key (distro ID, e.g. ``"ubuntu-2404"``).
        raw_entry: Raw JSON object for this distro.

    Returns:
        A normalised ``dict`` with only the validated fields present.

    Raises:
        ValueError: If any required field is missing, has the wrong type,
            or contains an invalid value.
    """
    if not isinstance(raw_entry, dict):
        raise ValueError("entry must be an object.")

    # --- install_method (required) ---
    install_method = raw_entry.get("install_method", "rootfs")
    install_method = _require_string(install_method, "install_method")
    if install_method not in ALLOWED_INSTALL_METHODS:
        raise ValueError(
            f"install_method must be one of {sorted(ALLOWED_INSTALL_METHODS)}."
        )

    normalized: dict[str, Any] = {
        "display_name": _require_string(raw_entry.get("display_name"), "display_name"),
        "description": _require_string(raw_entry.get("description"), "description"),
        "install_method": install_method,
    }

    # --- Method-dependent required fields ---
    if install_method == "wsl_online":
        # Online installs only need the catalog name
        normalized["online_name"] = _require_string(raw_entry.get("online_name"), "online_name")
    else:
        # Rootfs installs need download URL and extraction type
        normalized["url"] = _require_string(raw_entry.get("url"), "url")
        extract_type = raw_entry.get("extract_type", "tar.gz")
        extract_type = _require_string(extract_type, "extract_type")
        if extract_type not in ALLOWED_EXTRACT_TYPES:
            raise ValueError(
                f"extract_type must be one of {sorted(ALLOWED_EXTRACT_TYPES)}."
            )
        normalized["extract_type"] = extract_type

    # --- Optional string fields ---
    optional_string_fields = (
        "pkg_manager",
        "sudo_group",
        "winget_id",
        "algo",
        "checksum_url",
        "checksum_file_pattern",
        "notes",
    )
    for field_name in optional_string_fields:
        if field_name in raw_entry:
            normalized[field_name] = _optional_string(raw_entry.get(field_name), field_name)

    # --- Optional boolean fields ---
    if "systemd" in raw_entry:
        if not isinstance(raw_entry["systemd"], bool):
            raise ValueError("'systemd' must be a boolean.")
        normalized["systemd"] = raw_entry["systemd"]

    if "legacy_non_interactive_disable" in raw_entry:
        if not isinstance(raw_entry["legacy_non_interactive_disable"], bool):
            raise ValueError("'legacy_non_interactive_disable' must be a boolean.")
        normalized["legacy_non_interactive_disable"] = raw_entry["legacy_non_interactive_disable"]

    # --- Optional packages list ---
    if "packages" in raw_entry:
        packages = raw_entry["packages"]
        if not isinstance(packages, list) or any(
            not isinstance(item, str) or not item.strip()
            for item in packages
        ):
            raise ValueError("'packages' must be a list of non-empty strings.")
        normalized["packages"] = [item.strip() for item in packages]

    return normalized


def validate_catalog(raw_catalog: Any, *, source_name: str) -> CatalogLoadResult:
    """Validate a raw catalog payload, skipping invalid entries with warnings.

    This is the main validation entry point.  It iterates over every key in
    the catalog dict and passes each value through
    :func:`_normalize_catalog_entry`.  Entries that fail validation are
    **skipped** (not included in the result) and a warning is recorded.
    This ensures the application can still start even if the catalog has a
    few malformed entries.

    Args:
        raw_catalog: Parsed JSON object (``dict`` expected at top level).
        source_name: Human-readable label for the catalog source (e.g.
            ``"local catalog"`` or ``"remote catalog"``).  Used in warning
            messages.

    Returns:
        A :class:`CatalogLoadResult` with the successfully validated entries
        and any warnings.
    """

    result = CatalogLoadResult()
    if not isinstance(raw_catalog, dict):
        result.warnings.append(f"{source_name}: catalog root must be an object.")
        return result

    for key, raw_entry in raw_catalog.items():
        if not isinstance(key, str) or not key.strip():
            result.warnings.append(f"{source_name}: skipped catalog entry with invalid key.")
            continue
        try:
            result.entries[key] = _normalize_catalog_entry(key, raw_entry)
        except ValueError as exc:
            result.warnings.append(f"{source_name}: skipped '{key}': {exc}")
    return result


def _load_local_catalog(local_path: Path) -> CatalogLoadResult:
    """Read and parse the on-disk ``distros.json`` catalog file.

    Args:
        local_path: Absolute path to the local catalog JSON file.

    Returns:
        A :class:`CatalogLoadResult` with source set to ``"local"``.
        On file-read or JSON-parse errors the result contains zero entries
        and a warning describing the failure.
    """
    try:
        raw_text = local_path.read_text(encoding="utf-8")
    except OSError as exc:
        return CatalogLoadResult(
            warnings=[f"local catalog '{local_path}' could not be read: {exc}"],
            source="local",
        )
    try:
        raw_catalog = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return CatalogLoadResult(
            warnings=[f"local catalog '{local_path}' is not valid JSON: {exc}"],
            source="local",
        )
    result = validate_catalog(raw_catalog, source_name="local catalog")
    result.source = "local"
    return result


def _load_remote_catalog(remote_url: str) -> CatalogLoadResult:
    """Fetch and parse a remote distro catalog via HTTP.

    Args:
        remote_url: Full URL to the remote catalog JSON endpoint.

    Returns:
        A :class:`CatalogLoadResult`.  On success the source is
        ``"remote-merged"``; on any network or parse error the result
        contains zero entries and the source is ``"remote-fallback"``
        (so the caller knows to use the local catalog only).
    """
    try:
        response = requests.get(remote_url, timeout=CATALOG_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        return CatalogLoadResult(
            warnings=[f"remote catalog fetch failed: {exc}"],
            source="remote-fallback",
        )

    try:
        raw_catalog = response.json()
    except ValueError:
        try:
            raw_catalog = json.loads(response.text)
        except json.JSONDecodeError as exc:
            return CatalogLoadResult(
                warnings=[f"remote catalog is not valid JSON: {exc}"],
                source="remote-fallback",
            )

    result = validate_catalog(raw_catalog, source_name="remote catalog")
    result.source = "remote-merged"
    return result


def load_catalog(local_path: Path, remote_url: str = "") -> CatalogLoadResult:
    """Load and merge the local and (optionally) remote distro catalogs.

    This is the **main entry point** for catalog loading.  It always loads
    the local ``distros.json`` first.  If *remote_url* is non-empty, it
    fetches the remote catalog and **merges** its entries over the local
    ones — remote entries with the same distro ID override local entries.

    .. note::

        Remote catalogs are loaded **without cryptographic signature
        verification** in this phase.  A warning is appended to the result
        to remind the user.

    Args:
        local_path: Absolute path to the on-disk ``distros.json``.
        remote_url: Optional URL to a remote catalog.  Empty string means
            local-only mode.

    Returns:
        A :class:`CatalogLoadResult` with the merged entries and all
        collected warnings.
    """

    local_result = _load_local_catalog(local_path)
    if not remote_url.strip():
        return local_result

    remote_result = _load_remote_catalog(remote_url.strip())
    if remote_result.source != "remote-merged":
        return CatalogLoadResult(
            entries=dict(local_result.entries),
            warnings=local_result.warnings + remote_result.warnings,
            source="remote-fallback",
        )

    merged = dict(local_result.entries)
    merged.update(remote_result.entries)
    warnings = list(local_result.warnings)
    warnings.extend(remote_result.warnings)
    warnings.append(
        "Remote catalog loaded without signature verification; use under your own responsibility."
    )
    return CatalogLoadResult(entries=merged, warnings=warnings, source="remote-merged")
