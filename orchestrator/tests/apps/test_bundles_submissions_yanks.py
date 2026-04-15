"""Wave 2 service-layer tests: bundles, submissions, yanks, monitoring.

Unit tests (no DB) exercise pure logic: submission transition guards and
the critical-yank two-admin protocol (via an in-memory fake session).

Integration tests (marked `integration`) round-trip against the Postgres
test DB and verify consolidated hashes, slug conflicts, AppVersion
cascades, and the reputation UPSERT accumulator.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from app import models
from app.services.apps import bundles, monitoring, submissions, yanks


# ============================================================================
# Unit tests — no DB
# ============================================================================


class _FakeResult:
    def __init__(self, row: Any):
        self._row = row

    def scalar_one_or_none(self):
        return self._row

    def scalars(self):
        class _S:
            def __init__(self, row):
                self._row = row

            def all(self_inner):
                if self_inner._row is None:
                    return []
                return [self_inner._row] if not isinstance(
                    self_inner._row, list
                ) else self_inner._row

        return _S(self._row)


class _FakeSession:
    """Tiny async-session fake that returns a single pre-seeded row for any
    SELECT and a no-op flush. Enough for the yanks unit test."""

    def __init__(self, row: Any, av_row: Any = None):
        self._row = row
        self._av_row = av_row
        self._call_count = 0

    async def execute(self, _stmt):
        # First query: the YankRequest load. Second (if any): AppVersion.
        self._call_count += 1
        if self._call_count == 1:
            return _FakeResult(self._row)
        return _FakeResult(self._av_row)

    async def flush(self):
        return None


@dataclass
class _YankRow:
    id: UUID
    app_version_id: UUID
    severity: str
    reason: str = "reason"
    status: str = "pending"
    primary_admin_id: UUID | None = None
    secondary_admin_id: UUID | None = None
    decided_at: datetime | None = None


@dataclass
class _AvRow:
    id: UUID
    approval_state: str = "stage2_approved"
    yanked_at: datetime | None = None
    yanked_reason: str | None = None
    yanked_by_user_id: UUID | None = None
    yanked_is_critical: bool = False
    yanked_second_admin_id: UUID | None = None


@pytest.mark.asyncio
async def test_submission_transitions_enforced():
    """VALID_TRANSITIONS is the single source of truth.

    - approved -> anywhere raises
    - stage0 -> stage2 (skipping stage1) raises
    - stage0 -> stage1 is allowed (no raise from the pure guard)
    """
    # Pure-guard invocation via the private helper exposed through the
    # module's behaviour: we instead verify the table directly + simulate.
    # Approved is terminal.
    assert submissions.VALID_TRANSITIONS["approved"] == set()
    assert submissions.VALID_TRANSITIONS["rejected"] == set()
    # stage0 cannot skip to stage2.
    assert "stage2" not in submissions.VALID_TRANSITIONS["stage0"]
    # stage0 -> stage1 legal.
    assert "stage1" in submissions.VALID_TRANSITIONS["stage0"]

    # Drive advance_stage against a fake session whose row is in 'approved'.
    sub_id = uuid.uuid4()
    av_id = uuid.uuid4()

    @dataclass
    class _SubRow:
        id: UUID = sub_id
        app_version_id: UUID = av_id
        stage: str = "approved"
        stage_entered_at: datetime = field(
            default_factory=lambda: datetime.now(timezone.utc)
        )
        reviewer_user_id: UUID | None = None
        decision: str = "approved"
        decision_notes: str | None = None

    sess = _FakeSession(_SubRow())
    with pytest.raises(submissions.InvalidTransitionError):
        await submissions.advance_stage(
            sess, submission_id=sub_id, to_stage="stage1"
        )

    # stage0 -> stage2 skipping stage1.
    sess2 = _FakeSession(_SubRow(stage="stage0", decision="pending"))
    with pytest.raises(submissions.InvalidTransitionError):
        await submissions.advance_stage(
            sess2, submission_id=sub_id, to_stage="stage2"
        )


@pytest.mark.asyncio
async def test_yank_critical_needs_two_admins():
    """Critical yank: first admin -> needs_second_admin; same admin twice ->
    NeedsSecondAdminError; different admin -> approved."""
    yank_id = uuid.uuid4()
    av_id = uuid.uuid4()
    admin_a = uuid.uuid4()
    admin_b = uuid.uuid4()

    row = _YankRow(id=yank_id, app_version_id=av_id, severity="critical")
    av = _AvRow(id=av_id)

    # First admin signs -> pending + needs_second_admin flag.
    sess = _FakeSession(row, av)
    result = await yanks.approve_yank(
        sess, yank_request_id=yank_id, admin_user_id=admin_a
    )
    assert result == {"needs_second_admin": True}
    assert row.primary_admin_id == admin_a
    assert row.status == "pending"

    # Same admin tries to double-sign -> NeedsSecondAdminError.
    sess_dup = _FakeSession(row, av)
    with pytest.raises(yanks.NeedsSecondAdminError):
        await yanks.approve_yank(
            sess_dup, yank_request_id=yank_id, admin_user_id=admin_a
        )

    # Distinct admin finalizes -> approved + AV cascaded.
    sess_final = _FakeSession(row, av)
    result2 = await yanks.approve_yank(
        sess_final, yank_request_id=yank_id, admin_user_id=admin_b
    )
    assert result2 == {"status": "approved"}
    assert row.status == "approved"
    assert row.secondary_admin_id == admin_b
    assert av.approval_state == "yanked"
    assert av.yanked_is_critical is True


# ============================================================================
# Integration tests — live DB
# ============================================================================


def _make_app_version(db_session, *, approval_state: str = "stage2_approved"):
    """Create a MarketplaceApp + AppVersion; return the AppVersion."""
    app_id = uuid.uuid4()
    app = models.MarketplaceApp(
        id=app_id,
        slug=f"test/app-{app_id.hex[:8]}",
        name="Test App",
    )
    db_session.add(app)
    db_session.flush()

    av = models.AppVersion(
        id=uuid.uuid4(),
        app_id=app_id,
        version="0.0.1",
        manifest_schema_version="2025-01",
        manifest_json={},
        manifest_hash="sha256:" + uuid.uuid4().hex + uuid.uuid4().hex[:32],
        feature_set_hash="sha256:" + ("0" * 64),
        approval_state=approval_state,
    )
    db_session.add(av)
    db_session.flush()
    return av


def _make_user(db_session):
    user = models.User(
        id=uuid.uuid4(),
        username=f"u-{uuid.uuid4().hex[:8]}",
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_bundle_computes_consolidated_hash(db_session):
    owner = _make_user(db_session)
    av1 = _make_app_version(db_session)
    av2 = _make_app_version(db_session)

    items = [
        bundles.BundleItemSpec(app_version_id=av1.id, order_index=0),
        bundles.BundleItemSpec(app_version_id=av2.id, order_index=1),
    ]
    bundle_id = await bundles.create_bundle(
        db_session,
        owner_user_id=owner.id,
        slug=f"bundle-{uuid.uuid4().hex[:8]}",
        display_name="B1",
        items=items,
    )
    got = await bundles.get_bundle(db_session, bundle_id=bundle_id)
    assert got["consolidated_manifest_hash"] is not None
    assert len(got["items"]) == 2

    # Order-independent: reversing the items should yield the same hash.
    bundle_id_rev = await bundles.create_bundle(
        db_session,
        owner_user_id=owner.id,
        slug=f"bundle-{uuid.uuid4().hex[:8]}",
        display_name="B1-rev",
        items=list(reversed(items)),
    )
    got_rev = await bundles.get_bundle(db_session, bundle_id=bundle_id_rev)
    assert got_rev["consolidated_manifest_hash"] == got["consolidated_manifest_hash"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bundle_slug_conflict(db_session):
    owner = _make_user(db_session)
    av = _make_app_version(db_session)
    slug = f"bundle-dup-{uuid.uuid4().hex[:8]}"
    items = [bundles.BundleItemSpec(app_version_id=av.id)]
    await bundles.create_bundle(
        db_session,
        owner_user_id=owner.id,
        slug=slug,
        display_name="B",
        items=items,
    )
    with pytest.raises(bundles.BundleSlugTakenError):
        await bundles.create_bundle(
            db_session,
            owner_user_id=owner.id,
            slug=slug,
            display_name="B again",
            items=items,
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_approve_yank_noncritical_happy_path(db_session):
    admin = _make_user(db_session)
    requester = _make_user(db_session)
    av = _make_app_version(db_session)
    yid = await yanks.request_yank(
        db_session,
        requester_user_id=requester.id,
        app_version_id=av.id,
        severity="low",
        reason="bug",
    )
    result = await yanks.approve_yank(
        db_session, yank_request_id=yid, admin_user_id=admin.id
    )
    assert result == {"status": "approved"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_approve_yank_critical_two_admin_happy_path(db_session):
    admin_a = _make_user(db_session)
    admin_b = _make_user(db_session)
    requester = _make_user(db_session)
    av = _make_app_version(db_session)
    yid = await yanks.request_yank(
        db_session,
        requester_user_id=requester.id,
        app_version_id=av.id,
        severity="critical",
        reason="security",
    )
    r1 = await yanks.approve_yank(
        db_session, yank_request_id=yid, admin_user_id=admin_a.id
    )
    assert r1 == {"needs_second_admin": True}
    r2 = await yanks.approve_yank(
        db_session, yank_request_id=yid, admin_user_id=admin_b.id
    )
    assert r2 == {"status": "approved"}
    # DB CHECK constraint was NOT triggered — both admin ids populated.


@pytest.mark.integration
@pytest.mark.asyncio
async def test_submission_advance_to_approved_flips_app_version(db_session):
    submitter = _make_user(db_session)
    reviewer = _make_user(db_session)
    av = _make_app_version(db_session, approval_state="pending_stage1")

    sub = models.AppSubmission(
        id=uuid.uuid4(),
        app_version_id=av.id,
        submitter_user_id=submitter.id,
        stage="stage3",
    )
    db_session.add(sub)
    db_session.flush()

    await submissions.advance_stage(
        db_session,
        submission_id=sub.id,
        to_stage="approved",
        reviewer_user_id=reviewer.id,
        decision_notes="lgtm",
    )
    db_session.refresh(av)
    assert av.approval_state == "stage2_approved"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_upsert_creator_reputation_accumulates(db_session):
    user = _make_user(db_session)
    await monitoring.upsert_creator_reputation(
        db_session, user_id=user.id, delta_yanks=1
    )
    await monitoring.upsert_creator_reputation(
        db_session, user_id=user.id, delta_yanks=1, delta_score=Decimal("0.5")
    )
    row = db_session.get(models.CreatorReputation, user.id)
    assert row is not None
    assert row.yanks_count == 2
    assert row.score == Decimal("0.5")
