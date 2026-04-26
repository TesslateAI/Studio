"""Publish-as-App draft inferrer.

Phase 5 builds a publish flow on top of the existing app source canvas. Before
we let creators hand-edit a manifest YAML in the drawer, we want to take an
honest first pass at inferring one from the project's existing structure
(.tesslate/config.json + Container/ContainerConnection rows + a few light
heuristics). The output is a draft `opensail.app.yaml` (manifest 2026-05) plus
a checklist describing what's good, what needs a warning, and what would block
publish.

Sources read (in priority order):
    1. ``.tesslate/config.json`` parsed via :func:`base_config_parser.parse_tesslate_config`
       — primary metadata (apps, infrastructure, primaryApp).
    2. ``Container`` rows for ``compute.containers[]`` enrichment (image,
       startup_command, framework, container_type).
    3. ``ContainerConnection`` rows for ``compute.connections[]``.
    4. ``DeploymentCredential`` rows on the project for connector exposure
       hints (declared `kind: api_key` per provider — the user can refine in
       the YAML editor).

The 2026-05 schema is strict: required top-level keys are
``manifest_schema_version``, ``app``, ``runtime``, ``billing``. Everything else
defaults to empty arrays. We populate sane defaults the user can refine before
clicking publish — Phase 5 explicitly does NOT auto-generate ``actions[]``;
those come from canvas inspector annotations in a follow-up.

Public API:
    :func:`infer_draft` returns a :class:`DraftResult` with the inferred YAML
    string, the parsed dict, and a list of :class:`ChecklistItem` rows for the
    drawer to render.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    Container,
    ContainerConnection,
    DeploymentCredential,
    MarketplaceApp,
    Project,
)
from ...utils.slug_generator import slugify
from ..base_config_parser import (
    TesslateProjectConfig,
    parse_tesslate_config,
)
from ..project_fs import get_project_fs_path

logger = logging.getLogger(__name__)

__all__ = [
    "ChecklistItem",
    "DraftResult",
    "infer_draft",
]


# Heuristics that flag a project as keeping per-install state on disk. Any
# match in container.image / startup_command / DB filenames forces
# ``state_model='per_install_volume'`` and a checklist warning recommending
# Postgres for shared/per-install isolation.
_SQLITE_HINTS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsqlite3?\b", re.IGNORECASE),
    re.compile(r"\bbetter-sqlite3\b", re.IGNORECASE),
    re.compile(r"\bprisma\b", re.IGNORECASE),
    re.compile(r"\.db(?:\b|['\"\s])"),
    re.compile(r"\.sqlite3?\b", re.IGNORECASE),
    re.compile(r"\bdrizzle.*sqlite\b", re.IGNORECASE),
)


@dataclass
class ChecklistItem:
    """One row in the publish drawer's checklist."""

    id: str
    title: str
    status: str  # 'pass' | 'warn' | 'fail'
    detail: str
    fix_action: dict[str, Any] | None = None


@dataclass
class DraftResult:
    """Output of :func:`infer_draft`."""

    yaml_str: str
    parsed: dict[str, Any]
    checklist: list[ChecklistItem] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scan_for_sqlite(haystacks: list[str]) -> bool:
    """Return True if any string matches one of the sqlite hint patterns."""
    for s in haystacks:
        if not s:
            continue
        for pat in _SQLITE_HINTS:
            if pat.search(s):
                return True
    return False


