"""App installer — materializes an approved AppVersion into a user Project.

Flow (single transaction):
    load AppVersion+App -> approval gate -> compat re-check -> dedupe
    installer->app -> validate consent shape -> restore bundle to a new
    volume via Hub -> create Project(app_role=app_instance) -> insert
    AppInstance + McpConsentRecord rows.

Idempotency: the DB has a partial UNIQUE on
`app_instances(project_id) WHERE state='installed' AND project_id IS NOT NULL`.
We also dedupe eagerly via `AlreadyInstalledError` to give callers a clean
error before we hit Hub. IntegrityError at flush time is translated.
"""

from __future__ import annotations

import logging
import secrets as _secrets
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ... import config_features
from ...models import (
    AgentSchedule,
    AppInstallAttempt,
    AppInstance,
    AppVersion,
    Container,
    ContainerConnection,
    MarketplaceApp,
    McpConsentRecord,
    Project,
)
from ..hub_client import HubClient
from . import compatibility

__all__ = [
    "InstallError",
    "AlreadyInstalledError",
    "IncompatibleAppError",
    "ConsentRejectedError",
    "InstallResult",
    "install_app",
]

logger = logging.getLogger(__name__)


_APPROVED_STATES: frozenset[str] = frozenset({"stage1_approved", "stage2_approved"})
_BILLING_DIMENSIONS: tuple[str, ...] = ("ai_compute", "general_compute", "platform_fee")


class InstallError(Exception):
    """Base for install-time failures."""


class AlreadyInstalledError(InstallError):
    """User already has an installed instance of this app."""

    def __init__(self, message: str, app_instance_id: UUID | None = None) -> None:
        super().__init__(message)
        self.app_instance_id = app_instance_id


class IncompatibleAppError(InstallError):
    """AppVersion is not installable in this deployment right now."""


class ConsentRejectedError(InstallError):
    """Installer consent payload doesn't match the manifest's billing shape."""


@dataclass(frozen=True)
class InstallResult:
    app_instance_id: UUID
    project_id: UUID
    volume_id: str
    node_name: str


ProjectFactory = Callable[..., Awaitable[Project]]


async def _default_project_factory(
    db: AsyncSession,
    *,
    name: str,
    team_id: UUID,
    owner_user_id: UUID,
    volume_id: str,
    cache_node: str,
    app_role: str,
) -> Project:
    """Minimum-viable Project creation for the installer. Callers that need
    container specs or richer setup should pass their own factory."""
    # Slug must be unique + URL-safe. A short uuid suffix is fine for the
    # app_instance case; install UIs may rename the project later.
    suffix = uuid.uuid4().hex[:8]
    base = "".join(c if c.isalnum() or c in "-_" else "-" for c in name.lower()).strip("-") or "app"
    slug = f"{base}-{suffix}"
    project = Project(
        name=name,
        slug=slug,
        owner_id=owner_user_id,
        team_id=team_id,
        visibility="team",
        volume_id=volume_id,
        cache_node=cache_node,
        app_role=app_role,
    )
    db.add(project)
    await db.flush()
    return project


def _consent_matches_billing(consent: dict[str, Any], billing: dict[str, Any]) -> bool:
    """Every billing dimension present in the manifest must also be present
    (by key) in the consent payload. Accepts either a flat consent
    (``{ai_compute: {...}}``) or a nested one under ``dimensions``
    (``{accepted, dimensions: {ai_compute: {...}}}``). We don't validate
    values here — that's the billing dispatcher's job in Wave 3."""
    raw_nested = consent.get("dimensions")
    if isinstance(raw_nested, dict):
        nested_keys = set(raw_nested.keys())
    elif isinstance(raw_nested, list):
        nested_keys = {
            x.get("dimension") for x in raw_nested if isinstance(x, dict) and x.get("dimension")
        }
    else:
        nested_keys = set()
    for dim in _BILLING_DIMENSIONS:
        if dim in billing and dim not in consent and dim not in nested_keys:
            return False
    return True


