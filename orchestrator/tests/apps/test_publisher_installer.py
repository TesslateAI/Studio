"""Wave 2 publisher + installer service tests.

Unit tests (no DB):
  - compatibility happy / missing-feature / unsupported-schema paths.

Integration tests (`@pytest.mark.integration`):
  - publish happy path + duplicate rejection.
  - install happy path + dedupe enforcement + approval gate.

Integration tests rely on the shared `db_session` fixture used elsewhere in
`tests/apps/`. A `FakeHubClient` stands in for the real gRPC client.
"""

from __future__ import annotations

import os
import uuid
from copy import deepcopy
from typing import Any
from uuid import UUID

import pytest

from app import config_features, models
from app.services.apps import compatibility, installer, publisher


# ---------------------------------------------------------------------------
# Fake Hub client — async, deterministic.
# ---------------------------------------------------------------------------


class FakeHubClient:
    def __init__(
        self,
        *,
        bundle_hash: str = "sha256:" + ("a" * 64),
        volume_id: str = "vol-installed-1",
        node_name: str = "node-a",
    ) -> None:
        self._bundle_hash = bundle_hash
        self._volume_id = volume_id
        self._node_name = node_name
        self.publish_calls: list[dict[str, Any]] = []
        self.create_calls: list[dict[str, Any]] = []

    async def publish_bundle(
        self, *, volume_id: str, app_id: str, version: str, timeout: float = 600.0
    ) -> str:
        self.publish_calls.append(
            {"volume_id": volume_id, "app_id": app_id, "version": version}
        )
        return self._bundle_hash

    async def create_volume_from_bundle(
        self,
        *,
        bundle_hash: str,
        hint_node: str | None = None,
        timeout: float = 600.0,
    ) -> tuple[str, str]:
        self.create_calls.append({"bundle_hash": bundle_hash, "hint_node": hint_node})
        return self._volume_id, self._node_name


# ---------------------------------------------------------------------------
# Manifest builders.
# ---------------------------------------------------------------------------


def _minimal_manifest(version: str = "0.1.0", slug: str | None = None) -> dict[str, Any]:
    slug = slug or f"hello-{uuid.uuid4().hex[:6]}"
    return {
        "manifest_schema_version": "2025-01",
        "app": {
            "id": f"com.example.{slug}",
            "name": "Hello App",
            "slug": slug,
            "version": version,
        },
        "compatibility": {
            "studio": {"min": "3.2.0"},
            "manifest_schema": "2025-01",
            "runtime_api": "^1.0",
            "required_features": [],
        },
        "surfaces": [{"kind": "ui", "entrypoint": "index.html"}],
        "state": {"model": "stateless"},
        "billing": {
            "ai_compute": {"payer": "installer"},
            "general_compute": {"payer": "installer"},
            "platform_fee": {"model": "free", "price_usd": 0},
        },
        "listing": {"visibility": "public"},
    }


# ---------------------------------------------------------------------------
# Unit tests — compatibility (pure).
# ---------------------------------------------------------------------------


def test_compatibility_check_missing_feature(monkeypatch):
    # Force the resolved feature set to NOT include the required flag.
    monkeypatch.setattr(
        config_features, "current_feature_set", lambda: ["cas_bundle", "volume_fork"]
    )
    report = compatibility.check(
        required_features=["apps.runtime.ui"],
        manifest_schema="2025-01",
    )
    assert report.compatible is False
    assert "apps.runtime.ui" in report.missing_features
    assert report.unsupported_manifest_schema is False
    assert report.upgrade_required is False


def test_compatibility_check_unsupported_schema(monkeypatch):
    monkeypatch.setattr(
        config_features, "current_feature_set", lambda: ["cas_bundle"]
    )
    report = compatibility.check(
        required_features=[],
        manifest_schema="2999-99",
    )
    assert report.compatible is False
    assert report.unsupported_manifest_schema is True
    assert report.missing_features == []


def test_compatibility_check_happy_path(monkeypatch):
    monkeypatch.setattr(
        config_features,
        "current_feature_set",
        lambda: ["apps.runtime.ui", "cas_bundle", "volume_fork", "volume_snapshot"],
    )
    report = compatibility.check(
        required_features=["apps.runtime.ui", "cas_bundle"],
        manifest_schema="2025-01",
    )
    assert report.compatible is True
    assert report.missing_features == []
    assert report.unsupported_manifest_schema is False
    assert "2025-01" in report.server_manifest_schemas
    assert report.server_feature_set_hash  # hash is non-empty


# ---------------------------------------------------------------------------
# Integration tests — require db_session + live Postgres.
# ---------------------------------------------------------------------------


def _make_source_project(db_session, owner_user_id: UUID, team_id: UUID) -> models.Project:
    project = models.Project(
        id=uuid.uuid4(),
        name="Source Project",
        slug=f"src-{uuid.uuid4().hex[:8]}",
        owner_id=owner_user_id,
        team_id=team_id,
        visibility="team",
        volume_id=f"vol-source-{uuid.uuid4().hex[:8]}",
        app_role="app_source",
    )
    db_session.add(project)
    db_session.flush()
    return project


@pytest.mark.integration
async def test_publish_version_happy_path(db_session, test_user, test_team):
    project = _make_source_project(db_session, test_user.id, test_team.id)
    manifest = _minimal_manifest()
    hub = FakeHubClient()

    result = await publisher.publish_version(
        db_session,
        creator_user_id=test_user.id,
        project_id=project.id,
        manifest_source=manifest,
        hub_client=hub,
    )

    assert hub.publish_calls == [
        {
            "volume_id": project.volume_id,
            "app_id": str(result.app_id),
            "version": "0.1.0",
        }
    ]
    app = db_session.get(models.MarketplaceApp, result.app_id)
    assert app is not None and app.slug == manifest["app"]["slug"]
    av = db_session.get(models.AppVersion, result.app_version_id)
    assert av is not None
    assert av.bundle_hash == result.bundle_hash
    assert av.manifest_hash == result.manifest_hash
    assert av.approval_state == "pending_stage1"
    sub = db_session.get(models.AppSubmission, result.submission_id)
    assert sub is not None and sub.stage == "stage0"


