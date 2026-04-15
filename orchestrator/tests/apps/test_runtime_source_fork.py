"""Wave 2 — unit + integration tests for runtime / source_view / fork / audit.

Unit tests (default) mock the SQLAlchemy session. Integration tests
(marked `@pytest.mark.integration`) hit a live Postgres + use FakeDelegate
for the LiteLLM proxy, mirroring `tests/integration/test_litellm_keys_integration.py`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.services.apps import audit, fork, runtime, source_view
from app.services.apps.source_view import (
    HARDCODED_EXCLUSIONS,
    InstallerOnlySourceError,
    PrivateSourceError,
    SourceAccessError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app_version(
    *,
    level: str = "public",
    excluded_paths: list[str] | None = None,
    manifest_always_public: bool = False,
    app_id: UUID | None = None,
    bundle_hash: str = "bundle-abc",
):
    """Build a mock AppVersion-shaped object (only the fields source_view reads)."""
    av = MagicMock()
    av.id = uuid4()
    av.app_id = app_id or uuid4()
    av.bundle_hash = bundle_hash
    av.manifest_json = {
        "source_visibility": {
            "level": level,
            "excluded_paths": list(excluded_paths or []),
            "manifest_always_public": manifest_always_public,
        }
    }
    return av


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class FakeDb:
    """Minimal AsyncSession stand-in for unit tests.

    Accepts a list of `execute` results (FIFO) so tests can script the SQL
    path. We intentionally don't validate the SELECT shape — that's what the
    integration tests are for.
    """

    def __init__(self, results):
        self._results = list(results)
        self.added = []
        self.flushed = False

    async def execute(self, _stmt):
        if not self._results:
            return _ScalarResult(None)
        nxt = self._results.pop(0)
        return _ScalarResult(nxt)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed = True

    async def rollback(self):
        pass


# ---------------------------------------------------------------------------
# source_view unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_source_view_private_rejects() -> None:
    av = _make_app_version(level="private")
    db = FakeDb([av])
    with pytest.raises(PrivateSourceError):
        await source_view.list_files(
            db,  # type: ignore[arg-type]
            app_version_id=av.id,
            viewer_user_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_source_view_installers_only_rejects_non_installer() -> None:
    av = _make_app_version(level="installers")
    # First execute() returns the AppVersion, second returns None (no install).
    db = FakeDb([av, None])
    with pytest.raises(InstallerOnlySourceError):
        await source_view.list_files(
            db,  # type: ignore[arg-type]
            app_version_id=av.id,
            viewer_user_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_source_view_installers_only_rejects_anonymous() -> None:
    av = _make_app_version(level="installers")
    db = FakeDb([av])
    with pytest.raises(InstallerOnlySourceError):
        await source_view.list_files(
            db,  # type: ignore[arg-type]
            app_version_id=av.id,
            viewer_user_id=None,
        )


@pytest.mark.asyncio
async def test_source_view_public_allows() -> None:
    av = _make_app_version(level="public")
    db = FakeDb([av])

    async def lister(_vol):
        return ["README.md", "src/index.ts"]

    result = await source_view.list_files(
        db,  # type: ignore[arg-type]
        app_version_id=av.id,
        viewer_user_id=None,
        list_volume_files=lister,
    )
    assert result.files == ["README.md", "src/index.ts"]


@pytest.mark.asyncio
async def test_source_view_excluded_paths_filtered() -> None:
    av = _make_app_version(level="public")
    db = FakeDb([av])

    async def lister(_vol):
        return [
            "README.md",
            ".env",
            ".env.production",
            "secrets/config.yaml",
            ".git/HEAD",
            ".tesslate/internal/notes.md",
            "src/index.ts",
        ]

    result = await source_view.list_files(
        db,  # type: ignore[arg-type]
        app_version_id=av.id,
        viewer_user_id=None,
        list_volume_files=lister,
    )
    assert set(result.files) == {"README.md", "src/index.ts"}
    # Sanity: HARDCODED_EXCLUSIONS actually cover these
    assert any("env" in p for p in HARDCODED_EXCLUSIONS)


@pytest.mark.asyncio
async def test_source_view_manifest_always_included() -> None:
    av = _make_app_version(
        level="public",
        excluded_paths=["app.manifest.json"],
        manifest_always_public=True,
    )
    db = FakeDb([av])

    async def lister(_vol):
        return ["app.manifest.json", "src/index.ts"]

    result = await source_view.list_files(
        db,  # type: ignore[arg-type]
        app_version_id=av.id,
        viewer_user_id=None,
        list_volume_files=lister,
    )
    assert "app.manifest.json" in result.files
    assert "src/index.ts" in result.files


# ---------------------------------------------------------------------------
# fork unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fork_not_forkable_raises() -> None:
    parent = MagicMock()
    parent.id = uuid4()
    parent.forkable = "no"
    parent.description = None
    parent.category = None
    parent.icon_ref = None
    version = MagicMock()
    version.id = uuid4()
    # db.execute().one_or_none() must return (version, parent)
    class _R:
        def one_or_none(self):
            return (version, parent)

    db = MagicMock()
    db.execute = AsyncMock(return_value=_R())

    with pytest.raises(fork.NotForkableError):
        await fork.fork_app(
            db,
            forker_user_id=uuid4(),
            source_app_version_id=version.id,
            new_slug="my-fork",
            new_name="My Fork",
        )


# ---------------------------------------------------------------------------
# audit unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_write_does_not_raise_on_failure(caplog) -> None:
    db = MagicMock()
    # flush() raises to simulate a DB error
    db.add = MagicMock()
    db.flush = AsyncMock(side_effect=RuntimeError("db down"))

    # Must not raise
    await audit.write_audit(
        db,
        actor_user_id=uuid4(),
        team_id=uuid4(),
        project_id=None,
        action="app.publish",
        resource_type="app_version",
        resource_id=str(uuid4()),
        details={"hello": "world"},
    )


@pytest.mark.asyncio
async def test_audit_write_logger_only_when_no_team() -> None:
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()

    await audit.write_audit(
        db,
        actor_user_id=uuid4(),
        team_id=None,
        project_id=None,
        action="app.install",
        resource_type="app",
        resource_id=str(uuid4()),
    )
    # No DB add should have happened in the team-less fallback path
    db.add.assert_not_called()


# ---------------------------------------------------------------------------
# Integration tests (live Postgres + FakeDelegate)
# ---------------------------------------------------------------------------


pytestmark_integration = pytest.mark.integration


class FakeDelegate:
    def __init__(self) -> None:
        self.minted: list[dict[str, Any]] = []
        self.revoked: list[str] = []
        self._counter = 0

    async def create_scoped_key(
        self,
        *,
        tier: str,
        budget_usd: Decimal,
        ttl_seconds: int,
        metadata: dict[str, Any],
    ) -> dict[str, str]:
        self._counter += 1
        key_id = f"rt-key-{self._counter}-{uuid.uuid4().hex[:8]}"
        api_key = f"sk-fake-{key_id}"
        self.minted.append(
            {"key_id": key_id, "api_key": api_key, "tier": tier, "budget_usd": Decimal(budget_usd), "metadata": metadata}
        )
        return {"key_id": key_id, "api_key": api_key}

    async def revoke_key(self, key_id: str) -> None:
        self.revoked.append(key_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_begin_session_mints_session_key() -> None:
    from app.database import AsyncSessionLocal
    from app.models import AppInstance, AppVersion, LiteLLMKeyLedger, MarketplaceApp, User

    delegate = FakeDelegate()
    async with AsyncSessionLocal() as db:
        user = User(id=uuid4(), email=f"rt-{uuid.uuid4().hex[:6]}@example.com", username=f"rt{uuid.uuid4().hex[:6]}", hashed_password="x")
        app = MarketplaceApp(id=uuid4(), slug=f"rt-app-{uuid.uuid4().hex[:6]}", name="rt", creator_user_id=user.id, state="approved", forkable="restricted", visibility="private")
        av = AppVersion(id=uuid4(), app_id=app.id, version="1.0.0", manifest_schema_version="2025-01", manifest_json={}, manifest_hash="h", feature_set_hash="f", approval_state="stage2_approved")
        inst = AppInstance(id=uuid4(), app_id=app.id, app_version_id=av.id, installer_user_id=user.id, state="installed")
        db.add_all([user, app, av, inst])
        await db.flush()

        handle = await runtime.begin_session(
            db,
            app_instance_id=inst.id,
            installer_user_id=user.id,
            delegate=delegate,
            budget_usd=Decimal("1.00"),
            ttl_seconds=3600,
        )
        assert handle.litellm_key_id in [m["key_id"] for m in delegate.minted]
        row = (await db.execute(
            __import__("sqlalchemy").select(LiteLLMKeyLedger).where(LiteLLMKeyLedger.key_id == handle.litellm_key_id)
        )).scalar_one()
        assert row.state == "active"
        assert row.tier == "session"
        await db.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_begin_session_rejects_yanked_app() -> None:
    from app.database import AsyncSessionLocal
    from app.models import AppInstance, AppVersion, MarketplaceApp, User

    delegate = FakeDelegate()
    async with AsyncSessionLocal() as db:
        user = User(id=uuid4(), email=f"rt-{uuid.uuid4().hex[:6]}@example.com", username=f"rt{uuid.uuid4().hex[:6]}", hashed_password="x")
        app = MarketplaceApp(id=uuid4(), slug=f"rt-app-{uuid.uuid4().hex[:6]}", name="rt", creator_user_id=user.id, state="yanked", forkable="restricted", visibility="private")
        av = AppVersion(id=uuid4(), app_id=app.id, version="1.0.0", manifest_schema_version="2025-01", manifest_json={}, manifest_hash="h", feature_set_hash="f", approval_state="stage2_approved")
        inst = AppInstance(id=uuid4(), app_id=app.id, app_version_id=av.id, installer_user_id=user.id, state="installed")
        db.add_all([user, app, av, inst])
        await db.flush()

        with pytest.raises(runtime.AppNotRunnableError):
            await runtime.begin_session(
                db,
                app_instance_id=inst.id,
                installer_user_id=user.id,
                delegate=delegate,
            )
        await db.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fork_creates_new_app_row() -> None:
    from app.database import AsyncSessionLocal
    from app.models import AppVersion, MarketplaceApp, User
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        user = User(id=uuid4(), email=f"fk-{uuid.uuid4().hex[:6]}@example.com", username=f"fk{uuid.uuid4().hex[:6]}", hashed_password="x")
        app = MarketplaceApp(id=uuid4(), slug=f"fk-app-{uuid.uuid4().hex[:6]}", name="orig", creator_user_id=user.id, state="approved", forkable="true", visibility="public")
        av = AppVersion(id=uuid4(), app_id=app.id, version="1.0.0", manifest_schema_version="2025-01", manifest_json={}, manifest_hash="h", feature_set_hash="f", approval_state="stage2_approved")
        db.add_all([user, app, av])
        await db.flush()

        new_slug = f"fk-fork-{uuid.uuid4().hex[:6]}"
        result = await fork.fork_app(
            db,
            forker_user_id=user.id,
            source_app_version_id=av.id,
            new_slug=new_slug,
            new_name="Forked",
        )
        row = (await db.execute(select(MarketplaceApp).where(MarketplaceApp.id == result.new_app_id))).scalar_one()
        assert row.forked_from == app.id
        assert row.creator_user_id == user.id
        assert row.state == "draft"
        assert row.slug == new_slug
        await db.rollback()
