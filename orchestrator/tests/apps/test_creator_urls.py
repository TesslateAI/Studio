"""Wave 9 Track B1 — creator-branded app runtime URLs.

Covers:
- ``users.handle`` format validation (regex + reserved list).
- ``app_container_url`` shape for multi-container and single-container.
- Legacy ``container_url`` is untouched for non-app projects.
"""

from __future__ import annotations

import pytest

from app.services.apps.reserved_handles import (
    is_reserved,
    is_valid_handle_format,
)
from app.services.apps.runtime_urls import (
    app_container_url,
    container_url,
)

# ---------------------------------------------------------------------------
# Handle validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "handle",
    ["acme", "acme-co", "acme-co-2", "a1b2", "user123"],
)
def test_handle_format_accepts_well_formed(handle: str) -> None:
    assert is_valid_handle_format(handle, max_length=32) is True
    assert is_reserved(handle) is False


@pytest.mark.parametrize(
    "handle,reason",
    [
        ("ACME", "uppercase rejected"),
        ("-acme", "leading hyphen rejected"),
        ("acme-", "trailing hyphen rejected"),
        ("a", "below min length"),
        ("ab", "below min length"),
        ("ac", "below min length"),
        ("acme--co", "consecutive hyphens rejected"),
        ("acme_co", "underscore rejected"),
        ("a" * 50, "above max length"),
    ],
)
def test_handle_format_rejects_invalid(handle: str, reason: str) -> None:
    assert is_valid_handle_format(handle, max_length=32) is False, reason


def test_reserved_handles_blocked() -> None:
    for r in ("admin", "api", "app", "marketplace", "studio", "tesslate"):
        assert is_reserved(r) is True


# ---------------------------------------------------------------------------
# app_container_url shape
# ---------------------------------------------------------------------------


def test_app_url_multi_container_localhost() -> None:
    url = app_container_url(
        app_handle="crm",
        creator_handle="acme",
        container_dir="web",
        app_domain="localhost",
        protocol="http",
    )
    assert url == "http://web-crm-acme.localhost"


def test_app_url_single_container_collapses() -> None:
    url = app_container_url(
        app_handle="crm",
        creator_handle="acme",
        container_dir="web",
        app_domain="localhost",
        protocol="http",
        only_primary=True,
    )
    assert url == "http://crm-acme.localhost"


def test_app_url_https_production_domain() -> None:
    url = app_container_url(
        app_handle="todo-list",
        creator_handle="jane-doe",
        container_dir="api",
        app_domain="apps.tesslate.com",
        protocol="https",
    )
    assert url == "https://api-todo-list-jane-doe.apps.tesslate.com"


# ---------------------------------------------------------------------------
# Legacy container_url stays the same for non-app projects
# ---------------------------------------------------------------------------


def test_legacy_container_url_unchanged_localhost() -> None:
    url = container_url(
        project_slug="my-app-k3x8n2",
        container_dir_or_name="frontend",
        app_domain="localhost",
        protocol="http",
    )
    assert url == "http://my-app-k3x8n2-frontend.localhost"


def test_legacy_container_url_unchanged_https() -> None:
    url = container_url(
        project_slug="cool-thing-abc123",
        container_dir_or_name="api",
        app_domain="opensail.tesslate.com",
        protocol="https",
    )
    assert url == "https://cool-thing-abc123-api.opensail.tesslate.com"
