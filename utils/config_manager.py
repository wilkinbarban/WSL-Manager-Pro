"""
utils/config_manager.py
=======================

Persistent JSON configuration for WSL Manager Pro.

Stores application settings, download resume states, and a registry of
distributions installed through this application.  All writes go through
strict validation; reads are lenient with safe fallbacks.

**Config file location:**
    * Windows — ``%APPDATA%\\WSLManagerPro\\config.json``
    * Linux   — ``~/.config/wslmanagerpro/config.json``

**Schema versioning:**
    * Current version: :data:`SCHEMA_VERSION` = 2.
    * v1 → v2 migration is automatic and transparent.  Missing fields are
      populated with defaults; the migrated config is saved back to disk.

**Design principles:**
    * **Strict on save** — :func:`validate_config_data` rejects any invalid
      values before writing to disk.
    * **Lenient on load** — :func:`normalize_loaded_config` falls back to
      defaults for invalid scalar values and skips invalid nested entries.
    * **Auto-persist on migration** — If the config was migrated or
      corrected, the corrected version is saved automatically.

Key classes
-----------
* :class:`ConfigManager` — Main facade for reading and writing config.
* :class:`AppConfig` — Dataclass holding all configurable values.
* :class:`InstalledDistro` — Record of a distro installed by this app.
* :class:`DownloadState` — Resume metadata for a partial download.
* :class:`ConfigLoadResult` — Wrapper for load results with warnings.
* :class:`ConfigValidationError` — Raised on invalid config data.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from utils.i18n import SUPPORTED_LANGUAGES

#: Current config schema version.  Increment when adding required fields or
#: changing the structure of existing fields.
SCHEMA_VERSION: int = 2


class ConfigValidationError(ValueError):
    """Raised when configuration data cannot be validated for persistence."""


# ---------------------------------------------------------------------------
# Config directory
# ---------------------------------------------------------------------------

def _config_dir() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    path = base / "WSLManagerPro"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _default_install_dir() -> str:
    return r"C:\WSL\Distros"


def _default_download_dir() -> str:
    return r"C:\WSL\Cache"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class DownloadState:
    """Tracks a partial or completed download to support resuming."""

    url: str
    dest_path: str
    bytes_downloaded: int = 0
    total_bytes: int = 0
    checksum: Optional[str] = None
    completed: bool = False


@dataclass
class InstalledDistro:
    """Records a distro installed by this application."""

    name: str
    distro_id: str
    install_dir: str
    installed_at: str
    username: str = ""


@dataclass
class AppConfig:
    schema_version: int = SCHEMA_VERSION
    language: str = "en"
    install_dir: str = field(default_factory=_default_install_dir)
    download_dir: str = field(default_factory=_default_download_dir)
    remote_catalog_url: str = ""
    run_as_admin: bool = True
    check_for_updates: bool = False
    update_repo_url: str = ""
    memory_limit_gb: int = 4
    swap_size_gb: int = 2
    processors: int = 2
    localhost_forwarding: bool = True
    vm_idle_timeout_sec: int = 60
    auto_refresh_interval_sec: int = 15
    wsl_version: int = 2
    diagnostic_log_tail_lines: int = 200
    download_states: dict[str, DownloadState] = field(default_factory=dict)
    installed_distros: list[InstalledDistro] = field(default_factory=list)


@dataclass
class ConfigLoadResult:
    """Result of loading config from disk with normalized warnings."""

    config: AppConfig
    warnings: list[str] = field(default_factory=list)
    infos: list[str] = field(default_factory=list)
    should_persist: bool = False


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def migrate_v1_to_v2(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Migrate the legacy schema (without ``schema_version``) to v2."""

    migrated = dict(raw)
    infos = [
        "config.json schema v1 detected; migrated automatically to schema_version=2."
    ]
    migrated["schema_version"] = SCHEMA_VERSION
    migrated.setdefault("language", "en")
    migrated.setdefault("remote_catalog_url", "")
    migrated.setdefault("run_as_admin", True)
    migrated.setdefault("check_for_updates", False)
    migrated.setdefault("update_repo_url", "")
    migrated.setdefault("localhost_forwarding", True)
    migrated.setdefault("vm_idle_timeout_sec", 60)
    return migrated, infos


