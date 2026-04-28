"""App Runtime Contract — manifest 2026-05 projection service.

On every install or version upgrade, the six ``app_*`` projection tables
(``app_actions``, ``app_views``, ``app_data_resources``, ``app_dependencies``,
``app_connector_requirements``, ``app_automation_templates``) are
regenerated atomically from ``AppVersion.manifest_json``.

The manifest stays the immutable source of truth — projection rows are a
derived view, regenerated on demand. All six writes happen inside ONE
savepoint (``db.begin_nested``); if any single insert fails the savepoint
rolls back and the previous projection stays in service. The caller's
outer transaction is unaffected.

Phase 1 only projects the 2026-05 schema. Older manifests (2025-01,
2025-02) don't carry these blocks — the regenerator returns a zero-result
``ProjectionResult`` and is a no-op.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AppVersion, MarketplaceApp
from ...models_automations import (
    AppAction,
    AppAutomationTemplate,
    AppConnectorRequirement,
    AppDataResource,
    AppDependency,
    AppView,
    AutomationAction,
    AutomationDefinition,
    InvocationSubject,
)
from .app_manifest import AppManifest2026_05
from .manifest_parser import ManifestValidationError, parse as parse_manifest

__all__ = [
    "ProjectionError",
    "AppVersionNotFound",
    "ManifestInvalid",
    "DependencyAppNotFound",
    "ProjectionResult",
    "regenerate_projection",
]

logger = logging.getLogger(__name__)

# Manifest schema version this projector targets. Older manifests are skipped
# entirely (no rows written, no rows deleted) — they predate the runtime
# contract and don't carry the typed action/view/etc. blocks.
_PROJECTION_SCHEMA_VERSION = "2026-05"


class ProjectionError(Exception):
    """Base for projection-time failures. Triggers savepoint rollback."""


class AppVersionNotFound(ProjectionError):
    """No AppVersion row matches the supplied id."""


class ManifestInvalid(ProjectionError):
    """The stored manifest_json fails parser/typed validation.

    Wraps the underlying ``ManifestValidationError`` so the install caller
    can catch a single domain error type and roll back.
    """


class DependencyAppNotFound(ProjectionError):
    """A manifest dependency references an app_id with no matching
    ``MarketplaceApp`` row. Phase 1 treats this as fatal — a missing
    dependency means the install must abort, not graceful no-op."""

    def __init__(self, app_id: str) -> None:
        super().__init__(f"manifest dependency references unknown app_id={app_id!r}")
        self.app_id = app_id


@dataclass(frozen=True)
class ProjectionResult:
    """Counts of rows materialized per projection table.

    All counts are zero when the manifest schema isn't 2026-05 (the older
    versions don't carry these blocks; nothing to project)."""

    actions_count: int
    views_count: int
    data_resources_count: int
    dependencies_count: int
    connector_requirements_count: int
    automation_templates_count: int

    @classmethod
    def empty(cls) -> "ProjectionResult":
        return cls(0, 0, 0, 0, 0, 0)


