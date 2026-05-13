"""GitHub release update checking helpers."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import requests

DEFAULT_UPDATE_REPO_URL = "https://github.com/wilkinbarban/WSL-Manager-Pro/releases"


@dataclass(frozen=True)
class UpdateCheckResult:
    latest_version: str
    release_url: str
    update_available: bool


def _normalise_version(version: str) -> tuple[int, ...]:
    cleaned = version.strip().lstrip("vV")
    parts = re.findall(r"\d+", cleaned)
    if not parts:
        return (0,)
    return tuple(int(part) for part in parts[:4])


def is_newer_version(latest: str, current: str) -> bool:
    latest_parts = _normalise_version(latest)
    current_parts = _normalise_version(current)
    width = max(len(latest_parts), len(current_parts))
    latest_padded = latest_parts + (0,) * (width - len(latest_parts))
    current_padded = current_parts + (0,) * (width - len(current_parts))
    return latest_padded > current_padded


def github_repo_api_url(repo_url: str) -> str:
    """Return the GitHub API latest-release URL for a repository/releases URL."""
    parsed = urlparse((repo_url or DEFAULT_UPDATE_REPO_URL).strip())
    if parsed.netloc.lower() != "github.com":
        raise ValueError("Update URL must be a github.com repository URL.")

    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 2:
        raise ValueError("Update URL must include owner and repository name.")
    owner, repo = parts[0], parts[1]
    return f"https://api.github.com/repos/{owner}/{repo}/releases/latest"


def latest_release_page_url(repo_url: str) -> str:
    parsed = urlparse((repo_url or DEFAULT_UPDATE_REPO_URL).strip())
    if parsed.netloc.lower() != "github.com":
        raise ValueError("Update URL must be a github.com repository URL.")
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 2:
        raise ValueError("Update URL must include owner and repository name.")
    return f"https://github.com/{parts[0]}/{parts[1]}/releases/latest"


def check_latest_release(
    repo_url: str,
    current_version: str,
    *,
    timeout: tuple[int, int] = (5, 15),
) -> UpdateCheckResult:
    api_url = github_repo_api_url(repo_url)
    response = requests.get(
        api_url,
        timeout=timeout,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "WSL-Manager-Pro",
        },
    )
    response.raise_for_status()
    payload: dict[str, Any] = response.json()
    latest_version = str(payload.get("tag_name") or payload.get("name") or "").strip()
    if not latest_version:
        raise ValueError("Latest release does not define a tag_name.")
    release_url = str(payload.get("html_url") or latest_release_page_url(repo_url))
    return UpdateCheckResult(
        latest_version=latest_version,
        release_url=release_url,
        update_available=is_newer_version(latest_version, current_version),
    )
