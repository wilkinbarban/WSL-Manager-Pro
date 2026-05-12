# Contributing to WSL Manager Pro

Thank you for your interest in contributing! This document provides
guidelines for setting up your development environment and submitting
changes.

## Code of Conduct

Please be respectful and constructive in all interactions.  We follow
the [Contributor Covenant](https://www.contributor-covenant.org/).

## Development Environment Setup

### Prerequisites

- **Windows 10** build 19041+ with WSL 2
- **Python 3.10** or later
- **PowerShell 5.1+** or PowerShell 7+
- **winget** (bundled with App Installer from Microsoft Store)

### One-Click Setup

```powershell
.\install.ps1
```

This fully automates the environment setup (WSL features, Python,
venv, and dependencies).

### Manual Setup

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev]"
```

The `[dev]` extra installs pytest, ruff, and pytest-qt.

## Project Structure

See [REDME.md](REDME.md) for the complete repository structure and
architecture overview.

## Running the Application

```powershell
python main.py
```

On first launch you will be prompted to run as Administrator (recommended
for WSL operations and winget).  You can decline to run in read-only mode.

## Running Tests

```bash
pytest tests/ -q
```

All 32 tests pass without requiring `wsl.exe`.  The parsers are pure
functions and the downloader/engine tests use mocks.

## Linting

```bash
ruff check core/ utils/ tests/ main.py
```

Ruff is configured in `pyproject.toml` (target Python 3.10, line length 100).
The `ui/` directory is temporarily excluded pending style review (see
ROADMAP phase A).

## Building the Executable

```powershell
.\build.ps1
```

This invokes PyInstaller with `wsl_manager_pro.spec`, producing
`dist/WSLManagerPro.exe` (~50 MB).

## Pull Request Process

1. **Fork** the repository and create your branch from `main`.
2. **Add tests** if you are adding or changing functionality.
3. **Run tests** (`pytest tests/ -q`) — all must pass.
4. **Run linting** (`ruff check core/ utils/ tests/ main.py`) — all must pass.
5. **Update documentation** if you are changing user-facing behaviour.
6. **Submit a pull request** with a clear description of the changes.

## Commit Message Guidelines

- Use the present tense ("Add feature" not "Added feature").
- Use the imperative mood ("Fix bug" not "Fixes bug").
- Keep the first line under 72 characters.
- Reference issues and pull requests where applicable.

## Code Style

- **Python 3.10+** with modern type annotations (`list[str]`, `dict[str, str]`).
- **Google-style docstrings** for all public functions and classes.
- **4 spaces** for indentation (no tabs).
- **Line length:** 100 characters (configured in ruff).
- **Imports:** use `isort`-compatible ordering (enforced by ruff).

## Security

- Never hardcode credentials, API keys, or tokens.
- Never log passwords or sensitive user data.
- Follow the existing password-handling pattern in `WslEngine`
  (temp file in guest, deleted immediately after use).
- Report security vulnerabilities privately before opening a public issue.

## Questions?

Open an issue on GitHub with the `question` label.