@pytest.mark.integration
async def test_publish_duplicate_version_raises(db_session, test_user, test_team):
    project = _make_source_project(db_session, test_user.id, test_team.id)
    manifest = _minimal_manifest()
    hub = FakeHubClient()

    first = await publisher.publish_version(
        db_session,
        creator_user_id=test_user.id,
        project_id=project.id,
        manifest_source=manifest,
        hub_client=hub,
    )

    with pytest.raises(publisher.DuplicateVersionError):
        await publisher.publish_version(
            db_session,
            creator_user_id=test_user.id,
            project_id=project.id,
            manifest_source=deepcopy(manifest),
            hub_client=hub,
            app_id=first.app_id,
        )


def _seed_approved_version(
    db_session, creator_user_id: UUID, approval_state: str = "stage1_approved"
) -> tuple[models.MarketplaceApp, models.AppVersion]:
    manifest = _minimal_manifest()
    app = models.MarketplaceApp(
        id=uuid.uuid4(),
        slug=manifest["app"]["slug"],
        name=manifest["app"]["name"],
        creator_user_id=creator_user_id,
        state="draft",
        visibility="public",
    )
    db_session.add(app)
    db_session.flush()
    av = models.AppVersion(
        id=uuid.uuid4(),
        app_id=app.id,
        version=manifest["app"]["version"],
        manifest_schema_version="2025-01",
        manifest_json=manifest,
        manifest_hash="sha256:" + ("1" * 64),
        bundle_hash="sha256:" + ("2" * 64),
        feature_set_hash=config_features.feature_set_hash(),
        required_features=[],
        approval_state=approval_state,
    )
    db_session.add(av)
    db_session.flush()
    return app, av


@pytest.mark.integration
async def test_install_app_happy_path(db_session, test_user, test_team):
    _, av = _seed_approved_version(db_session, test_user.id)
    hub = FakeHubClient()
    consent = {
        "ai_compute": {"payer": "installer"},
        "general_compute": {"payer": "installer"},
        "platform_fee": {"model": "free"},
    }
    mcp_consents = [
        {"mcp_server_id": "github", "scopes": ["repo.read"]},
        {"mcp_server_id": "slack", "scopes": ["chat.write"]},
    ]

    result = await installer.install_app(
        db_session,
        installer_user_id=test_user.id,
        app_version_id=av.id,
        hub_client=hub,
        wallet_mix_consent=consent,
        mcp_consents=mcp_consents,
        team_id=test_team.id,
    )

    project = db_session.get(models.Project, result.project_id)
    assert project is not None and project.app_role == "app_instance"
    assert project.volume_id == result.volume_id
    inst = db_session.get(models.AppInstance, result.app_instance_id)
    assert inst is not None and inst.state == "installed"
    assert inst.wallet_mix == consent
    records = (
        db_session.query(models.McpConsentRecord)
        .filter_by(app_instance_id=inst.id)
        .all()
    )
    assert {r.mcp_server_id for r in records} == {"github", "slack"}


@pytest.mark.integration
async def test_install_one_project_one_app_enforced(db_session, test_user, test_team):
    _, av = _seed_approved_version(db_session, test_user.id)
    hub = FakeHubClient()
    consent = {
        "ai_compute": {"payer": "installer"},
        "general_compute": {"payer": "installer"},
        "platform_fee": {"model": "free"},
    }
    await installer.install_app(
        db_session,
        installer_user_id=test_user.id,
        app_version_id=av.id,
        hub_client=hub,
        wallet_mix_consent=consent,
        mcp_consents=[],
        team_id=test_team.id,
    )
    with pytest.raises(installer.AlreadyInstalledError):
        await installer.install_app(
            db_session,
            installer_user_id=test_user.id,
            app_version_id=av.id,
            hub_client=FakeHubClient(volume_id="vol-installed-2"),
            wallet_mix_consent=consent,
            mcp_consents=[],
            team_id=test_team.id,
        )


@pytest.mark.integration
async def test_install_unapproved_rejected_without_flag(
    db_session, test_user, test_team, monkeypatch
):
    _, av = _seed_approved_version(
        db_session, test_user.id, approval_state="pending_stage1"
    )
    hub = FakeHubClient()
    consent = {
        "ai_compute": {"payer": "installer"},
        "general_compute": {"payer": "installer"},
        "platform_fee": {"model": "free"},
    }
    # Flag OFF → rejected.
    monkeypatch.delenv("TSL_APPS_SKIP_APPROVAL", raising=False)
    monkeypatch.delenv("TSL_APPS_DEV_AUTO_APPROVE", raising=False)
    with pytest.raises(installer.IncompatibleAppError):
        await installer.install_app(
            db_session,
            installer_user_id=test_user.id,
            app_version_id=av.id,
            hub_client=hub,
            wallet_mix_consent=consent,
            mcp_consents=[],
            team_id=test_team.id,
        )
    # Flag ON → succeeds.
    monkeypatch.setenv("TSL_APPS_DEV_AUTO_APPROVE", "1")
    result = await installer.install_app(
        db_session,
        installer_user_id=test_user.id,
        app_version_id=av.id,
        hub_client=hub,
        wallet_mix_consent=consent,
        mcp_consents=[],
        team_id=test_team.id,
    )
    assert result.app_instance_id is not None
