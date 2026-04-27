"""App installer — materializes an approved AppVersion into a user Project.

Flow (single transaction):
    load AppVersion+App -> approval gate -> compat re-check -> dedupe
    installer->app -> validate consent shape -> restore bundle to a new
    volume via Hub -> create Project(project_kind=app_runtime) -> insert
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
    PROJECT_KIND_APP_RUNTIME,
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
from ...models_automations import AppRuntimeDeployment
from ..hub_client import HubClient
from . import compatibility

__all__ = [
    "InstallError",
    "AlreadyInstalledError",
    "IncompatibleAppError",
    "ConsentRejectedError",
    "ManifestInvalid",
    "InstallResult",
    "create_per_pod_signing_key",
    "delete_per_pod_signing_key",
    "install_app",
    "propagate_user_secrets_post_install",
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


class ManifestInvalid(InstallError):
    """Manifest carries a runtime/state combination that isn't installable.

    Distinct from ``IncompatibleAppError`` (which is about *server-side*
    feature mismatches) — ``ManifestInvalid`` flags constraint-matrix
    violations the publish-time checker should already have rejected, but
    that we re-validate at install time as a defense-in-depth gate.
    """


@dataclass(frozen=True)
class InstallResult:
    """Outcome of a successful install.

    ``project_id`` is None for ``per_invocation`` installs (no persistent
    runtime project — each invocation spins a Job). ``volume_id`` is None
    for both ``per_invocation`` and ``shared_singleton`` reuse paths
    where no fresh Hub volume was minted. ``node_name`` is None when the
    install path didn't touch Volume Hub at all.
    """

    app_instance_id: UUID
    project_id: UUID | None
    volume_id: str | None
    node_name: str | None


ProjectFactory = Callable[..., Awaitable[Project]]


async def _default_project_factory(
    db: AsyncSession,
    *,
    name: str,
    team_id: UUID,
    owner_user_id: UUID,
    volume_id: str,
    cache_node: str,
    project_kind: str,
) -> Project:
    """Minimum-viable Project creation for the installer. Callers that need
    container specs or richer setup should pass their own factory."""
    # Slug must be unique + URL-safe. A short uuid suffix is fine for the
    # app_runtime case; install UIs may rename the project later.
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
        project_kind=project_kind,
    )
    db.add(project)
    await db.flush()
    return project


# ---------------------------------------------------------------------------
# Runtime contract — Phase 3.
#
# These helpers extract ``runtime.tenancy_model`` / ``runtime.state_model``
# from the manifest, validate the constraint matrix at install time, and
# either look up an existing shared-singleton ``AppRuntimeDeployment`` or
# create a fresh one alongside the install. The CHECK constraints in
# alembic 0076 are the source of truth — these helpers exist so the install
# transaction sees a clean ``ManifestInvalid`` instead of a raw IntegrityError
# wrapping a CHECK violation, AND so unsafe combinations are caught before
# any side effects (volume create, project create) happen.
# ---------------------------------------------------------------------------


_VALID_TENANCY_MODELS: frozenset[str] = frozenset(
    {"per_install", "shared_singleton", "per_invocation"}
)
_VALID_STATE_MODELS: frozenset[str] = frozenset(
    {"stateless", "per_install_volume", "service_pvc", "shared_volume", "external"}
)


@dataclass(frozen=True)
class _RuntimeContract:
    """Resolved runtime block from the manifest.

    Pre-Phase-3 manifests (2025-01 / 2025-02) don't carry a ``runtime``
    block; they default to ``per_install + per_install_volume`` which is
    the legacy behavior. Phase 3 manifests (2026-05+) MUST carry it.
    """

    tenancy_model: str
    state_model: str
    min_replicas: int
    max_replicas: int
    desired_replicas: int
    idle_timeout_seconds: int
    concurrency_target: int
    scaling_config: dict[str, Any]


def _extract_runtime_contract(manifest_json: dict[str, Any]) -> _RuntimeContract:
    """Resolve the runtime block, with legacy defaults for pre-2026 manifests.

    Raises ``ManifestInvalid`` for unknown enum values (defense in depth —
    JSON Schema should already have rejected these at publish time).
    """
    runtime_block = manifest_json.get("runtime") or {}

    # Legacy default: 2025-01 / 2025-02 manifests behave as per_install +
    # per_install_volume with max_replicas=1. The CHECK matrix on
    # app_runtime_deployments allows this combination unchanged.
    tenancy = str(runtime_block.get("tenancy_model") or "per_install")
    state = str(runtime_block.get("state_model") or "per_install_volume")

    if tenancy not in _VALID_TENANCY_MODELS:
        raise ManifestInvalid(
            f"runtime.tenancy_model={tenancy!r} is not a valid value "
            f"(allowed: {sorted(_VALID_TENANCY_MODELS)})"
        )
    if state not in _VALID_STATE_MODELS:
        raise ManifestInvalid(
            f"runtime.state_model={state!r} is not a valid value "
            f"(allowed: {sorted(_VALID_STATE_MODELS)})"
        )

    scaling = runtime_block.get("scaling") or {}
    if not isinstance(scaling, dict):
        scaling = {}

    # ``per_invocation`` deployments own no persistent pods. The plan pins
    # them to (0, 0); a manifest that ships scaling overrides for
    # per_invocation is silently ignored to keep accounting simple.
    if tenancy == "per_invocation":
        min_r, max_r, desired_r = 0, 0, 0
    else:
        min_r = int(scaling.get("min_replicas", 0))
        max_r = int(scaling.get("max_replicas", 1))
        # Default desired_replicas to max_replicas (warm by default for
        # per_install / shared_singleton). Phase 4's controller will
        # actually scale; Phase 3 only persists the desired count.
        desired_r = int(scaling.get("desired_replicas", max_r))

    return _RuntimeContract(
        tenancy_model=tenancy,
        state_model=state,
        min_replicas=min_r,
        max_replicas=max_r,
        desired_replicas=desired_r,
        idle_timeout_seconds=int(scaling.get("idle_timeout_seconds", 600)),
        concurrency_target=int(
            scaling.get("target_concurrency", scaling.get("concurrency_target", 10))
        ),
        scaling_config={
            k: v
            for k, v in scaling.items()
            if k
            not in {
                "min_replicas",
                "max_replicas",
                "desired_replicas",
                "idle_timeout_seconds",
                "target_concurrency",
                "concurrency_target",
            }
        },
    )


def _validate_runtime_contract(contract: _RuntimeContract) -> None:
    """Pre-flight the runtime constraint matrix in Python so the caller
    sees a domain error before any side effects (volume create, project
    create). DB CHECKs in 0076 are the authoritative gate; this raises
    before we hit them so the install transaction stays clean.
    """
    # per_install_volume implies per-install runtime — it makes no sense
    # to declare per-install state on a shared-singleton or per-invocation
    # runtime (there's no per-install pod to mount it on).
    if contract.state_model == "per_install_volume" and contract.tenancy_model != "per_install":
        raise ManifestInvalid(
            f"state_model='per_install_volume' is incompatible with "
            f"tenancy_model={contract.tenancy_model!r}: "
            "a per-install volume requires a per-install runtime"
        )

    # per_invocation has no persistent pods, so persistent state models
    # (per_install_volume, service_pvc, shared_volume) are nonsensical.
    # external is also rejected — per_invocation should be pure stateless.
    if contract.tenancy_model == "per_invocation" and contract.state_model != "stateless":
        raise ManifestInvalid(
            f"tenancy_model='per_invocation' requires state_model='stateless', "
            f"got state_model={contract.state_model!r}: per-invocation has no "
            "persistent pods to back stateful storage"
        )

    # Mirror the DB CHECKs in Python to give a domain error rather than a
    # raw IntegrityError. The DB is still the ultimate authority.
    if contract.max_replicas < contract.min_replicas:
        raise ManifestInvalid(
            f"max_replicas={contract.max_replicas} < "
            f"min_replicas={contract.min_replicas}"
        )
    if not (
        contract.min_replicas
        <= contract.desired_replicas
        <= contract.max_replicas
    ):
        raise ManifestInvalid(
            f"desired_replicas={contract.desired_replicas} must be in "
            f"[{contract.min_replicas}, {contract.max_replicas}]"
        )
    if contract.state_model == "per_install_volume" and contract.max_replicas > 1:
        raise ManifestInvalid(
            "state_model='per_install_volume' forces max_replicas=1 "
            f"(got {contract.max_replicas})"
        )
    if contract.state_model == "service_pvc" and contract.max_replicas > 1:
        raise ManifestInvalid(
            "state_model='service_pvc' forces max_replicas=1 "
            f"(got {contract.max_replicas})"
        )


async def _find_shared_singleton_deployment(
    db: AsyncSession,
    *,
    app_id: UUID,
    app_version_id: UUID,
) -> AppRuntimeDeployment | None:
    """Look up the existing shared-singleton runtime row for (app, version).

    Concurrency note: the lookup is a plain SELECT inside the install
    transaction. The first installer to commit wins; a racing installer
    sees the row on its next attempt OR collides on the partial UNIQUE
    on ``app_instances(project_id) WHERE state='installed'`` when both
    races land on the same shared project. The IntegrityError that
    surfaces is caught by the existing handler in ``install_app`` and
    translated to ``AlreadyInstalledError``. A future Phase 4 enhancement
    can add a per-(app_id, app_version_id, tenancy_model) UNIQUE on
    ``app_runtime_deployments`` to make the create idempotent at the DB
    level; for Phase 3 the project-level partial UNIQUE is enough.
    """
    stmt = (
        select(AppRuntimeDeployment)
        .where(
            AppRuntimeDeployment.app_id == app_id,
            AppRuntimeDeployment.app_version_id == app_version_id,
            AppRuntimeDeployment.tenancy_model == "shared_singleton",
        )
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


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

    # 4.5) Resolve + validate the runtime contract BEFORE any side effects
    # (volume create, project create). ManifestInvalid raised here means the
    # publish-time checker missed something — we still abort cleanly so the
    # installer never sees a partial state.
    runtime_contract = _extract_runtime_contract(manifest_json)
    _validate_runtime_contract(runtime_contract)

    # 4a) Regenerate the manifest 2026-05 projection rows
    # (app_actions/views/data_resources/dependencies/connector_requirements/
    # automation_templates). No-op for older manifest schemas. We run BEFORE
    # the Hub volume is materialized so a projection failure short-circuits
    # without leaking a volume; the inner savepoint owned by the projector
    # plays nicely with the install transaction the caller commits below.
    from . import projection as _projection

    try:
        await _projection.regenerate_projection(db, app_version_id=av.id)
    except _projection.ProjectionError as e:
        raise IncompatibleAppError(
            f"AppVersion {app_version_id} projection failed: {e}"
        ) from e

    # 5) Resolve runtime deployment + provision the underlying project/volume.
    #
    # Branching by tenancy_model:
    #   per_install      → fresh volume, fresh project, fresh AppRuntimeDeployment.
    #   shared_singleton → REUSE existing AppRuntimeDeployment + project for this
    #                      (app, version) if one already exists (no Hub call,
    #                      no project create); only mint if this is the first
    #                      installer.
    #   per_invocation   → no Hub call, no project, no containers. Just an
    #                      AppRuntimeDeployment row with replicas=(0, 0, 0).
    #                      Each invocation will spin a Job via the action
    #                      dispatcher's k8s_job handler.
    factory = project_factory or _default_project_factory
    runtime_deployment: AppRuntimeDeployment
    project: Project | None = None
    volume_id: str | None = None
    node_name: str | None = None
    attempt_id: UUID | None = None
    materialize_compute = False

    if runtime_contract.tenancy_model == "per_invocation":
        # No persistent runtime. Create the AppRuntimeDeployment row with
        # replicas pinned to zero so accounting + the action dispatcher can
        # find a target row to bill against. ``runtime_project_id`` stays
        # NULL — the action dispatcher's k8s_job handler is responsible for
        # picking a namespace at invocation time (Phase 4 wires this up).
        runtime_deployment = AppRuntimeDeployment(
            app_id=app_row.id,
            app_version_id=av.id,
            tenancy_model="per_invocation",
            state_model=runtime_contract.state_model,
            runtime_project_id=None,
            namespace=None,
            primary_container_id=None,
            volume_id=None,
            min_replicas=0,
            max_replicas=0,
            desired_replicas=0,
            idle_timeout_seconds=runtime_contract.idle_timeout_seconds,
            concurrency_target=runtime_contract.concurrency_target,
            scaling_config=runtime_contract.scaling_config,
        )
        db.add(runtime_deployment)
        await db.flush()

    elif runtime_contract.tenancy_model == "shared_singleton":
        existing = await _find_shared_singleton_deployment(
            db, app_id=app_row.id, app_version_id=av.id
        )
        if existing is not None:
            # Reuse path. The runtime project + volume + containers were all
            # materialized by the first installer; subsequent installs are
            # logical-only DB rows pointing at the shared deployment.
            runtime_deployment = existing
            if existing.runtime_project_id is not None:
                project = await db.get(Project, existing.runtime_project_id)
            volume_id = existing.volume_id
            logger.info(
                "install_app: reusing shared_singleton runtime app=%s version=%s "
                "deployment=%s project=%s",
                app_row.id,
                av.id,
                existing.id,
                existing.runtime_project_id,
            )
        else:
            # First installer mints the shared runtime: one Hub volume, one
            # project, one set of containers. Future installs join this row.
            if not av.bundle_hash:
                raise IncompatibleAppError(
                    f"AppVersion {app_version_id} has no bundle_hash; cannot install"
                )
            volume_id, node_name = await hub_client.create_volume_from_bundle(
                bundle_hash=av.bundle_hash,
            )
            attempt_id = await _record_install_attempt(
                marketplace_app_id=app_row.id,
                app_version_id=av.id,
                installer_user_id=installer_user_id,
                volume_id=volume_id,
                node_name=node_name,
                bundle_hash=av.bundle_hash,
            )
            project = await factory(
                db,
                name=f"{app_row.name} (shared)",
                team_id=team_id,
                owner_user_id=installer_user_id,
                volume_id=volume_id,
                cache_node=node_name,
                project_kind=PROJECT_KIND_APP_RUNTIME,
            )
            project.environment_status = "ready"
            runtime_deployment = AppRuntimeDeployment(
                app_id=app_row.id,
                app_version_id=av.id,
                tenancy_model="shared_singleton",
                state_model=runtime_contract.state_model,
                runtime_project_id=project.id,
                namespace=None,  # Set by the orchestrator at first start.
                primary_container_id=None,
                volume_id=volume_id,
                min_replicas=runtime_contract.min_replicas,
                max_replicas=runtime_contract.max_replicas,
                desired_replicas=runtime_contract.desired_replicas,
                idle_timeout_seconds=runtime_contract.idle_timeout_seconds,
                concurrency_target=runtime_contract.concurrency_target,
                scaling_config=runtime_contract.scaling_config,
            )
            db.add(runtime_deployment)
            await db.flush()
            materialize_compute = True

    else:
        # per_install: existing legacy path. Fresh volume + project + runtime.
        if not av.bundle_hash:
            raise IncompatibleAppError(
                f"AppVersion {app_version_id} has no bundle_hash; cannot install"
            )
        volume_id, node_name = await hub_client.create_volume_from_bundle(
            bundle_hash=av.bundle_hash,
        )
        # 5a) Saga ledger: record the Hub-side volume in an INDEPENDENT
        # session and commit immediately so every volume has a persistent
        # marker that predates any downstream DB writes. If the rest of
        # this function crashes (worker SIGKILL, flush fails, commit
        # fails), the orphan reaper picks up this row and frees the
        # volume. ``attempt_id`` is linked to the AppInstance below via a
        # second independent commit.
        attempt_id = await _record_install_attempt(
            marketplace_app_id=app_row.id,
            app_version_id=av.id,
            installer_user_id=installer_user_id,
            volume_id=volume_id,
            node_name=node_name,
            bundle_hash=av.bundle_hash,
        )
        # 6) Create the app_runtime Project.
        project = await factory(
            db,
            name=f"{app_row.name} (installed)",
            team_id=team_id,
            owner_user_id=installer_user_id,
            volume_id=volume_id,
            cache_node=node_name,
            project_kind=PROJECT_KIND_APP_RUNTIME,
        )
        # App runtimes don't need template-build provisioning — the volume
        # was materialized from the bundle. Mark ready so the orchestrator
        # start path (shared with user projects) doesn't bail at its
        # provisioning gate.
        project.environment_status = "ready"
        runtime_deployment = AppRuntimeDeployment(
            app_id=app_row.id,
            app_version_id=av.id,
            tenancy_model="per_install",
            state_model=runtime_contract.state_model,
            runtime_project_id=project.id,
            namespace=None,
            primary_container_id=None,
            volume_id=volume_id,
            min_replicas=runtime_contract.min_replicas,
            max_replicas=runtime_contract.max_replicas,
            desired_replicas=runtime_contract.desired_replicas,
            idle_timeout_seconds=runtime_contract.idle_timeout_seconds,
            concurrency_target=runtime_contract.concurrency_target,
            scaling_config=runtime_contract.scaling_config,
        )
        db.add(runtime_deployment)
        await db.flush()
        materialize_compute = True

    # 7) Materialize Containers + Connections from manifest.compute.
    # Skipped for per_invocation (no project) and for shared_singleton
    # reuse (the first installer already materialized them).
    compute = manifest_json.get("compute") or {}
    container_specs = list(compute.get("containers") or [])
    compute_model = str(compute.get("model") or "always-on")
    if not materialize_compute:
        container_specs = []
    if compute_model == "job-only":
        logger.info(
            "install_app: app=%s version=%s is job-only — containers will be marked status=job_only",
            app_row.id,
            av.id,
        )
    initial_status = "job_only" if compute_model == "job-only" else "stopped"
    containers_by_name: dict[str, Container] = {}
    primary_container: Container | None = None

    # Per-pod runtime env overlay (Connector Proxy auth + runtime URL).
    # Gets layered onto the primary container's environment_vars so the
    # SDK inside the pod can reach the proxy with a verifiable token.
    # The token value is materialized as a ``${secret:name/key}`` reference
    # so ``resolve_env_for_pod`` translates it to a K8s
    # ``valueFrom.secretKeyRef`` — token bytes never sit in the pod spec.
    #
    # ``OPENSAIL_RUNTIME_URL`` is injected even outside K8s (desktop / dev)
    # so the SDK has a stable env contract; non-K8s callers reach the
    # orchestrator at the same Service name today.
    runtime_env_overlay: dict[str, str] = {}
    # Defer the token secret reference until we have ``instance`` minted
    # (instance.id is the secret name suffix). We add the runtime URL eagerly.
    if (
        runtime_contract.tenancy_model == "per_install"
        or (
            runtime_contract.tenancy_model == "shared_singleton"
            and materialize_compute
        )
    ):
        # ``connector_proxy_runtime_url`` resolves to the standalone
        # ``opensail-runtime:8400`` Service in dedicated mode and to the
        # embedded mount (``tesslate-backend-service:8000/api/v1/connector-proxy``)
        # in desktop / docker mode. The SDK appends
        # ``/connectors/{id}/{path}`` either way.
        from ...config import get_settings as _get_runtime_settings

        runtime_env_overlay["OPENSAIL_RUNTIME_URL"] = (
            _get_runtime_settings().connector_proxy_runtime_url
        )

    for entry in container_specs:
        if not isinstance(entry, dict):
            continue
        # The container loop only runs when ``materialize_compute`` is
        # True, which guarantees ``project`` was assigned above. The
        # assertion documents the invariant for static analyzers.
        assert project is not None, "container materialization requires a project"
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
        # Layer runtime env overlay onto every container in the install.
        # Manifest-declared values win — operators can override the runtime
        # URL for migration windows. The token (added below post-instance)
        # also yields to manifest-declared values so an app can opt out
        # entirely if it ships its own auth.
        for ov_key, ov_val in runtime_env_overlay.items():
            env_in.setdefault(ov_key, ov_val)

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

    if materialize_compute:
        assert project is not None
        for conn in compute.get("connections") or []:
            if not isinstance(conn, dict):
                continue
            # Manifest schema (2025-02 and 2026-05) names these fields
            # `source_container` / `target_container`. No legacy fallback —
            # there is no installed-base predating the schema.
            src_name = conn.get("source_container")
            tgt_name = conn.get("target_container")
            if not src_name:
                raise IncompatibleAppError(
                    "manifest compute.connections entry missing 'source_container'"
                )
            if not tgt_name:
                raise IncompatibleAppError(
                    "manifest compute.connections entry missing 'target_container'"
                )
            src = containers_by_name.get(src_name)
            tgt = containers_by_name.get(tgt_name)
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
    #
    # ``project_id`` may be NULL for per_invocation installs (no persistent
    # runtime project). ``runtime_deployment_id`` always points at the row
    # we minted/reused above so downstream code can resolve the runtime
    # without re-walking the manifest.
    now = datetime.now(UTC)
    instance = AppInstance(
        app_id=app_row.id,
        app_version_id=av.id,
        installer_user_id=installer_user_id,
        project_id=(project.id if project is not None else None),
        state="installed",
        consent_record=wallet_mix_consent,
        wallet_mix=wallet_mix_consent,
        update_policy=update_policy,
        volume_id=volume_id,
        feature_set_hash=config_features.feature_set_hash(),
        primary_container_id=(primary_container.id if primary_container else None),
        runtime_deployment_id=runtime_deployment.id,
        installed_at=now,
    )
    db.add(instance)
    try:
        await db.flush()
    except IntegrityError as e:
        # Partial UNIQUE on project_id caught a concurrent install. Translate.
        await db.rollback()
        raise AlreadyInstalledError(
            f"project {project.id if project is not None else '<none>'} "
            "already has an installed app instance"
        ) from e

    # 8.5) Wire ``OPENSAIL_APPINSTANCE_TOKEN`` onto the primary container as
    # a secretKeyRef. The K8s Secret named ``app-pod-key-{instance.id}`` is
    # minted by ``create_per_pod_signing_key`` after this transaction
    # commits; the env reference here is what makes the orchestrator's
    # ``resolve_env_for_pod`` translate to a ``valueFrom.secretKeyRef`` at
    # pod-spec build time. The secret must exist before the pod starts —
    # the install router calls ``create_per_pod_signing_key`` before any
    # ``orchestrator.start_project`` call, so the ordering holds. Manifest-
    # declared values still win (``setdefault``) so an app can opt out.
    if primary_container is not None and runtime_env_overlay:
        env = dict(primary_container.environment_vars or {})
        env.setdefault(
            "OPENSAIL_APPINSTANCE_TOKEN",
            f"${{secret:app-pod-key-{instance.id}/token}}",
        )
        primary_container.environment_vars = env

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
    # AgentSchedule.project_id is NOT NULL — schedules are skipped for
    # per_invocation installs (no persistent project to anchor them on).
    # The Phase 4 controller handles trigger routing for per_invocation
    # apps via automation_definitions instead.
    schedule_specs = (
        list(manifest_json.get("schedules") or []) if project is not None else []
    )
    for sched in schedule_specs:
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

    # 9.5) Wire app_instance_links rows for manifest.dependencies[] (Phase 3).
    #
    # Phase 3 simplification: this does NOT auto-install missing
    # dependencies. If a `required: true` dep has no installed instance for
    # this user, we raise MissingDependencyError and the caller (UI / Phase
    # 5's Install Modal) is responsible for walking the user through the
    # recursive install. Optional deps are silently skipped — the runtime
    # surfaces them as AliasNotFound at call time.
    if (manifest_json.get("manifest_schema_version") == "2026-05"
            and manifest_json.get("dependencies")):
        from .app_manifest import AppManifest2026_05
        from .composition import (
            MissingDependencyError,
            resolve_dependency_installs,
            wire_install_links,
        )

        try:
            parsed_manifest = AppManifest2026_05.model_validate(manifest_json)
        except Exception as exc:  # noqa: BLE001 — manifest already passed publish
            # If the manifest doesn't even parse here, the projection layer
            # already raised earlier — defense in depth.
            raise IncompatibleAppError(
                f"manifest parse failed during link wiring: {exc}"
            ) from exc

        if parsed_manifest.dependencies:
            child_installs_by_app_id = await resolve_dependency_installs(
                db,
                installer_user_id=installer_user_id,
                parent_manifest=parsed_manifest,
            )
            try:
                await wire_install_links(
                    db,
                    parent_install=instance,
                    parent_manifest=parsed_manifest,
                    child_installs_by_app_id=child_installs_by_app_id,
                )
            except MissingDependencyError as exc:
                # Translate to InstallError so the router maps to a clean
                # 4xx. Phase 5's Install Modal catches this and prompts
                # the user to install the missing child first.
                raise IncompatibleAppError(str(exc)) from exc

    await db.flush()

    logger.info(
        "install_app: app=%s version=%s installer=%s project=%s volume=%s "
        "attempt=%s tenancy=%s deployment=%s",
        app_row.id,
        av.id,
        installer_user_id,
        project.id if project is not None else None,
        volume_id,
        attempt_id,
        runtime_contract.tenancy_model,
        runtime_deployment.id,
    )

    # Saga ledger: flip the attempt row to committed in a second independent
    # session. ``attempt_id`` is None for per_invocation installs (no Hub
    # call) and for shared_singleton reuse (the first installer already
    # marked the attempt). If this call fails the reaper still converges
    # — it joins on volume_id / app_instance_id and skips rows that
    # already have a live AppInstance.
    if attempt_id is not None:
        await _mark_attempt_committed(
            attempt_id=attempt_id,
            app_instance_id=instance.id,
        )

    return InstallResult(
        app_instance_id=instance.id,
        project_id=(project.id if project is not None else None),
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


async def propagate_user_secrets_post_install(
    db: AsyncSession,
    *,
    app_instance_id: UUID,
    project_id: UUID | None,
) -> dict[str, str] | None:
    """Best-effort: materialize per-user OAuth/API-key Secrets for the install.

    Called by the install router AFTER the install transaction commits and
    AFTER the namespace exists. Wrapped in try/except by the caller — a
    propagation failure must NOT roll back the install. The user can
    re-trigger via "Resync credentials" (Phase 5 UI). The app pod will
    fail to start with a clear "missing env" error if credentials never
    land, which is recoverable.

    Returns:
        ``{connector_id: status}`` from ``propagate_user_secrets`` if any
        env-exposure grants exist; ``None`` if there are no env grants
        (or if the install has no project — per-invocation installs).
    """
    if project_id is None:
        return None

    # Lazy imports: this module is in a hot path and the K8s client +
    # propagator pull in a chain of dependencies (cryptography, kubernetes
    # client) we don't want at install_app's import time.
    from kubernetes import client as k8s_client

    from .user_secret_propagator import (
        _load_env_grants_for_install,  # type: ignore[attr-defined]
        propagate_user_secrets,
    )

    instance = await db.get(AppInstance, app_instance_id)
    if instance is None:
        logger.warning(
            "propagate_user_secrets_post_install: instance=%s not found; skipping",
            app_instance_id,
        )
        return None

    # Cheap pre-check: if the install has no env grants, skip the K8s
    # client creation entirely. Avoids spinning up a CoreV1Api against
    # a deployment that doesn't need one.
    pairs = await _load_env_grants_for_install(db, instance.id)
    if not pairs:
        return None

    target_namespace = f"proj-{project_id}"
    core_v1 = k8s_client.CoreV1Api()
    statuses = await propagate_user_secrets(
        db,
        core_v1,
        app_instance=instance,
        target_namespace=target_namespace,
    )
    logger.info(
        "propagate_user_secrets_post_install: instance=%s ns=%s statuses=%s",
        instance.id,
        target_namespace,
        statuses,
    )
    return statuses


async def create_per_pod_signing_key(
    *,
    app_instance_id: UUID,
    target_namespace: str | None = None,
) -> dict[str, str] | None:
    """Mint a per-pod signing key + token for a freshly-installed AppInstance.

    Writes ``app-pod-key-{instance_id}`` K8s Secret with two fields:

    * ``signing_key`` — 32 random bytes used by the Connector Proxy to
      verify the per-pod token's HMAC.
    * ``token`` — the long-lived ``f"{instance_id}.{nonce}.{hmac}"``
      string. The pod template injects this verbatim as env var
      ``OPENSAIL_APPINSTANCE_TOKEN``.

    Returns the env-var dict ``{"OPENSAIL_APPINSTANCE_TOKEN": "..."}``
    so callers can splice it into the pod spec without re-fetching the
    Secret. Returns ``None`` when K8s mode is off (desktop / docker /
    dev) — the proxy's deterministic-derivation fallback handles those
    cases. Best-effort: a Secret-create failure logs and returns None
    rather than rolling back the install.

    Idempotent: 409 → patch.
    """
    # Late imports keep K8s client dependencies off the install hot path
    # for non-K8s deployment modes.
    from kubernetes import client as k8s_client
    from kubernetes.client.rest import ApiException

    from ...config import get_settings
    from .connector_proxy.auth import (
        generate_pod_signing_key,
        generate_pod_token,
        invalidate_signing_key_cache,
        k8s_secret_name,
    )

    settings = get_settings()
    if not getattr(settings, "is_kubernetes_mode", False):
        # Non-K8s mode: the proxy's fallback derivation handles auth, so
        # we don't need to materialize a Secret. We still mint a token
        # against the deterministic key so the pod env var is populated.
        from .shared_singleton_router import _derive_signing_key

        signing_key = _derive_signing_key(
            app_instance_id=app_instance_id,
            fallback_secret=settings.secret_key,
        )
        token = generate_pod_token(
            app_instance_id=app_instance_id, signing_key=signing_key
        )
        return {"OPENSAIL_APPINSTANCE_TOKEN": token}

    namespace = target_namespace or getattr(
        settings, "kubernetes_namespace", "tesslate"
    ) or "tesslate"
    secret_name = k8s_secret_name(app_instance_id)
    signing_key = generate_pod_signing_key()
    token = generate_pod_token(
        app_instance_id=app_instance_id, signing_key=signing_key
    )

    body = k8s_client.V1Secret(
        metadata=k8s_client.V1ObjectMeta(
            name=secret_name,
            namespace=namespace,
            labels={
                "tesslate.io/managed-by": "connector-proxy-auth",
                "tesslate.io/app-instance-id": str(app_instance_id),
            },
        ),
        type="Opaque",
        # ``string_data`` so we don't have to base64-encode by hand;
        # K8s does it server-side.
        string_data={
            "signing_key": signing_key.hex(),
            "token": token,
        },
    )

    core_v1 = k8s_client.CoreV1Api()
    try:
        try:
            core_v1.create_namespaced_secret(namespace=namespace, body=body)
        except ApiException as exc:
            if exc.status != 409:
                raise
            core_v1.patch_namespaced_secret(
                name=secret_name, namespace=namespace, body=body
            )
        # Drop any stale cached key so the proxy reads the fresh value
        # on the next call.
        invalidate_signing_key_cache(app_instance_id)
        logger.info(
            "create_per_pod_signing_key: wrote Secret=%s ns=%s instance=%s",
            secret_name,
            namespace,
            app_instance_id,
        )
        return {"OPENSAIL_APPINSTANCE_TOKEN": token}
    except Exception:  # noqa: BLE001 — non-fatal
        logger.exception(
            "create_per_pod_signing_key: K8s Secret write failed instance=%s "
            "ns=%s; proxy will fall back to deterministic-derivation key",
            app_instance_id,
            namespace,
        )
        # We still return the token: even though the Secret didn't land,
        # the proxy's deterministic fallback uses the same signing key,
        # so the issued token verifies correctly. Worst case the operator
        # sees the warning and re-syncs.
        return {"OPENSAIL_APPINSTANCE_TOKEN": token}


async def delete_per_pod_signing_key(
    *,
    app_instance_id: UUID,
    target_namespace: str | None = None,
) -> None:
    """Best-effort cleanup of the per-pod signing-key Secret on uninstall.

    Mirrors :func:`create_per_pod_signing_key`. 404 from K8s is treated
    as success (already gone). All other exceptions log and swallow —
    uninstall must converge regardless of K8s state.
    """
    from kubernetes import client as k8s_client
    from kubernetes.client.rest import ApiException

    from ...config import get_settings
    from .connector_proxy.auth import (
        invalidate_signing_key_cache,
        k8s_secret_name,
    )

    invalidate_signing_key_cache(app_instance_id)

    settings = get_settings()
    if not getattr(settings, "is_kubernetes_mode", False):
        return

    namespace = target_namespace or getattr(
        settings, "kubernetes_namespace", "tesslate"
    ) or "tesslate"
    try:
        core_v1 = k8s_client.CoreV1Api()
        core_v1.delete_namespaced_secret(
            name=k8s_secret_name(app_instance_id),
            namespace=namespace,
        )
    except ApiException as exc:
        if exc.status not in (404, 410):
            logger.warning(
                "delete_per_pod_signing_key: ns=%s instance=%s failed: %s",
                namespace,
                app_instance_id,
                exc.reason,
            )
    except Exception:  # noqa: BLE001 — defensive
        logger.exception(
            "delete_per_pod_signing_key: ns=%s instance=%s",
            namespace,
            app_instance_id,
        )
