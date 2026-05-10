# Changelog

All notable changes to WSL Manager Pro will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] — 2026-05-09

### Added

- **Dashboard tab** — Live WSL distribution status table with 7 columns
  (status icon, name, state, WSL version, default flag, user status,
  action button). Auto-refresh timer and Re-scan User Status.
- **Manage tab** — Import/export controls and quick actions (Set Default,
  Terminate, Shutdown All, Open Shell, System Update, winget Install,
  Repair, Unregister, Deep Clean).
- **Settings tab** — Default directories, startup options, WSL 2 resource
  limits (memory, swap, processors, localhost forwarding, VM idle timeout),
  `.wslconfig` generation, and diagnostic bundle export.
- **5-page Install Wizard** — Distro Selection → Configure Paths → User
  Account → Summary → Progress with profile save/load.
- **WSL Engine (`WslEngine`)** — High-level facade over `wsl.exe`, winget,
  DISM, and PowerShell with streaming output and explicit timeouts.
- **Download Manager (`DownloadManager`)** — Resumable HTTP downloads with
  SHA-256/SHA-512/MD5 checksum verification, cooperative cancellation, APPX
  extraction, and Arch Linux bootstrap (`.tar.zst`) support.
- **Catalog system** — Local `distros.json` + optional remote catalog merge
  with strict schema validation and lenient loading.
- **Internationalisation (i18n)** — English, Spanish (Español), and
  Portuguese (Português) with live language switching.
- **Persistent configuration** — JSON-based settings at
  `%APPDATA%\WSLManagerPro\config.json` with schema versioning (v1→v2
  migration).
- **Diagnostic bundle** — ZIP export with app version, log tail,
  `wsl --version`, and `wsl --status`.
- **32 unit tests** — All pass without requiring `wsl.exe`.
- **CI pipeline** — GitHub Actions workflow with ruff linting and pytest.
- **One-click installer** — `install.ps1` for fully automated environment
  setup.
- **PyInstaller build** — Single-file `WSLManagerPro.exe` (~50 MB).
- **Dark theme** — QSS stylesheet (`resources/styles/dark.qss`, ~250 lines).

### Supported Distributions

Ubuntu 22.04/24.04 LTS, Debian 12 (Bookworm), Fedora 40, Alpine Linux 3.19,
Arch Linux, AlmaLinux 9, SUSE Linux Enterprise 15 SP6, Oracle Linux 9.5.
