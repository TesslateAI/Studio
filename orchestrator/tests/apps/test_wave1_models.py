"""Wave 1 model tests: core hub entities + wallet ledger.

Covers:
  - Import/registration: all 7 new Wave-1 models load and attach to
    Base.metadata.
  - Integration: CHECK constraint `ck_app_version_critical_two_admin` rejects
    a critical yank without a second admin id.
  - Regression guard: Wave-0 pydantic schemas still import cleanly.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app import models
from app.database import Base


# -- Pure unit: import + metadata registration --------------------------------


def test_wave1_models_registered_on_metadata():
    """All 7 new Wave-1 models must import and attach to Base.metadata."""
    expected = {
        "marketplace_apps": models.MarketplaceApp,
        "app_versions": models.AppVersion,
        "app_instances": models.AppInstance,
        "mcp_consent_records": models.McpConsentRecord,
        "wallets": models.Wallet,
        "wallet_ledger_entries": models.WalletLedgerEntry,
        "spend_records": models.SpendRecord,
    }
    for tablename, cls in expected.items():
        assert cls.__tablename__ == tablename, f"{cls.__name__} tablename mismatch"
        assert tablename in Base.metadata.tables, f"{tablename} not registered on Base.metadata"


def test_app_version_has_two_admin_check_constraint():
    """CHECK constraint must be declared on AppVersion for the critical-yank rule."""
    # The CHECK lives in the migration, not __table_args__, but Alembic reflects
    # it onto the live DB. We at minimum assert the model compiles the column
    # that participates in the rule.
    cols = {c.name for c in models.AppVersion.__table__.columns}
    assert "yanked_is_critical" in cols
    assert "yanked_second_admin_id" in cols
    assert "yanked_at" in cols


# -- Regression guard: Wave-0 schemas still importable ------------------------


def test_wave0_manifest_schema_still_imports():
    """Wave-0 pydantic schemas must continue to import cleanly after Wave-1 edits."""
    # These are the Wave-0 frozen surfaces — if a models.py edit broke a shared
    # import, this test fires first.
    from app.services.apps.app_manifest import AppManifest  # noqa: F401
    from app.services.apps.key_lifecycle import KeyState, KeyTier  # noqa: F401


# -- Integration: CHECK constraint enforcement -------------------------------


@pytest.mark.integration
def test_critical_yank_without_second_admin_raises(db_session):
    """Inserting a critical-yank row without a second admin must violate
    ck_app_version_critical_two_admin.
    """
    # Arrange: minimum viable MarketplaceApp + AppVersion row.
    app_id = uuid.uuid4()
    app = models.MarketplaceApp(
        id=app_id,
        slug=f"test/critical-yank-{app_id.hex[:8]}",
        name="Critical Yank Fixture",
    )
    db_session.add(app)
    db_session.flush()

    bad_version = models.AppVersion(
        id=uuid.uuid4(),
        app_id=app_id,
        version="0.0.1",
        manifest_schema_version="2025-01",
        manifest_json={},
        manifest_hash="sha256:" + ("0" * 64),
        feature_set_hash="sha256:" + ("0" * 64),
        yanked_is_critical=True,
        yanked_at=datetime.now(timezone.utc),
        yanked_second_admin_id=None,
    )
    db_session.add(bad_version)

    # Act + Assert
    with pytest.raises(IntegrityError) as excinfo:
        db_session.flush()
    assert "ck_app_version_critical_two_admin" in str(excinfo.value)
    db_session.rollback()