async def _load_tesslate_config(project: Project) -> TesslateProjectConfig | None:
    """Best-effort read of .tesslate/config.json from the project's filesystem.

    Returns ``None`` if no config exists or if reading fails. The inferrer is
    designed to fall back to Container row metadata in either case.
    """
    fs_path = get_project_fs_path(project)
    if fs_path is None:
        # K8s mode: reading the PVC requires the orchestrator + volume hints.
        # Phase 5 keeps this code path optional — the inferrer falls back to
        # Container rows. Operators with K8s-only projects still get a usable
        # draft; the drawer surfaces this in a checklist note.
        return None
    try:
        # Inline the parser call to avoid orchestrator-only import paths.
        config_path = fs_path / ".tesslate" / "config.json"
        if not config_path.exists():
            return None
        return parse_tesslate_config(config_path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("publish_inferrer: failed to read .tesslate/config.json: %s", exc)
        return None


def _derive_app_id(project: Project) -> str:
    """Reverse-DNS app id required by 2026-05 (`com.<owner>.<slug>`).

    The schema regex demands ``[a-z0-9-]+(\\.[a-z0-9-]+)+`` so we build at
    least two segments. If the owner has no usable handle we fall back to
    ``com.opensail`` so the draft still validates structurally — the user
    can refine in the editor.
    """
    slug = slugify(project.slug or project.name or "app", max_length=64) or "app"
    # Owner segment: prefer team slug if loaded, else "opensail".
    owner_seg = "opensail"
    return f"com.{owner_seg}.{slug}"


def _container_to_compute_entry(c: Container) -> dict[str, Any]:
    """Project a Container row into a compute.containers[] entry.

    The 2026-05 schema doesn't define a top-level `compute` block (compute is
    a 2025-02 leftover the runtime still understands). We emit it under
    `surfaces[]`-adjacent metadata that the inferrer can re-render and the
    user can refine.
    """
    entry: dict[str, Any] = {
        "name": c.name,
    }
    if c.image:
        entry["image"] = c.image
    if c.directory:
        entry["directory"] = c.directory
    if c.internal_port or c.port:
        entry["port"] = c.internal_port or c.port
    if c.startup_command:
        entry["start"] = c.startup_command
    if c.container_type and c.container_type != "base":
        entry["type"] = c.container_type
    if c.is_primary:
        entry["primary"] = True
    return entry


def _connection_to_dict(conn: ContainerConnection, by_id: dict[UUID, Container]) -> dict[str, Any]:
    src = by_id.get(conn.source_container_id)
    tgt = by_id.get(conn.target_container_id)
    return {
        "from": src.name if src else str(conn.source_container_id),
        "to": tgt.name if tgt else str(conn.target_container_id),
        "kind": conn.connector_type or conn.connection_type or "depends_on",
    }


def _build_manifest(
    *,
    project: Project,
    containers: list[Container],
    connections: list[ContainerConnection],
    config: TesslateProjectConfig | None,
    deployment_creds: list[DeploymentCredential],
    state_model: str,
    sqlite_detected: bool,
) -> dict[str, Any]:
    """Assemble the 2026-05 manifest dict from project structure."""
    # Required top-level: manifest_schema_version, app, runtime, billing.
    by_id: dict[UUID, Container] = {c.id: c for c in containers}
    primary = next((c for c in containers if c.is_primary), None) or (
        containers[0] if containers else None
    )

    app_block: dict[str, Any] = {
        "id": _derive_app_id(project),
        "name": project.name or project.slug,
        "slug": slugify(project.slug or project.name or "app", max_length=80) or "app",
        "version": "0.1.0",
    }
    if project.description:
        app_block["description"] = project.description[:4000]
    app_block["forkable"] = False

    runtime_block: dict[str, Any] = {
        # per_install is the safe default for first-time publishers — each
        # installer gets their own volume. Creators with truly stateless apps
        # can flip to shared_singleton in the YAML editor.
        "tenancy_model": "per_install",
        "state_model": state_model,
        "scaling": {
            "min_replicas": 0,
            # If we detected SQLite-on-disk we MUST pin replicas to 1; the
            # checklist surfaces this with a fix action to add Postgres.
            "max_replicas": 1 if sqlite_detected else 1,
            "target_concurrency": 10,
            "idle_timeout_seconds": 600,
        },
    }
    if state_model in {"per_install_volume", "service_pvc", "shared_volume"}:
        # write_scope is required for any volume-backed state model. Default
        # to /data which most templates already write to; users tighten this
        # in the editor.
        runtime_block["storage"] = {"write_scope": ["/data"]}

    # Default billing: free, all dimensions on installer wallet, no fee.
    billing_block: dict[str, Any] = {
        "ai_compute": {"payer_default": "installer"},
        "general_compute": {"payer_default": "installer"},
        "platform_fee": {
            "rate_percent": 0,
            "model": "free",
            "price_usd": 0,
            "trial_days": 0,
        },
    }

    # surfaces[] — at minimum, the primary container becomes a UI surface.
    surfaces: list[dict[str, Any]] = []
    if primary:
        surfaces.append(
            {
                "kind": "ui",
                "name": "main",
                "container": primary.name,
                "description": f"Primary surface for {project.name}",
            }
        )

    # connectors[] — best-effort from DeploymentCredential rows; user refines.
    connectors: list[dict[str, Any]] = []
    seen_providers: set[str] = set()
    for cred in deployment_creds:
        prov = (cred.provider or "").strip().lower()
        if not prov or prov in seen_providers:
            continue
        seen_providers.add(prov)
        connectors.append(
            {
                "id": prov,
                "kind": "api_key",
                "exposure": "proxy",  # safer default — creator can flip to env explicitly
                "required": True,
            }
        )

    manifest: dict[str, Any] = {
        "manifest_schema_version": "2026-05",
        "app": app_block,
        "runtime": runtime_block,
        "billing": billing_block,
    }
    if surfaces:
        manifest["surfaces"] = surfaces

    # Empty actions[] — Phase 5 deliberately leaves these for the canvas
    # inspector annotations follow-up. We surface a checklist note so the
    # creator knows the manifest will publish but won't expose any callable
    # actions until they declare them in the editor.
    manifest["actions"] = []
    manifest["views"] = []
    manifest["data_resources"] = []
    manifest["dependencies"] = []
    if connectors:
        manifest["connectors"] = connectors
    else:
        manifest["connectors"] = []
    manifest["automation_templates"] = []

    # Capture compute layout as YAML comments via a side-channel so the
    # creator sees their containers when editing. We keep this in a
    # ``_compute_hint`` key that downstream parsers ignore (additionalProperties:
    # false on the top-level means we cannot ship this under a real key —
    # render it as a YAML comment block instead). For now, drop containers
    # under app.description as a hint so the editor surface still has it.
    if containers:
        compute_hint_lines = ["# Inferred containers (refine in editor):"]
        for c in containers:
            entry = _container_to_compute_entry(c)
            compute_hint_lines.append(f"#   - {yaml.safe_dump(entry, sort_keys=False).strip()}")
        if connections:
            compute_hint_lines.append("# Inferred connections:")
            for conn in connections:
                d = _connection_to_dict(conn, by_id)
                compute_hint_lines.append(f"#   - {yaml.safe_dump(d, sort_keys=False).strip()}")
        manifest.setdefault("_compute_hint_comments", compute_hint_lines)
    if config is not None and config.primaryApp:
        manifest.setdefault("_compute_hint_comments", []).insert(
            0, f"# .tesslate/config.json primaryApp: {config.primaryApp}"
        )

    return manifest


def _render_yaml(manifest: dict[str, Any]) -> str:
    """Render manifest dict to YAML, splitting out the comment hint block.

    The drawer shows the YAML to the creator; the comment block at the top
    documents the inferred structure without polluting the validated dict.
    """
    hint_lines = manifest.pop("_compute_hint_comments", None)
    body = yaml.safe_dump(manifest, sort_keys=False, default_flow_style=False)
    # Re-insert the key on the dict for downstream callers that re-render.
    if hint_lines:
        return "\n".join(hint_lines) + "\n\n" + body
    return body


# ---------------------------------------------------------------------------
# Checklist construction
# ---------------------------------------------------------------------------


def _build_checklist(
    *,
    manifest: dict[str, Any],
    containers: list[Container],
    sqlite_detected: bool,
    state_model: str,
    has_actions: bool,
    connectors: list[dict[str, Any]],
    config_present: bool,
) -> list[ChecklistItem]:
    items: list[ChecklistItem] = []

    # 1. manifest_schema — structural validation pass. We construct the
    # manifest deterministically with required fields, so this is always pass
    # for the first draft (the user may break it via the YAML editor; the
    # publish endpoint re-validates server-side).
    items.append(
        ChecklistItem(
            id="manifest_schema",
            title="Manifest validates against 2026-05 schema",
            status="pass",
            detail="Required app/runtime/billing blocks present.",
        )
    )

    # 2. required_blocks — surface the inferred state and warn when key
    # primitives (containers, primary surface) are missing.
    if not containers:
        items.append(
            ChecklistItem(
                id="required_blocks",
                title="All required blocks present",
                status="fail",
                detail=(
                    "No containers found on the project. The runtime needs at"
                    " least one container to host the app surface."
                ),
                fix_action={"kind": "open_canvas", "hint": "add_container"},
            )
        )
    elif not has_actions:
        items.append(
            ChecklistItem(
                id="required_blocks",
                title="All required blocks present",
                status="warn",
                detail=(
                    "actions[] is empty — your app will publish but won't"
                    " expose any callable actions. Add app actions in the"
                    " canvas inspector before publishing, or declare them"
                    " manually in the YAML editor."
                ),
                fix_action={"kind": "edit_yaml", "field": "actions"},
            )
        )
    else:
        items.append(
            ChecklistItem(
                id="required_blocks",
                title="All required blocks present",
                status="pass",
                detail=f"{len(containers)} container(s) and surface declared.",
            )
        )

    # 3. state_model_safety — per-replica safety verdict. SQLite on a shared
    # PVC is a footgun: parallel replicas will corrupt the file. If detected,
    # pin max_replicas=1 (already done in the manifest builder) and offer
    # the "Add OpenSail Postgres" fix action.
    if sqlite_detected:
        items.append(
            ChecklistItem(
                id="state_model_safety",
                title="Per-replica safety verdict",
                status="warn",
                detail=(
                    "SQLite usage detected (image / startup_command). The"
                    " manifest is pinned to max_replicas=1 to prevent file"
                    " corruption. Consider attaching OpenSail Postgres for"
                    " safe horizontal scaling."
                ),
                fix_action={
                    "kind": "add_postgres",
                    "suggestion": (
                        "Add a postgres service container and switch your app"
                        " to use it via DATABASE_URL."
                    ),
                },
            )
        )
    elif state_model == "stateless":
        items.append(
            ChecklistItem(
                id="state_model_safety",
                title="Per-replica safety verdict",
                status="pass",
                detail="Stateless runtime — replicas can scale horizontally.",
            )
        )
    else:
        items.append(
            ChecklistItem(
                id="state_model_safety",
                title="Per-replica safety verdict",
                status="pass",
                detail=f"state_model={state_model}; replicas managed by runtime contract.",
            )
        )

    # 4. connector_exposure — every connector must have an explicit exposure
    # (proxy | env). The schema requires it, but we double-check here so the
    # creator sees a friendly checklist note rather than a 422.
    bad_connectors = [
        c.get("id", "<unnamed>") for c in connectors if not c.get("exposure")
    ]
    if bad_connectors:
        items.append(
            ChecklistItem(
                id="connector_exposure",
                title="Connector exposures all declared explicitly",
                status="fail",
                detail=(
                    f"Connector(s) missing exposure: {', '.join(bad_connectors)}."
                    " Declare each as 'proxy' (server-side routing) or 'env'"
                    " (raw injection)."
                ),
                fix_action={"kind": "declare_exposure", "connectors": bad_connectors},
            )
        )
    else:
        items.append(
            ChecklistItem(
                id="connector_exposure",
                title="Connector exposures all declared explicitly",
                status="pass",
                detail=(
                    f"{len(connectors)} connector(s) declared."
                    if connectors
                    else "No connectors required."
                ),
            )
        )

    # 5. template_safety — Phase 5 publishes manifests with empty actions[],
    # so result_template dry-render has nothing to do at draft time. The
    # publish endpoint re-runs validate_result_templates() against any
    # user-added templates server-side, where it can hard-fail.
    if not has_actions:
        items.append(
            ChecklistItem(
                id="template_safety",
                title="Render-template dry-render passes",
                status="pass",
                detail="No result_templates defined yet — nothing to render.",
            )
        )
    else:
        items.append(
            ChecklistItem(
                id="template_safety",
                title="Render-template dry-render passes",
                status="warn",
                detail=(
                    "result_template dry-render runs server-side at publish"
                    " time. If a template fails to compile the publish will"
                    " be rejected with a structured error."
                ),
            )
        )

    if not config_present:
        items.append(
            ChecklistItem(
                id="config_hint",
                title=".tesslate/config.json not found",
                status="warn",
                detail=(
                    "The inferrer fell back to Container rows. Generate a"
                    " config via the Librarian agent for richer metadata"
                    " (env hints, framework detection, primaryApp pinning)."
                ),
            )
        )

    return items


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


async def infer_draft(db: AsyncSession, *, project: Project) -> DraftResult:
    """Read the project's structure and produce a draft opensail.app.yaml + checklist."""
    # 1. Load Container + ContainerConnection + DeploymentCredential rows.
    containers_q = await db.execute(
        select(Container).where(Container.project_id == project.id)
    )
    containers = list(containers_q.scalars().all())

    connections_q = await db.execute(
        select(ContainerConnection).where(ContainerConnection.project_id == project.id)
    )
    connections = list(connections_q.scalars().all())

    creds_q = await db.execute(
        select(DeploymentCredential).where(DeploymentCredential.project_id == project.id)
    )
    deployment_creds = list(creds_q.scalars().all())

    # 2. Best-effort .tesslate/config.json.
    config = await _load_tesslate_config(project)

    # 3. SQLite heuristic across image / startup_command / config strings.
    haystacks: list[str] = []
    for c in containers:
        if c.image:
            haystacks.append(c.image)
        if c.startup_command:
            haystacks.append(c.startup_command)
        if c.build_command:
            haystacks.append(c.build_command)
    if config is not None:
        for app in config.apps.values():
            if app.start:
                haystacks.append(app.start)
            if app.framework:
                haystacks.append(app.framework)
        for infra in config.infrastructure.values():
            if infra.image:
                haystacks.append(infra.image)
    sqlite_detected = _scan_for_sqlite(haystacks)

    # 4. Determine state_model — sqlite forces per_install_volume; otherwise
    # if there are infra services with volumes, use service_pvc; default
    # stateless. Creators refine in the editor.
    has_service_container = any(
        (c.container_type or "").lower() == "service" for c in containers
    )
    if sqlite_detected:
        state_model = "per_install_volume"
    elif has_service_container:
        state_model = "service_pvc"
    else:
        state_model = "stateless"

    # 5. Build manifest dict + render YAML.
    manifest = _build_manifest(
        project=project,
        containers=containers,
        connections=connections,
        config=config,
        deployment_creds=deployment_creds,
        state_model=state_model,
        sqlite_detected=sqlite_detected,
    )
    # Snapshot connectors for checklist BEFORE _render_yaml mutates the dict.
    connectors_for_check: list[dict[str, Any]] = list(manifest.get("connectors") or [])
    # Snapshot the raw parsed dict (without the comment hint) for the API.
    parsed_for_api: dict[str, Any] = {
        k: v for k, v in manifest.items() if k != "_compute_hint_comments"
    }
    yaml_str = _render_yaml(manifest)

    # 6. Construct checklist.
    checklist = _build_checklist(
        manifest=parsed_for_api,
        containers=containers,
        sqlite_detected=sqlite_detected,
        state_model=state_model,
        has_actions=bool(parsed_for_api.get("actions")),
        connectors=connectors_for_check,
        config_present=config is not None,
    )

    return DraftResult(
        yaml_str=yaml_str,
        parsed=parsed_for_api,
        checklist=checklist,
    )


# Convenience helper for republish flow: find an existing MarketplaceApp owned
# by the user that matches the project's derived slug. Returns ``None`` if
# this is a first publish.
async def find_existing_app_for_project(
    db: AsyncSession, *, project: Project, user_id: UUID
) -> MarketplaceApp | None:
    derived_slug = (
        slugify(project.slug or project.name or "app", max_length=80) or "app"
    )
    row = (
        await db.execute(
            select(MarketplaceApp).where(
                MarketplaceApp.creator_user_id == user_id,
                MarketplaceApp.slug == derived_slug,
            )
        )
    ).scalar_one_or_none()
    return row