async def install_app(
    db: AsyncSession,
    *,
    installer_user_id: UUID,
    app_version_id: UUID,
    hub_client: HubClient,
    wallet_mix_consent: dict[str, Any],
    mcp_consents: list[dict[str, Any]],
    team_id: UUID,
    update_policy: str = "manual",
    project_factory: ProjectFactory | None = None,
) -> InstallResult:
    # 1) Load AppVersion + MarketplaceApp.
    av = (
        await db.execute(select(AppVersion).where(AppVersion.id == app_version_id))
    ).scalar_one_or_none()
    if av is None:
        raise IncompatibleAppError(f"AppVersion {app_version_id} not found")
    app_row = (
        await db.execute(select(MarketplaceApp).where(MarketplaceApp.id == av.app_id))
    ).scalar_one_or_none()
    if app_row is None:
        raise IncompatibleAppError(f"MarketplaceApp {av.app_id} not found")

    # Approval gate. Dev flag allows installing pending_stage1 locally.
    from ._auto_approve_flag import is_auto_approve_enabled

    skip_approval = is_auto_approve_enabled()
    allowed_states = set(_APPROVED_STATES)
    if skip_approval:
        allowed_states.add("pending_stage1")
    if av.approval_state not in allowed_states:
        raise IncompatibleAppError(
            f"AppVersion {app_version_id} has approval_state={av.approval_state!r}"
        )
    if app_row.state in {"yanked", "deprecated"}:
        raise IncompatibleAppError(f"MarketplaceApp {app_row.id} is {app_row.state}")

    # 2) Compat re-check against the current server feature set.
    manifest_json = av.manifest_json or {}
    required = list(av.required_features or [])
    manifest_schema = (
        manifest_json.get("compatibility", {}).get("manifest_schema")
        or manifest_json.get("manifest_schema_version")
        or ""
    )
    report = compatibility.check(
        required_features=required,
        manifest_schema=manifest_schema,
    )
    if not report.compatible:
        raise IncompatibleAppError(
            f"server incompatible: missing={report.missing_features} "
            f"unsupported_schema={report.unsupported_manifest_schema}"
        )

    # 3) Dedupe: one installed instance per (installer, app).
    existing_instance_id = (
        await db.execute(
            select(AppInstance.id)
            .where(
                AppInstance.installer_user_id == installer_user_id,
                AppInstance.app_id == app_row.id,
                AppInstance.state == "installed",
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing_instance_id is not None:
        raise AlreadyInstalledError(
            f"user {installer_user_id} already has app {app_row.id} installed",
            app_instance_id=existing_instance_id,
        )

    # 4) Consent shape check against manifest.billing.
    billing = manifest_json.get("billing") or {}
    if not _consent_matches_billing(wallet_mix_consent, billing):
        raise ConsentRejectedError(
            "wallet_mix_consent missing dimensions required by manifest.billing"
        )

    # 5) Restore the bundle to a new volume on some node.
    if not av.bundle_hash:
        raise IncompatibleAppError(
            f"AppVersion {app_version_id} has no bundle_hash; cannot install"
        )
    volume_id, node_name = await hub_client.create_volume_from_bundle(
        bundle_hash=av.bundle_hash,
    )

    # 5a) Saga ledger: record the Hub-side volume in an INDEPENDENT session
    # and commit immediately, so every volume has a persistent marker that
    # predates any downstream DB writes. If the rest of this function
    # crashes (worker SIGKILL, flush fails, caller's commit fails), the
    # orphan reaper (see install_reaper.py) picks up this row and frees the
    # volume. The ``attempt_id`` is linked to the resulting AppInstance at
    # step 9 below via a second independent commit.
    attempt_id = await _record_install_attempt(
        marketplace_app_id=app_row.id,
        app_version_id=av.id,
        installer_user_id=installer_user_id,
        volume_id=volume_id,
        node_name=node_name,
        bundle_hash=av.bundle_hash,
    )

    # 6) Create the app_instance Project.
    factory = project_factory or _default_project_factory
    project = await factory(
        db,
        name=f"{app_row.name} (installed)",
        team_id=team_id,
        owner_user_id=installer_user_id,
        volume_id=volume_id,
        cache_node=node_name,
        app_role="app_instance",
    )
    # App instances don't need template-build provisioning — the volume was
    # materialized from the bundle. Mark ready so the orchestrator start path
    # (shared with user projects) doesn't bail at its provisioning gate.
    project.environment_status = "ready"

    # 7) Materialize Containers + Connections from manifest.compute.
    compute = manifest_json.get("compute") or {}
    container_specs = list(compute.get("containers") or [])
    compute_model = str(compute.get("model") or "always-on")
    if compute_model == "job-only":
        logger.info(
            "install_app: app=%s version=%s is job-only — containers will be marked status=job_only",
            app_row.id,
            av.id,
        )
    initial_status = "job_only" if compute_model == "job-only" else "stopped"
    containers_by_name: dict[str, Container] = {}
    primary_container: Container | None = None

    for entry in container_specs:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            raise IncompatibleAppError("manifest compute.containers entry missing 'name'")
        image = entry.get("image")
        if not image:
            raise IncompatibleAppError(f"manifest compute.containers[{name}] missing 'image'")
        ports = entry.get("ports") or []
        port = ports[0] if ports else None
        directory = entry.get("directory") or "/app"
        is_primary = bool(entry.get("primary", False))

        env_in = dict(entry.get("env") or {})

        c = Container(
            project_id=project.id,
            name=name,
            directory=directory,
            container_name=f"{project.slug}-{name}",
            port=port,
            internal_port=port,
            startup_command=entry.get("startup_command"),
            environment_vars=env_in,
            image=str(image),
            status=initial_status,
            container_type=("service" if entry.get("kind") == "service" else "base"),
            is_primary=is_primary,
        )
        db.add(c)
        containers_by_name[name] = c
        if is_primary and primary_container is None:
            primary_container = c

    # Default primary if none marked: first container inserted.
    if primary_container is None and containers_by_name:
        first = next(iter(containers_by_name.values()))
        first.is_primary = True
        primary_container = first

    # Flush so Container.id values are available for FK references below.
    if containers_by_name:
        await db.flush()

    for conn in compute.get("connections") or []:
        if not isinstance(conn, dict):
            continue
        src_name = conn.get("source") or conn.get("source_name")
        tgt_name = conn.get("target") or conn.get("target_name")
        src = containers_by_name.get(src_name) if src_name else None
        tgt = containers_by_name.get(tgt_name) if tgt_name else None
        if src is None or tgt is None:
            logger.warning(
                "install_app: skipping connection %r->%r (unknown name)",
                src_name,
                tgt_name,
            )
            continue
        db.add(
            ContainerConnection(
                project_id=project.id,
                source_container_id=src.id,
                target_container_id=tgt.id,
                connector_type=conn.get("connector_type", "env_injection"),
                config=conn.get("config") or {"env_mapping": conn.get("env_mapping") or {}},
                label=conn.get("label"),
            )
        )

    # 8) Insert AppInstance + McpConsentRecord rows.
    now = datetime.now(UTC)
    instance = AppInstance(
        app_id=app_row.id,
        app_version_id=av.id,
        installer_user_id=installer_user_id,
        project_id=project.id,
        state="installed",
        consent_record=wallet_mix_consent,
        wallet_mix=wallet_mix_consent,
        update_policy=update_policy,
        volume_id=volume_id,
        feature_set_hash=config_features.feature_set_hash(),
        primary_container_id=(primary_container.id if primary_container else None),
        installed_at=now,
    )
    db.add(instance)
    try:
        await db.flush()
    except IntegrityError as e:
        # Partial UNIQUE on project_id caught a concurrent install. Translate.
        await db.rollback()
        raise AlreadyInstalledError(
            f"project {project.id} already has an installed app instance"
        ) from e

    for consent in mcp_consents:
        server_id = consent.get("mcp_server_id")
        if not server_id:
            raise ConsentRejectedError("mcp_consents entry missing 'mcp_server_id'")
        db.add(
            McpConsentRecord(
                app_instance_id=instance.id,
                mcp_server_id=server_id,
                scopes=list(consent.get("scopes", [])),
            )
        )

    # 9) Materialize AgentSchedule rows for manifest.schedules.
    for sched in manifest_json.get("schedules") or []:
        if not isinstance(sched, dict):
            continue
        sched_name = str(sched.get("name") or "").strip()
        if not sched_name:
            logger.warning("install_app: skipping schedule without name")
            continue
        trigger_kind = str(sched.get("trigger_kind") or "cron")
        default_cron = sched.get("default_cron") or ("0 0 * * *" if trigger_kind == "cron" else "")
        trigger_config: dict[str, Any] = {
            "execution": sched.get("execution", "job"),
            "entrypoint": sched.get("entrypoint"),
        }
        if trigger_kind == "webhook":
            # Per-schedule HMAC secrets are stored as a kid-keyed list so they
            # can be rotated and revoked without losing back-compat for callers
            # mid-flight. The verifier in routers/app_triggers.py also accepts
            # the legacy single-key shape ({"webhook_secret": "..."}) for one
            # release; new installs always emit the list form.
            trigger_config["webhook_secrets"] = [
                {
                    "kid": "v1",
                    "secret": _secrets.token_urlsafe(32),
                    "created_at": datetime.now(UTC).isoformat(),
                    "revoked_at": None,
                }
            ]
        db.add(
            AgentSchedule(
                user_id=installer_user_id,
                project_id=project.id,
                app_instance_id=instance.id,
                name=sched_name,
                cron_expression=default_cron or "",
                normalized_cron=default_cron or "",
                prompt_template=sched.get("prompt_template") or "",
                trigger_kind=trigger_kind,
                trigger_config=trigger_config,
                is_active=True,
            )
        )

    await db.flush()

    logger.info(
        "install_app: app=%s version=%s installer=%s project=%s volume=%s attempt=%s",
        app_row.id,
        av.id,
        installer_user_id,
        project.id,
        volume_id,
        attempt_id,
    )

    # Saga ledger: flip the attempt row to committed in a second independent
    # session. If this call fails the reaper still converges — it joins on
    # volume_id / app_instance_id and skips rows that already have a live
    # AppInstance.
    await _mark_attempt_committed(
        attempt_id=attempt_id,
        app_instance_id=instance.id,
    )

    return InstallResult(
        app_instance_id=instance.id,
        project_id=project.id,
        volume_id=volume_id,
        node_name=node_name,
    )


async def _record_install_attempt(
    *,
    marketplace_app_id: UUID,
    app_version_id: UUID,
    installer_user_id: UUID,
    volume_id: str,
    node_name: str | None,
    bundle_hash: str | None,
) -> UUID:
    """Insert an AppInstallAttempt in an independent session and commit.

    Runs OUTSIDE the caller's transaction so the row survives even if the
    caller rolls back. Best-effort: if the insert fails, log and return a
    nil UUID — the install still proceeds (we just lose reaper coverage
    for this particular attempt). This is a ledger, not a gate.
    """
    from ...database import AsyncSessionLocal

    attempt_id = uuid.uuid4()
    try:
        async with AsyncSessionLocal() as session:
            session.add(
                AppInstallAttempt(
                    id=attempt_id,
                    marketplace_app_id=marketplace_app_id,
                    app_version_id=app_version_id,
                    installer_user_id=installer_user_id,
                    state="hub_created",
                    volume_id=volume_id,
                    node_name=node_name,
                    bundle_hash=bundle_hash,
                )
            )
            await session.commit()
    except Exception:
        logger.exception(
            "install_app: failed to record install attempt (volume=%s); "
            "continuing without reaper coverage for this attempt",
            volume_id,
        )
    return attempt_id


async def _mark_attempt_committed(
    *,
    attempt_id: UUID,
    app_instance_id: UUID,
) -> None:
    """Flip AppInstallAttempt to state='committed' in an independent session.

    Best-effort: failure here is non-fatal. The reaper's convergence rule
    (skip attempt whose volume_id matches a live AppInstance.volume_id) still
    protects the volume.
    """
    from ...database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as session:
            row = (
                await session.execute(
                    select(AppInstallAttempt).where(AppInstallAttempt.id == attempt_id)
                )
            ).scalar_one_or_none()
            if row is None:
                return
            row.state = "committed"
            row.app_instance_id = app_instance_id
            row.committed_at = datetime.now(UTC)
            await session.commit()
    except Exception:
        logger.exception(
            "install_app: failed to mark install attempt committed (attempt_id=%s)",
            attempt_id,
        )
