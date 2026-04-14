"""Unit tests for marketplace install service helpers."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

import app.models  # noqa: F401
from app.services.public.marketplace_install_service import (
    InstallResolution,
    build_download_urls,
    purchase_to_dict,
    record_install,
    resolve_item,
)


def _agent(slug="my-agent", item_type="agent", pricing_type="free", is_active=True):
    a = MagicMock()
    a.id = uuid.uuid4()
    a.slug = slug
    a.item_type = item_type
    a.pricing_type = pricing_type
    a.is_active = is_active
    return a


def _base(slug="my-base", pricing_type="free"):
    b = MagicMock()
    b.id = uuid.uuid4()
    b.slug = slug
    b.pricing_type = pricing_type
    b.is_active = True
    b.git_repo_url = "https://git.example/repo.git"
    b.default_branch = "main"
    return b


def _user():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.default_team_id = None
    return u


def _scalar_or_none(value):
    res = MagicMock()
    res.scalar_one_or_none.return_value = value
    return res


# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_item_rejects_unknown_type():
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await resolve_item(db, "widget", "slug")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_resolve_item_agent_404():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_or_none(None))
    with pytest.raises(HTTPException) as exc:
        await resolve_item(db, "agent", "missing")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_resolve_item_base_ok():
    db = AsyncMock()
    base = _base()
    db.execute = AsyncMock(return_value=_scalar_or_none(base))
    res = await resolve_item(db, "base", "my-base")
    assert res.is_base is True
    assert res.item is base


@pytest.mark.asyncio
async def test_record_install_paid_no_purchase_returns_402():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_or_none(None))
    resolution = InstallResolution(item_type="agent", item=_agent(pricing_type="paid"), is_base=False)

    with pytest.raises(HTTPException) as exc:
        await record_install(db, _user(), resolution)
    assert exc.value.status_code == 402


@pytest.mark.asyncio
async def test_record_install_free_creates_row():
    db = AsyncMock()
    # No existing purchase; insert succeeds.
    db.execute = AsyncMock(return_value=_scalar_or_none(None))
    db.add = MagicMock()
    db.commit = AsyncMock()

    async def _refresh(row):
        row.id = uuid.uuid4()
        row.purchase_type = "free"

    db.refresh = AsyncMock(side_effect=_refresh)

    resolution = InstallResolution(item_type="skill", item=_agent(item_type="skill"), is_base=False)
    row, created = await record_install(db, _user(), resolution)
    assert created is True
    assert row.purchase_type == "free"
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_record_install_existing_purchase_no_insert():
    db = AsyncMock()
    existing = MagicMock(purchase_type="purchased", id=uuid.uuid4())
    db.execute = AsyncMock(return_value=_scalar_or_none(existing))
    db.add = MagicMock()

    resolution = InstallResolution(item_type="agent", item=_agent(pricing_type="paid"), is_base=False)
    row, created = await record_install(db, _user(), resolution)
    assert created is False
    assert row is existing
    db.add.assert_not_called()


def test_build_download_urls_base_returns_git():
    res = InstallResolution(item_type="base", item=_base(), is_base=True)
    urls = build_download_urls(res)
    assert urls["git_repo_url"] == "https://git.example/repo.git"


def test_build_download_urls_agent_returns_manifest():
    res = InstallResolution(item_type="agent", item=_agent(slug="coder"), is_base=False)
    urls = build_download_urls(res)
    assert urls["manifest_url"].endswith("/coder/manifest")


def test_build_download_urls_skill_includes_body():
    res = InstallResolution(item_type="skill", item=_agent(slug="docker", item_type="skill"), is_base=False)
    urls = build_download_urls(res)
    assert urls["body_url"].endswith("/docker/body")


def test_purchase_to_dict_agent():
    row = MagicMock()
    row.id = uuid.uuid4()
    row.agent_id = uuid.uuid4()
    row.agent.item_type = "skill"
    row.purchase_type = "free"
    row.purchase_date = None
    row.expires_at = None
    row.is_active = True
    # Not a base: does not have base_id attribute
    del row.base_id

    d = purchase_to_dict(row)
    assert d["item_type"] == "skill"
    assert d["purchase_type"] == "free"
    assert d["is_active"] is True
