from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from utils.update_checker import (
    check_latest_release,
    github_repo_api_url,
    is_newer_version,
    latest_release_page_url,
)


def test_github_repo_urls_accept_releases_url() -> None:
    repo = "https://github.com/wilkinbarban/WSL-Manager-Pro/releases"
    assert (
        github_repo_api_url(repo)
        == "https://api.github.com/repos/wilkinbarban/WSL-Manager-Pro/releases/latest"
    )
    assert (
        latest_release_page_url(repo)
        == "https://github.com/wilkinbarban/WSL-Manager-Pro/releases/latest"
    )


def test_github_repo_url_rejects_non_github() -> None:
    with pytest.raises(ValueError):
        github_repo_api_url("https://example.com/owner/repo")


def test_is_newer_version_compares_semver_tags() -> None:
    assert is_newer_version("v1.0.1", "1.0.0")
    assert not is_newer_version("v1.0.0", "1.0.0")
    assert not is_newer_version("v0.9.9", "1.0.0")


def test_check_latest_release_reports_update_available() -> None:
    response = MagicMock()
    response.json.return_value = {
        "tag_name": "v1.2.0",
        "html_url": "https://github.com/wilkinbarban/WSL-Manager-Pro/releases/tag/v1.2.0",
    }
    response.raise_for_status.return_value = None
    with patch("utils.update_checker.requests.get", return_value=response):
        result = check_latest_release(
            "https://github.com/wilkinbarban/WSL-Manager-Pro/releases",
            "1.0.0",
        )

    assert result.update_available is True
    assert result.latest_version == "v1.2.0"
    assert result.release_url.endswith("/v1.2.0")
