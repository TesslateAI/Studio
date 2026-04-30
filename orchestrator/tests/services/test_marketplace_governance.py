"""
Wave 8 — orchestrator-side governance proxy tests.

Covers the helpers in ``app.services.marketplace_governance``:
  * ``select_token_for_write`` returns the admin token for Tesslate Official
    sources and the per-source token for everything else.
  * ``get_admin_token`` raises when ``MARKETPLACE_ADMIN_TOKEN`` is unset.
  * ``mirror_submission_into_cache`` updates stage / decision / checks
    on the local row and cascades terminal state to AppVersion.
  * ``mirror_yank_into_cache`` cascades approved yanks to AppVersion.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.services import marketplace_governance as gov


_ASYNC_DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://tesslate_test:testpass@localhost:5433/tesslate_test",
)


def _run_db(coro_fn, *args, **kwargs):
    """Run a coroutine on a throwaway loop with a fresh engine."""

    async def _inner():
        engine = create_async_engine(_ASYNC_DB_URL, pool_pre_ping=False)
        try:
            session_maker = async_sessionmaker(engine, expire_on_commit=False)
            async with session_maker() as db:
                return await coro_fn(db, *args, **kwargs)
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


# ---------------------------------------------------------------------------
# Pure-function tests — no DB
# ---------------------------------------------------------------------------


def test_get_admin_token_raises_when_unset(monkeypatch) -> None:
    monkeypatch.setenv("MARKETPLACE_ADMIN_TOKEN", "")
    from app import config

    config.get_settings.cache_clear()
    with pytest.raises(gov.AdminTokenMissingError):
        gov.get_admin_token()


def test_get_admin_token_returns_value(monkeypatch) -> None:
    monkeypatch.setenv("MARKETPLACE_ADMIN_TOKEN", "tok-abc-123")
    from app import config

    config.get_settings.cache_clear()
    try:
        token = gov.get_admin_token()
        assert token == "tok-abc-123"
    finally:
        config.get_settings.cache_clear()


def test_select_token_for_write_official_uses_admin(monkeypatch) -> None:
    """Tesslate Official sources always use the admin token."""
    monkeypatch.setenv("MARKETPLACE_ADMIN_TOKEN", "admin-token")
    from app import config
    from app.models import MarketplaceSource

    config.get_settings.cache_clear()
    try:
        src = MarketplaceSource(
            id=gov.TESSLATE_OFFICIAL_ID,
            handle="tesslate-official",
            display_name="Tesslate Official",
            base_url="https://marketplace.tesslate.com",
            scope="system",
            trust_level="official",
            is_active=True,
        )
        assert gov.select_token_for_write(src) == "admin-token"
    finally:
        config.get_settings.cache_clear()


def test_select_token_for_write_other_source_uses_per_source_token(monkeypatch) -> None:
    """Non-Tesslate-Official sources use the encrypted-per-source token."""
    monkeypatch.delenv("MARKETPLACE_ADMIN_TOKEN", raising=False)
    from app import config
    from app.models import MarketplaceSource

    config.get_settings.cache_clear()
    src = MarketplaceSource(
        id=uuid.uuid4(),
        handle="community-hub",
        display_name="Community Hub",
        base_url="https://community.example.com",
        scope="system",
        trust_level="admin_trusted",
        is_active=True,
        encrypted_token=None,
    )
    # No encrypted token + not official → returns None (anonymous).
    token = gov.select_token_for_write(src)
    assert token is None


# ---------------------------------------------------------------------------
# Cache mirroring — happy path on AppSubmission
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_mirror_submission_updates_stage_and_appends_checks() -> None:
    """Mirror an envelope onto a local cache row + assert AV cascades on terminal."""

    async def _seed_then_mirror(db):
        from app import models

        # Create a user, app, version, and submission so the mirror has
        # something to update.
        ux = uuid.uuid4().hex[:8]
        user = models.User(
            id=uuid.uuid4(),
            username=f"u-{ux}",
            name=f"User {ux}",
            slug=f"user-{ux}",
            email=f"{ux}@example.com",
            hashed_password="x",
        )
        db.add(user)
        await db.flush()
        from app.services.marketplace_constants import LOCAL_SOURCE_ID

        app = models.MarketplaceApp(
            id=uuid.uuid4(),
            slug=f"test/{uuid.uuid4().hex[:8]}",
            name="Mirror Target",
            source_id=LOCAL_SOURCE_ID,
        )
        db.add(app)
        await db.flush()
        av = models.AppVersion(
            id=uuid.uuid4(),
            app_id=app.id,
            version="0.0.1",
            manifest_schema_version="2025-01",
            manifest_json={},
            manifest_hash="sha256:" + uuid.uuid4().hex + uuid.uuid4().hex[:32],
            feature_set_hash="sha256:" + ("0" * 64),
            approval_state="pending_stage1",
            source_id=LOCAL_SOURCE_ID,
        )
        db.add(av)
        await db.flush()
        sub = models.AppSubmission(
            id=uuid.uuid4(),
            app_version_id=av.id,
            submitter_user_id=user.id,
            stage="stage1",
        )
        db.add(sub)
        await db.flush()

        envelope = {
            "id": str(sub.id),
            "kind": "app",
            "slug": app.slug,
            "version": av.version,
            "state": "approved",
            "stage": "approved",
            "decision": "approved",
            "decision_reason": "auto_approved",
            "checks": [
                {"stage": "stage1", "name": "slug_format", "status": "passed", "details": {}},
                {"stage": "stage3", "name": "reviewer_assignment", "status": "passed", "details": {}},
            ],
        }
        result = await gov.mirror_submission_into_cache(
            db, local_submission_id=sub.id, marketplace_envelope=envelope
        )
        await db.commit()

        # Refresh AppVersion from a fresh select; verify approval_state
        # cascaded to stage2_approved (the runtime-gate alias for the
        # marketplace's "approved" terminal state).
        from sqlalchemy import select

        refreshed_av = (
            await db.execute(select(models.AppVersion).where(models.AppVersion.id == av.id))
        ).scalar_one()
        refreshed_sub = (
            await db.execute(select(models.AppSubmission).where(models.AppSubmission.id == sub.id))
        ).scalar_one()
        check_rows = (
            await db.execute(
                select(models.SubmissionCheck).where(models.SubmissionCheck.submission_id == sub.id)
            )
        ).scalars().all()
        # Eagerly extract values so the caller can compare without the engine.
        return {
            "result": result is not None,
            "sub_stage": refreshed_sub.stage,
            "sub_decision": refreshed_sub.decision,
            "av_approval_state": refreshed_av.approval_state,
            "checks": [(c.stage, c.check_name) for c in check_rows],
        }

    snapshot = _run_db(_seed_then_mirror)
    assert snapshot["result"] is True
    assert snapshot["sub_stage"] == "approved"
    assert snapshot["sub_decision"] == "approved"
    assert snapshot["av_approval_state"] == "stage2_approved"
    pairs = set(snapshot["checks"])
    assert ("stage1", "slug_format") in pairs
    assert ("stage3", "reviewer_assignment") in pairs


@pytest.mark.integration
def test_mirror_submission_idempotent_on_repeated_calls() -> None:
    """Second call with the same envelope must not duplicate check rows."""

    async def _scenario(db):
        from app import models
        from sqlalchemy import select

        ux = uuid.uuid4().hex[:8]
        user = models.User(
            id=uuid.uuid4(),
            username=f"u-{ux}",
            name=f"User {ux}",
            slug=f"user-{ux}",
            email=f"{ux}@example.com",
            hashed_password="x",
        )
        db.add(user)
        from app.services.marketplace_constants import LOCAL_SOURCE_ID

        app = models.MarketplaceApp(
            id=uuid.uuid4(),
            slug=f"test/{uuid.uuid4().hex[:8]}",
            name="Idemp Target",
            source_id=LOCAL_SOURCE_ID,
        )
        db.add(app)
        await db.flush()
        av = models.AppVersion(
            id=uuid.uuid4(),
            app_id=app.id,
            version="0.0.1",
            manifest_schema_version="2025-01",
            manifest_json={},
            manifest_hash="sha256:" + uuid.uuid4().hex + uuid.uuid4().hex[:32],
            feature_set_hash="sha256:" + ("0" * 64),
            approval_state="pending_stage1",
            source_id=LOCAL_SOURCE_ID,
        )
        db.add(av)
        sub = models.AppSubmission(
            id=uuid.uuid4(),
            app_version_id=av.id,
            submitter_user_id=user.id,
            stage="stage1",
        )
        db.add(sub)
        await db.flush()
        envelope = {
            "stage": "stage2",
            "state": "stage2_dynamic",
            "checks": [
                {"stage": "stage1", "name": "slug_format", "status": "passed", "details": {}},
            ],
        }
        await gov.mirror_submission_into_cache(
            db, local_submission_id=sub.id, marketplace_envelope=envelope
        )
        await gov.mirror_submission_into_cache(
            db, local_submission_id=sub.id, marketplace_envelope=envelope
        )
        await db.commit()

        check_rows = (
            await db.execute(
                select(models.SubmissionCheck).where(models.SubmissionCheck.submission_id == sub.id)
            )
        ).scalars().all()
        return [(c.stage, c.check_name) for c in check_rows]

    checks = _run_db(_scenario)
    # Exactly one row, despite the double mirror.
    assert len(checks) == 1


@pytest.mark.integration
def test_mirror_yank_cascades_to_app_version() -> None:
    async def _scenario(db):
        from app import models
        from sqlalchemy import select

        ux = uuid.uuid4().hex[:8]
        user = models.User(
            id=uuid.uuid4(),
            username=f"u-{ux}",
            name=f"User {ux}",
            slug=f"user-{ux}",
            email=f"{ux}@example.com",
            hashed_password="x",
        )
        db.add(user)
        from app.services.marketplace_constants import LOCAL_SOURCE_ID

        app = models.MarketplaceApp(
            id=uuid.uuid4(),
            slug=f"test/{uuid.uuid4().hex[:8]}",
            name="Yank Target",
            source_id=LOCAL_SOURCE_ID,
        )
        db.add(app)
        await db.flush()
        av = models.AppVersion(
            id=uuid.uuid4(),
            app_id=app.id,
            version="0.0.1",
            manifest_schema_version="2025-01",
            manifest_json={},
            manifest_hash="sha256:" + uuid.uuid4().hex + uuid.uuid4().hex[:32],
            feature_set_hash="sha256:" + ("0" * 64),
            approval_state="stage2_approved",
            source_id=LOCAL_SOURCE_ID,
        )
        db.add(av)
        # Use medium severity so the local check constraint
        # ``ck_yank_critical_two_admin`` doesn't trip — the marketplace owns
        # the two-admin gate; the local mirror doesn't replicate admin user
        # ids (those are marketplace-side handles, not orchestrator users).
        yank = models.YankRequest(
            id=uuid.uuid4(),
            app_version_id=av.id,
            requester_user_id=user.id,
            severity="medium",
            reason="security incident",
            status="pending",
        )
        db.add(yank)
        await db.flush()

        envelope = {
            "id": str(yank.id),
            "state": "resolved",
            "resolution": "second_admin_confirmed",
        }
        await gov.mirror_yank_into_cache(
            db, local_yank_id=yank.id, marketplace_envelope=envelope
        )
        await db.commit()

        ref_av = (
            await db.execute(select(models.AppVersion).where(models.AppVersion.id == av.id))
        ).scalar_one()
        ref_yank = (
            await db.execute(select(models.YankRequest).where(models.YankRequest.id == yank.id))
        ).scalar_one()
        return {
            "yank_status": ref_yank.status,
            "av_approval": ref_av.approval_state,
            "av_yanked_at": ref_av.yanked_at,
        }

    snapshot = _run_db(_scenario)
    assert snapshot["yank_status"] == "approved"
    assert snapshot["av_approval"] == "yanked"
    assert snapshot["av_yanked_at"] is not None
