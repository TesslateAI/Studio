"""Wave 2 model tests: bundles, approvals, yanks, monitoring, reputation.

Covers:
  - Import/registration: all 10 new Wave-2 models load and attach to
    Base.metadata.
  - Integration: CHECK constraint `ck_yank_critical_two_admin` rejects a
    critical yank approved without both admin ids.
  - Regression guard: Wave-1 models still attach to Base.metadata.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app import models
from app.database import Base


# -- Pure unit: import + metadata registration --------------------------------


def test_wave2_models_registered_on_metadata():
    """All 10 new Wave-2 models must import and attach to Base.metadata."""
    expected = {
        "app_bundles": models.AppBundle,
        "app_bundle_items": models.AppBundleItem,
        "app_submissions": models.AppSubmission,
        "submission_checks": models.SubmissionCheck,
        "yank_requests": models.YankRequest,
        "yank_appeals": models.YankAppeal,
        "monitoring_runs": models.MonitoringRun,
        "adversarial_suites": models.AdversarialSuite,
        "adversarial_runs": models.AdversarialRun,
        "creator_reputation": models.CreatorReputation,
    }
    for tablename, cls in expected.items():
        assert cls.__tablename__ == tablename, f"{cls.__name__} tablename mismatch"
        assert tablename in Base.metadata.tables, (
            f"{tablename} not registered on Base.metadata"
        )


def test_wave1_models_still_register():
    """Regression guard: Wave-1 core hub + wallet models still attach."""
    wave1 = {
        "marketplace_apps": models.MarketplaceApp,
        "app_versions": models.AppVersion,
        "app_instances": models.AppInstance,
        "mcp_consent_records": models.McpConsentRecord,
        "wallets": models.Wallet,
        "wallet_ledger_entries": models.WalletLedgerEntry,
        "spend_records": models.SpendRecord,
    }
    for tablename, cls in wave1.items():
        assert cls.__tablename__ == tablename
        assert tablename in Base.metadata.tables


# -- Integration: CHECK constraint enforcement -------------------------------


@pytest.mark.integration
def test_yank_critical_two_admin_check(db_session):
    """Approving a critical yank without both admins must violate
    ck_yank_critical_two_admin.
    """
    # Arrange: an App + AppVersion for the yank to reference.
    app_id = uuid.uuid4()
    app = models.MarketplaceApp(
        id=app_id,
        slug=f"test/yank-critical-{app_id.hex[:8]}",
        name="Yank Critical Fixture",
    )
    db_session.add(app)
    db_session.flush()

    version = models.AppVersion(
        id=uuid.uuid4(),
        app_id=app_id,
        version="0.0.1",
        manifest_schema_version="2025-01",
        manifest_json={},
        manifest_hash="sha256:" + ("0" * 64),
        feature_set_hash="sha256:" + ("0" * 64),
    )
    db_session.add(version)
    db_session.flush()

    bad_yank = models.YankRequest(
        id=uuid.uuid4(),
        app_version_id=version.id,
        severity="critical",
        reason="test",
        status="approved",
        primary_admin_id=None,
        secondary_admin_id=None,
        decided_at=datetime.now(timezone.utc),
    )
    db_session.add(bad_yank)

    # Act + Assert
    with pytest.raises(IntegrityError) as excinfo:
        db_session.flush()
    assert "ck_yank_critical_two_admin" in str(excinfo.value)
    db_session.rollback()