async def regenerate_projection(
    db: AsyncSession,
    *,
    app_version_id: UUID,
) -> ProjectionResult:
    """Atomically regenerate all six projection tables for one AppVersion.

    Reads ``AppVersion.manifest_json``, parses via ``manifest_parser``,
    then deletes existing projection rows for this version and writes new
    ones inside a single ``db.begin_nested()`` savepoint. The outer
    transaction (owned by the install path) is unaffected; if projection
    fails, only the savepoint rolls back, and the install caller can
    decide whether to abort the whole transaction.

    Args:
        db: AsyncSession participating in the install/upgrade transaction.
        app_version_id: The AppVersion to project.

    Returns:
        ProjectionResult with counts per table. Zero across the board for
        manifests older than 2026-05 (those schemas don't have the runtime
        contract blocks — projection is a no-op, NOT a failure).

    Raises:
        AppVersionNotFound: AppVersion row missing.
        ManifestInvalid: manifest_json fails parser validation.
        DependencyAppNotFound: dependency app_id unknown to MarketplaceApp.
    """
    # 1. Load the AppVersion row.
    av = (
        await db.execute(select(AppVersion).where(AppVersion.id == app_version_id))
    ).scalar_one_or_none()
    if av is None:
        raise AppVersionNotFound(f"AppVersion {app_version_id} not found")

    # 2. Skip projection entirely for legacy schemas. Older manifests don't
    # carry actions/views/data_resources/etc. — there's nothing to project,
    # and we explicitly do NOT delete any rows (preserves any prior
    # projection if one was somehow written by a different code path).
    declared_schema = av.manifest_schema_version or (
        (av.manifest_json or {}).get("manifest_schema_version") or ""
    )
    if declared_schema != _PROJECTION_SCHEMA_VERSION:
        logger.debug(
            "regenerate_projection: skipping AppVersion=%s schema=%r (not %s)",
            app_version_id,
            declared_schema,
            _PROJECTION_SCHEMA_VERSION,
        )
        return ProjectionResult.empty()

    # 3. Parse + typed-validate the manifest. ManifestValidationError is the
    # parser's domain error; wrap it so callers catch a single ProjectionError.
    try:
        parsed = parse_manifest(av.manifest_json or {})
    except ManifestValidationError as e:
        raise ManifestInvalid(
            f"AppVersion {app_version_id} manifest_json failed validation: {e}"
        ) from e

    manifest = parsed.manifest
    if not isinstance(manifest, AppManifest2026_05):
        # Defense in depth: parser routed by manifest_schema_version, so
        # we should always get the 2026-05 typed mirror here. If we don't,
        # something is misconfigured upstream.
        raise ManifestInvalid(
            f"AppVersion {app_version_id} parsed to {type(manifest).__name__}, "
            f"expected AppManifest2026_05"
        )

    # 4. Pre-resolve dependency app_id → MarketplaceApp.id BEFORE opening
    # the savepoint. Looking up Phase 1 by manifest's STRING app_id, which
    # lands on MarketplaceApp.slug today (the only string-unique field on
    # the hub row). If a dependency is missing we want the failure to
    # happen before any DELETE, so the projection layer never partially
    # touches the table.
    dependency_resolutions: dict[str, UUID] = {}
    for dep in manifest.dependencies:
        if dep.app_id in dependency_resolutions:
            continue
        child_id = (
            await db.execute(
                select(MarketplaceApp.id).where(MarketplaceApp.slug == dep.app_id)
            )
        ).scalar_one_or_none()
        if child_id is None:
            raise DependencyAppNotFound(dep.app_id)
        dependency_resolutions[dep.app_id] = child_id

    # 5. Open the savepoint. All six writes live or die together.
    async with db.begin_nested():
        # 5a-pre. Snapshot dependents BEFORE the DELETE so we can rebind
        # them by slug after re-inserting AppAction rows. Without this:
        # ``automation_actions.app_action_id`` is FK ``ON DELETE SET NULL``,
        # so the cascade silently nulls every existing automation that
        # pointed at this app_version's actions and the dispatcher then
        # raises ``ContractInvalid`` on every subsequent run. The rebind
        # at 5b-post repoints survivors at the new same-named row, or
        # pauses the owning definition if the slug disappeared in the
        # new manifest. Same idea for ``invocation_subjects`` (billing
        # attribution; rebound when possible, NULL-tolerated otherwise).
        old_action_dependents = (
            await db.execute(
                select(AutomationAction.id, AppAction.name)
                .join(AppAction, AppAction.id == AutomationAction.app_action_id)
                .where(AppAction.app_version_id == app_version_id)
            )
        ).all()
        old_subject_dependents = (
            await db.execute(
                select(InvocationSubject.id, AppAction.name)
                .join(AppAction, AppAction.id == InvocationSubject.app_action_id)
                .where(AppAction.app_version_id == app_version_id)
            )
        ).all()

        # 5a. DELETE in reverse-FK order. ``app_data_resources`` is wiped
        # FIRST because it FKs ``app_actions``; even though the migration
        # declares ON DELETE CASCADE on that FK (so deleting actions would
        # cascade-clear data_resources), we explicit-delete to keep this
        # service portable across backends where CASCADE may be off
        # (SQLite without ``PRAGMA foreign_keys=ON``) and to keep the
        # behavior independent of the FK action choice.
        for table in (
            AppDataResource,
            AppAutomationTemplate,
            AppDependency,
            AppConnectorRequirement,
            AppView,
            AppAction,
        ):
            await db.execute(
                delete(table).where(table.app_version_id == app_version_id)
            )

        # 5b. INSERT new rows in FK-friendly order:
        #   actions → views → data_resources (FK→actions) → dependencies
        #   → connector_requirements → automation_templates.
        action_id_by_name: dict[str, UUID] = {}
        for action_spec in manifest.actions:
            row = AppAction(
                app_version_id=app_version_id,
                name=action_spec.name,
                handler=_to_jsonable(action_spec.handler),
                input_schema=action_spec.input_schema,
                output_schema=action_spec.output_schema,
                timeout_seconds=action_spec.timeout_seconds,
                idempotency=_to_jsonable(action_spec.idempotency)
                if action_spec.idempotency
                else None,
                billing=_to_jsonable(action_spec.billing) if action_spec.billing else None,
                required_connectors=list(action_spec.required_connectors),
                required_grants=[_to_jsonable(g) for g in action_spec.required_grants],
                result_template=action_spec.result_template,
                artifacts=[_to_jsonable(a) for a in action_spec.artifacts],
            )
            db.add(row)
            # Flush per-action so the autogenerated id is available BEFORE
            # we resolve data_resources[].backed_by_action — these are the
            # only intra-projection FK references we have.
            await db.flush()
            action_id_by_name[action_spec.name] = row.id

        # 5b-post. Rebind dependents snapshotted at 5a-pre. Walks the
        # ``(dependent_id, slug)`` snapshots and points each survivor at
        # the new same-named ``AppAction``. Slugs that vanished from the
        # new manifest leave the dependent's FK NULL and pause the owning
        # ``AutomationDefinition`` so the cron stops firing into a state
        # the dispatcher would only reject.
        orphaned_definition_ids: set[UUID] = set()
        for aa_id, slug in old_action_dependents:
            new_id = action_id_by_name.get(slug)
            if new_id is not None:
                await db.execute(
                    update(AutomationAction)
                    .where(AutomationAction.id == aa_id)
                    .values(app_action_id=new_id)
                )
            else:
                owning_def_id = (
                    await db.execute(
                        select(AutomationAction.automation_id).where(
                            AutomationAction.id == aa_id
                        )
                    )
                ).scalar_one_or_none()
                if owning_def_id is not None:
                    orphaned_definition_ids.add(owning_def_id)

        for def_id in orphaned_definition_ids:
            await db.execute(
                update(AutomationDefinition)
                .where(AutomationDefinition.id == def_id)
                .values(
                    is_active=False,
                    paused_reason="action_removed_in_upgrade",
                )
            )

        for is_id, slug in old_subject_dependents:
            new_id = action_id_by_name.get(slug)
            if new_id is not None:
                await db.execute(
                    update(InvocationSubject)
                    .where(InvocationSubject.id == is_id)
                    .values(app_action_id=new_id)
                )
            # Else: leave NULL — billing attribution is best-effort, and
            # losing the FK on a historical row only loses metadata, not
            # money. The unified billing path doesn't hard-require it.

        if old_action_dependents or old_subject_dependents:
            rebound_actions = sum(
                1 for _, slug in old_action_dependents if slug in action_id_by_name
            )
            rebound_subjects = sum(
                1 for _, slug in old_subject_dependents if slug in action_id_by_name
            )
            logger.info(
                "regenerate_projection: app_version=%s rebound %d/%d "
                "automation_action(s); paused %d definition(s) for missing "
                "slugs; rebound %d/%d invocation_subject(s)",
                app_version_id,
                rebound_actions,
                len(old_action_dependents),
                len(orphaned_definition_ids),
                rebound_subjects,
                len(old_subject_dependents),
            )

        for view_spec in manifest.views:
            db.add(
                AppView(
                    app_version_id=app_version_id,
                    name=view_spec.name,
                    kind=view_spec.kind,
                    entrypoint=view_spec.entrypoint,
                    input_schema=view_spec.input_schema,
                    output_schema=view_spec.output_schema,
                    cache_ttl_seconds=view_spec.cache_ttl_seconds,
                )
            )

        for resource_spec in manifest.data_resources:
            # Defense in depth — the Pydantic validator
            # (``_check_data_resource_action_refs``) already enforces this,
            # but a projection-layer recheck protects against any future
            # parser drift and makes this service correct in isolation.
            backing_action_id = action_id_by_name.get(resource_spec.backed_by_action)
            if backing_action_id is None:
                raise ManifestInvalid(
                    f"data_resource {resource_spec.name!r} references unknown "
                    f"action {resource_spec.backed_by_action!r}"
                )
            db.add(
                AppDataResource(
                    app_version_id=app_version_id,
                    name=resource_spec.name,
                    backed_by_action_id=backing_action_id,
                    schema=resource_spec.schema_,
                    cache_ttl_seconds=resource_spec.cache_ttl_seconds,
                )
            )

        for dep_spec in manifest.dependencies:
            child_id = dependency_resolutions[dep_spec.app_id]
            needs = dep_spec.needs
            db.add(
                AppDependency(
                    app_version_id=app_version_id,
                    alias=dep_spec.alias,
                    child_app_id=child_id,
                    required=dep_spec.required,
                    needs_actions=list(needs.actions) if needs else [],
                    needs_views=list(needs.views) if needs else [],
                    needs_data_resources=list(needs.data_resources) if needs else [],
                )
            )

        for connector_spec in manifest.connectors:
            # exposure ∈ {'proxy', 'env'} — both Pydantic and the DB CHECK
            # constraint enforce this; we trust them here.
            db.add(
                AppConnectorRequirement(
                    app_version_id=app_version_id,
                    connector_id=connector_spec.id,
                    kind=connector_spec.kind,
                    scopes=list(connector_spec.scopes),
                    exposure=connector_spec.exposure,
                )
            )

        for tmpl_spec in manifest.automation_templates:
            db.add(
                AppAutomationTemplate(
                    app_version_id=app_version_id,
                    name=tmpl_spec.name,
                    description=tmpl_spec.description,
                    trigger_config=_to_jsonable(tmpl_spec.trigger),
                    action_config=_to_jsonable(tmpl_spec.action),
                    delivery_config=_to_jsonable(tmpl_spec.delivery)
                    if tmpl_spec.delivery
                    else {},
                    contract_template=tmpl_spec.contract_template or {},
                    is_default_enabled=tmpl_spec.is_default_enabled,
                )
            )

        # Final flush so any constraint violations (e.g. duplicate names
        # from a malformed manifest) surface as IntegrityError INSIDE the
        # savepoint and roll the projection back atomically.
        await db.flush()

    return ProjectionResult(
        actions_count=len(manifest.actions),
        views_count=len(manifest.views),
        data_resources_count=len(manifest.data_resources),
        dependencies_count=len(manifest.dependencies),
        connector_requirements_count=len(manifest.connectors),
        automation_templates_count=len(manifest.automation_templates),
    )


def _to_jsonable(model: Any) -> dict[str, Any]:
    """Convert a Pydantic model to a JSONB-friendly dict.

    ``by_alias=True`` so aliased fields (``schema_`` → ``schema``,
    ``from_`` → ``from``) round-trip with their schema-declared keys.
    ``mode='json'`` so nested complex types are serialized to JSON-safe
    primitives. ``exclude_none=True`` keeps the JSONB payload compact and
    matches the manifest's "absent vs null" semantics."""
    return model.model_dump(by_alias=True, mode="json", exclude_none=True)