def _expect_dict(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigValidationError(f"'{field_name}' must be an object.")
    return value


def _validate_string(
    value: Any,
    field_name: str,
    *,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise ConfigValidationError(f"'{field_name}' must be a string.")
    result = value.strip()
    if not allow_empty and not result:
        raise ConfigValidationError(f"'{field_name}' must not be empty.")
    return result


def _validate_int(
    value: Any,
    field_name: str,
    *,
    minimum: int,
    maximum: Optional[int] = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigValidationError(f"'{field_name}' must be an integer.")
    if value < minimum:
        raise ConfigValidationError(f"'{field_name}' must be >= {minimum}.")
    if maximum is not None and value > maximum:
        raise ConfigValidationError(f"'{field_name}' must be <= {maximum}.")
    return value


def _validate_optional_string(value: Any, field_name: str) -> Optional[str]:
    if value is None:
        return None
    return _validate_string(value, field_name, allow_empty=False)


def _validate_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigValidationError(f"'{field_name}' must be a boolean.")
    return value


def _validate_language(value: Any, field_name: str) -> str:
    language = _validate_string(value, field_name)
    if language not in SUPPORTED_LANGUAGES:
        raise ConfigValidationError(
            f"'{field_name}' must be one of {', '.join(SUPPORTED_LANGUAGES)}."
        )
    return language


def _validate_download_state(data: Any, key: str) -> DownloadState:
    payload = _expect_dict(data, f"download_states[{key!r}]")
    return DownloadState(
        url=_validate_string(payload.get("url"), f"download_states[{key!r}].url"),
        dest_path=_validate_string(
            payload.get("dest_path"), f"download_states[{key!r}].dest_path"
        ),
        bytes_downloaded=_validate_int(
            payload.get("bytes_downloaded", 0),
            f"download_states[{key!r}].bytes_downloaded",
            minimum=0,
        ),
        total_bytes=_validate_int(
            payload.get("total_bytes", 0),
            f"download_states[{key!r}].total_bytes",
            minimum=0,
        ),
        checksum=_validate_optional_string(
            payload.get("checksum"), f"download_states[{key!r}].checksum"
        ),
        completed=bool(payload.get("completed", False)),
    )


def _validate_installed_distro(data: Any, index: int) -> InstalledDistro:
    payload = _expect_dict(data, f"installed_distros[{index}]")
    username = payload.get("username", "")
    if not isinstance(username, str):
        raise ConfigValidationError(f"'installed_distros[{index}].username' must be a string.")
    return InstalledDistro(
        name=_validate_string(payload.get("name"), f"installed_distros[{index}].name"),
        distro_id=_validate_string(
            payload.get("distro_id"), f"installed_distros[{index}].distro_id"
        ),
        install_dir=_validate_string(
            payload.get("install_dir"), f"installed_distros[{index}].install_dir"
        ),
        installed_at=_validate_string(
            payload.get("installed_at"), f"installed_distros[{index}].installed_at"
        ),
        username=username.strip(),
    )


def validate_config_data(raw: dict[str, Any]) -> AppConfig:
    """Validate a config payload and return a typed ``AppConfig``."""

    data = _expect_dict(raw, "config")
    cfg = AppConfig(
        schema_version=_validate_int(
            data.get("schema_version", SCHEMA_VERSION),
            "schema_version",
            minimum=SCHEMA_VERSION,
            maximum=SCHEMA_VERSION,
        ),
        language=_validate_language(data.get("language", "en"), "language"),
        install_dir=_validate_string(data.get("install_dir"), "install_dir"),
        download_dir=_validate_string(data.get("download_dir"), "download_dir"),
        remote_catalog_url=_validate_string(
            data.get("remote_catalog_url", ""),
            "remote_catalog_url",
            allow_empty=True,
        ),
        run_as_admin=_validate_bool(data.get("run_as_admin", True), "run_as_admin"),
        check_for_updates=_validate_bool(
            data.get("check_for_updates", False),
            "check_for_updates",
        ),
        update_repo_url=_validate_string(
            data.get("update_repo_url", ""),
            "update_repo_url",
            allow_empty=True,
        ),
        memory_limit_gb=_validate_int(
            data.get("memory_limit_gb"),
            "memory_limit_gb",
            minimum=1,
            maximum=256,
        ),
        swap_size_gb=_validate_int(
            data.get("swap_size_gb"),
            "swap_size_gb",
            minimum=0,
            maximum=128,
        ),
        processors=_validate_int(
            data.get("processors"),
            "processors",
            minimum=1,
            maximum=256,
        ),
        localhost_forwarding=_validate_bool(
            data.get("localhost_forwarding", True),
            "localhost_forwarding",
        ),
        vm_idle_timeout_sec=_validate_int(
            data.get("vm_idle_timeout_sec", 60),
            "vm_idle_timeout_sec",
            minimum=1,
        ),
        auto_refresh_interval_sec=_validate_int(
            data.get("auto_refresh_interval_sec"),
            "auto_refresh_interval_sec",
            minimum=1,
        ),
        wsl_version=_validate_int(data.get("wsl_version"), "wsl_version", minimum=1, maximum=2),
        diagnostic_log_tail_lines=_validate_int(
            data.get("diagnostic_log_tail_lines"),
            "diagnostic_log_tail_lines",
            minimum=1,
        ),
    )

    raw_states = data.get("download_states", {})
    if not isinstance(raw_states, dict):
        raise ConfigValidationError("'download_states' must be an object.")
    for key, state in raw_states.items():
        if not isinstance(key, str) or not key.strip():
            raise ConfigValidationError("download_states keys must be non-empty strings.")
        parsed = _validate_download_state(state, key)
        cfg.download_states[parsed.url] = parsed

    raw_installed = data.get("installed_distros", [])
    if not isinstance(raw_installed, list):
        raise ConfigValidationError("'installed_distros' must be a list.")
    for index, item in enumerate(raw_installed):
        cfg.installed_distros.append(_validate_installed_distro(item, index))

    return cfg


def normalize_loaded_config(raw: dict[str, Any]) -> ConfigLoadResult:
    """
    Convert raw JSON config data into ``AppConfig`` with safe fallbacks.

    Invalid scalar values fall back to defaults with warnings.
    Invalid nested entries are skipped with warnings.
    """

    warnings: list[str] = []
    infos: list[str] = []
    data = dict(raw)
    should_persist = False
    schema_version = data.get("schema_version")
    if schema_version is None:
        data, migration_infos = migrate_v1_to_v2(data)
        infos.extend(migration_infos)
        should_persist = True
    elif schema_version != SCHEMA_VERSION:
        warnings.append(
            "Unsupported config "
            f"schema_version={schema_version!r}; using safe defaults where needed."
        )
        data["schema_version"] = SCHEMA_VERSION
        should_persist = True

    cfg = AppConfig()
    cfg.schema_version = SCHEMA_VERSION

    scalar_specs = (
        ("install_dir", _validate_string, {"allow_empty": False}),
        ("language", _validate_language, {}),
        ("download_dir", _validate_string, {"allow_empty": False}),
        ("remote_catalog_url", _validate_string, {"allow_empty": True}),
        ("run_as_admin", _validate_bool, {}),
        ("check_for_updates", _validate_bool, {}),
        ("update_repo_url", _validate_string, {"allow_empty": True}),
        ("memory_limit_gb", _validate_int, {"minimum": 1, "maximum": 256}),
        ("swap_size_gb", _validate_int, {"minimum": 0, "maximum": 128}),
        ("processors", _validate_int, {"minimum": 1, "maximum": 256}),
        ("localhost_forwarding", _validate_bool, {}),
        ("vm_idle_timeout_sec", _validate_int, {"minimum": 1}),
        ("auto_refresh_interval_sec", _validate_int, {"minimum": 1}),
        ("wsl_version", _validate_int, {"minimum": 1, "maximum": 2}),
        ("diagnostic_log_tail_lines", _validate_int, {"minimum": 1}),
    )
    for field_name, validator, kwargs in scalar_specs:
        if field_name not in data:
            continue
        try:
            setattr(cfg, field_name, validator(data[field_name], field_name, **kwargs))
        except ConfigValidationError as exc:
            warnings.append(f"{exc} Falling back to default value.")
            should_persist = True

    raw_states = data.get("download_states", {})
    if raw_states is None:
        raw_states = {}
    if not isinstance(raw_states, dict):
        warnings.append("'download_states' must be an object. Ignoring invalid value.")
        should_persist = True
    else:
        for key, state in raw_states.items():
            if not isinstance(key, str) or not key.strip():
                warnings.append("download_states entry with invalid key was skipped.")
                should_persist = True
                continue
            try:
                parsed = _validate_download_state(state, key)
            except ConfigValidationError as exc:
                warnings.append(f"{exc} Entry skipped.")
                should_persist = True
                continue
            cfg.download_states[parsed.url] = parsed

    raw_installed = data.get("installed_distros", [])
    if raw_installed is None:
        raw_installed = []
    if not isinstance(raw_installed, list):
        warnings.append("'installed_distros' must be a list. Ignoring invalid value.")
        should_persist = True
    else:
        for index, item in enumerate(raw_installed):
            try:
                cfg.installed_distros.append(_validate_installed_distro(item, index))
            except ConfigValidationError as exc:
                warnings.append(f"{exc} Entry skipped.")
                should_persist = True

    return ConfigLoadResult(
        config=cfg,
        warnings=warnings,
        infos=infos,
        should_persist=should_persist,
    )


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class ConfigManager:
    """Load, validate, and persist application configuration as JSON.

    The manager is the **single source of truth** for all persistent state.
    Every save goes through :func:`validate_config_data` to ensure the
    on-disk file is always well-formed.  On load, invalid values are
    silently corrected to defaults with warnings collected in
    :attr:`startup_warnings`.

    Usage::

        mgr = ConfigManager()
        print(mgr.config.install_dir)
        mgr.config.language = "es"
        mgr.save()

    Attributes
    ----------
    startup_warnings : list[str]
        Warnings collected during the most recent load (schema migration,
        invalid values, skipped entries).  Available immediately after
        construction.
    startup_infos : list[str]
        Informational messages from the most recent load (e.g. migration
        notices).
    """

    _FILE = "config.json"

    def __init__(self, path: Optional[Path] = None) -> None:
        """Create a :class:`ConfigManager` bound to a specific config file.

        Args:
            path: Absolute path to the config JSON file.  If ``None``,
                defaults to the platform-appropriate location
                (``%APPDATA%\\WSLManagerPro\\config.json`` on Windows).
        """
        self._path = Path(path) if path is not None else (_config_dir() / self._FILE)
        self._startup_warnings: list[str] = []
        self._startup_infos: list[str] = []
        result = self._load()
        self._cfg = result.config
        self._startup_warnings = result.warnings
        self._startup_infos = result.infos
        if result.should_persist:
            self.save()

    # ---- public API -------------------------------------------------------

    @property
    def config(self) -> AppConfig:
        """The current application configuration (mutable).

        Modify attributes directly, then call :meth:`save` to persist::

            mgr.config.language = "pt"
            mgr.save()
        """
        return self._cfg

    @property
    def startup_warnings(self) -> list[str]:
        """Warnings from the most recent config load (schema migration, etc.)."""
        return list(self._startup_warnings)

    @property
    def startup_infos(self) -> list[str]:
        """Informational messages from the most recent config load."""
        return list(self._startup_infos)

    def save(self) -> None:
        """Validate and persist the current configuration to disk.

        Calls :func:`validate_config_data` first — if any value is invalid,
        a :class:`ConfigValidationError` is raised and nothing is written.

        Raises:
            ConfigValidationError: If the current config fails validation.
        """
        validated = validate_config_data(self._to_jsonable_dict(self._cfg))
        data = self._to_jsonable_dict(validated)
        with self._path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        self._cfg = validated

    # ---- download state ---------------------------------------------------

    def get_download_state(self, url: str) -> Optional[DownloadState]:
        """Look up the resume state for a download by its URL.

        Args:
            url: The download URL (used as the key).

        Returns:
            The :class:`DownloadState` if found, or ``None``.
        """
        return self._cfg.download_states.get(url)

    def update_download_state(self, state: DownloadState) -> None:
        """Record or update a download state and persist immediately.

        Args:
            state: The :class:`DownloadState` to store.
        """
        self._cfg.download_states[state.url] = state
        self.save()

    def remove_download_state(self, url: str) -> None:
        """Delete a download state and persist immediately.

        Args:
            url: The download URL to remove.
        """
        self._cfg.download_states.pop(url, None)
        self.save()

    # ---- distro registry --------------------------------------------------

    def register_installed_distro(self, distro: InstalledDistro) -> None:
        """Record a distro installed by this application and persist.

        If a distro with the same *name* already exists, it is replaced.

        Args:
            distro: The :class:`InstalledDistro` record to store.
        """
        self._cfg.installed_distros = [
            d for d in self._cfg.installed_distros if d.name != distro.name
        ]
        self._cfg.installed_distros.append(distro)
        self.save()

    def unregister_distro(self, name: str) -> None:
        """Remove a distro from the installed registry and persist.

        Args:
            name: WSL registration name of the distro to forget.
        """
        self._cfg.installed_distros = [
            d for d in self._cfg.installed_distros if d.name != name
        ]
        self.save()

    def find_installed(self, name: str) -> Optional[InstalledDistro]:
        """Look up an installed distro by its WSL name.

        Args:
            name: WSL registration name.

        Returns:
            The :class:`InstalledDistro` record if found, or ``None``.
        """
        for d in self._cfg.installed_distros:
            if d.name == name:
                return d
        return None

    # ---- private ----------------------------------------------------------

    def _load(self) -> ConfigLoadResult:
        if not self._path.exists():
            return ConfigLoadResult(config=AppConfig())
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except json.JSONDecodeError:
            return ConfigLoadResult(
                config=AppConfig(),
                warnings=["config.json is not valid JSON. Loaded safe defaults."],
            )
        except OSError as exc:
            return ConfigLoadResult(
                config=AppConfig(),
                warnings=[f"config.json could not be read: {exc}. Loaded safe defaults."],
            )

        if not isinstance(raw, dict):
            return ConfigLoadResult(
                config=AppConfig(),
                warnings=["config.json root value must be an object. Loaded safe defaults."],
            )
        return normalize_loaded_config(raw)

    def _to_jsonable_dict(self, cfg: AppConfig) -> dict[str, Any]:
        return {
            "schema_version": cfg.schema_version,
            "language": cfg.language,
            "install_dir": cfg.install_dir,
            "download_dir": cfg.download_dir,
            "remote_catalog_url": cfg.remote_catalog_url,
            "run_as_admin": cfg.run_as_admin,
            "check_for_updates": cfg.check_for_updates,
            "update_repo_url": cfg.update_repo_url,
            "memory_limit_gb": cfg.memory_limit_gb,
            "swap_size_gb": cfg.swap_size_gb,
            "processors": cfg.processors,
            "localhost_forwarding": cfg.localhost_forwarding,
            "vm_idle_timeout_sec": cfg.vm_idle_timeout_sec,
            "auto_refresh_interval_sec": cfg.auto_refresh_interval_sec,
            "wsl_version": cfg.wsl_version,
            "diagnostic_log_tail_lines": cfg.diagnostic_log_tail_lines,
            "download_states": {
                url: asdict(state)
                for url, state in cfg.download_states.items()
            },
            "installed_distros": [asdict(d) for d in cfg.installed_distros],
        }
