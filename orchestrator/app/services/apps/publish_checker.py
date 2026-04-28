"""Publish-time per-replica safety checker.

Phase 5 — see plan §"Per-Replica Safety for Vibecoded Apps".

Most creators ship apps that write to local SQLite, persist sessions to
``/app/sessions/``, or hold per-process state in a global. Silently scaling
those apps to N replicas behind a load balancer corrupts data or returns
inconsistent reads. The platform refuses to do that — it pins
``runtime.scaling.max_replicas = 1`` and offers a one-click "Add OpenSail
Postgres" upgrade.

This module is the verdict engine. It runs heuristics on the project's
file tree + Container model rows and returns a typed
:class:`StateModelVerdict` the Publish Drawer renders.

Detection scope (Phase 5)
-------------------------
We deliberately stay shallow:

* Top-level project file tree — looks for ``*.db`` / ``*.sqlite`` /
  ``*.sqlite3`` files and well-known framework cache directories
  (``.next/cache``, ``node_modules/.cache``).
* ``Container.startup_command`` strings — sniffs SQLite-bound CLIs
  (``sqlite3``, ``prisma db push``, ``prisma migrate``, ``sequelize``)
  and known dev-server patterns (``next dev``, ``django runserver``).
* Manifest's ``runtime.state_model`` and ``runtime.storage.write_scope``
  vs the inferred footprint — flags contradictions ("declared
  ``stateless`` but image writes outside ``/tmp``").

Real container-image scanning (peeling layers, resolving symlinks inside
the image FS) is intentionally a follow-up — that's a separate ops
project and would block the Phase 5 checker on infra it doesn't have.

Constraint matrix (mirrors the plan's table at §1556 and the Pydantic
model_validator at ``app_manifest.py::AppManifest2026_05._check_state_model_replica_constraints``):

::

    state_model         max_replicas allowed
    ─────────────       ─────────────────────
    stateless           unbounded
    external            unbounded
    shared_volume       unbounded only if RWX-capable storage class
    per_install_volume  1 (RWO PVC)
    service_pvc         1 (single-writer)
    unknown             1 (safe default)

The verdict's ``pinned_max_replicas`` is the platform-enforced ceiling
the install-time admission controller will honour. The publish UX uses
``upgrade_offers`` to let the creator escape the ceiling cleanly.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Container, Project
from ...utils.resource_naming import get_project_path
from .app_manifest import AppManifest2026_05

logger = logging.getLogger(__name__)

__all__ = [
    "StateModelVerdict",
    "StateModelWarning",
    "UpgradeOffer",
    "check_state_model",
    "DEFAULT_SCALABLE_MAX_REPLICAS",
    "WARNING_SQLITE_DETECTED",
    "WARNING_WRITABLE_OUTSIDE_SCOPE",
    "WARNING_FRAMEWORK_PATTERN",
    "STATE_MODEL_STATELESS",
    "STATE_MODEL_PER_INSTALL_VOLUME",
    "STATE_MODEL_SERVICE_PVC",
    "STATE_MODEL_UNKNOWN",
]


# Maximum replicas we permit for a manifest after a successful upgrade
# (e.g. add_postgres). Stays conservative — 10 is the plan's documented
# default. Creators can raise it manually after auditing.
DEFAULT_SCALABLE_MAX_REPLICAS: int = 10

# Warning kind constants — keep in lockstep with the dataclass docstring.
WARNING_SQLITE_DETECTED = "sqlite_detected"
WARNING_WRITABLE_OUTSIDE_SCOPE = "writable_outside_scope"
WARNING_FRAMEWORK_PATTERN = "framework_pattern"

# State-model constants. ``unknown`` is our safe default — when the
# manifest doesn't declare one or declares one we don't recognise we
# treat it as the most restrictive option (max_replicas=1).
STATE_MODEL_STATELESS = "stateless"
STATE_MODEL_PER_INSTALL_VOLUME = "per_install_volume"
STATE_MODEL_SERVICE_PVC = "service_pvc"
STATE_MODEL_SHARED_VOLUME = "shared_volume"
STATE_MODEL_EXTERNAL = "external"
STATE_MODEL_UNKNOWN = "unknown"

# State models that the constraint matrix forces to a single replica.
_PIN_TO_ONE_STATE_MODELS: frozenset[str] = frozenset(
    {
        STATE_MODEL_PER_INSTALL_VOLUME,
        STATE_MODEL_SERVICE_PVC,
        STATE_MODEL_UNKNOWN,
    }
)

# Filesystem patterns that mean "this app holds local state". We match on
# top-level file names + walk the project tree shallowly (depth-capped to
# avoid walking node_modules into the heat death of the universe).
_SQLITE_GLOB_SUFFIXES: tuple[str, ...] = (".db", ".sqlite", ".sqlite3")

# Directories we never descend into during the file-tree scan. These are
# either build artifacts or huge dependency trees; their contents can't
# meaningfully change the state-model verdict and walking them turns a
# fast check into a multi-second one.
_FILE_SCAN_SKIP_DIRS: frozenset[str] = frozenset(
    {
        "node_modules",
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "dist",
        "build",
        ".tesslate",
    }
)
# Cap the file-tree walk so a creator with a runaway repo doesn't stall
# the publish-checker. 5_000 entries is more than enough to surface
# obvious *.db files at the project root or under common ``data/``,
# ``var/``, ``storage/`` directories.
_FILE_SCAN_MAX_ENTRIES: int = 5_000

# Substring matches inside Container.startup_command that indicate a
# SQLite-bound workflow. Intentionally case-insensitive (creators wrote
# these as ``Prisma`` / ``PRISMA`` interchangeably).
_STARTUP_SQLITE_TOKENS: tuple[str, ...] = (
    "sqlite3 ",
    "prisma db push",
    "prisma migrate",
    "sequelize db:migrate",
    "alembic upgrade",
)

# Framework dev-server / cache patterns. Each entry is a regex matched
# against ``Container.startup_command``; if the regex hits we add a
# framework-pattern warning naming both the framework and the writable
# directory it implies.
_FRAMEWORK_PATTERNS: tuple[tuple[str, str, str], ...] = (
    # (regex, framework_label, implied_writable_path)
    (r"\bnext\s+dev\b", "Next.js (dev mode)", ".next/cache"),
    (r"\bnext\s+start\b", "Next.js", ".next/cache"),
    (r"\bdjango\b.*\brunserver\b", "Django", "session/upload directories (default file backends)"),
    (r"\bmanage\.py\s+runserver\b", "Django", "session/upload directories (default file backends)"),
    (r"\bflask\s+run\b", "Flask", "instance/ (Flask default writable folder)"),
    (r"\brails\s+server\b", "Rails", "tmp/ + storage/ (ActiveStorage default disk service)"),
)

# Cache/scratch directories that imply per-process state if not declared
# in runtime.storage.write_scope. The check is membership in the project
# file tree top-level — we don't need to descend into them.
_FRAMEWORK_DIR_HINTS: tuple[tuple[str, str], ...] = (
    (".next/cache", "Next.js build cache"),
    ("node_modules/.cache", "node-build cache"),
    ("instance", "Flask instance/"),
    ("tmp", "Rails tmp/"),
    ("storage", "Rails ActiveStorage / Laravel storage/"),
    ("var", "PHP / Symfony var/"),
)


@dataclass
class StateModelWarning:
    """A single piece of evidence the checker collected.

    ``kind`` is one of:
      * ``sqlite_detected``        — found a ``*.db`` / ``*.sqlite`` file
                                      or a SQLite-bound startup command.
      * ``writable_outside_scope`` — writes to a path the manifest's
                                      ``runtime.storage.write_scope`` does
                                      not enumerate.
      * ``framework_pattern``      — known per-process-state framework
                                      footprint (Next.js cache, Django
                                      file sessions, ...).

    ``detected_at`` is a relative path or container name so the Publish
    Drawer can highlight the exact source.
    """

    kind: str
    message: str
    detected_at: str


@dataclass
class UpgradeOffer:
    """A one-click "Make scalable" choice the Publish Drawer renders.

    ``manifest_patch`` is the JSON-merge-patch the platform applies on
    accept. The patch is *advisory* at this stage — the actual write
    happens in :mod:`managed_resources` (which knows how to mint the
    backing K8s Secret + emit the secret-template env).
    """

    kind: str  # 'add_postgres' | 'add_object_storage' | 'add_kv'
    title: str
    description: str
    manifest_patch: dict[str, Any]


@dataclass
class StateModelVerdict:
    """Verdict returned by :func:`check_state_model`.

    ``detected_state_model`` is what the checker *infers from evidence*,
    not what the manifest declared. The Publish Drawer compares the two
    and refuses to publish if they contradict (e.g. manifest says
    ``stateless`` but the project ships a SQLite file).

    ``pinned_max_replicas`` is the platform-enforced ceiling. After
    accepting an upgrade the verdict is recomputed and this number rises.
    """

    detected_state_model: str
    pinned_max_replicas: int
    warnings: list[StateModelWarning] = field(default_factory=list)
    upgrade_offers: list[UpgradeOffer] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Verdict assembly.
# ---------------------------------------------------------------------------


def _scan_project_files(project_root: Path) -> tuple[list[str], list[str]]:
    """Walk the project tree shallowly. Return (sqlite_paths, framework_dirs).

    Both lists hold paths relative to ``project_root`` so the verdict
    doesn't leak the platform's internal storage layout to the UI.

    The walk is depth-bounded by entry count (``_FILE_SCAN_MAX_ENTRIES``)
    so a runaway monorepo doesn't stall the checker. Skipped dirs come
    from ``_FILE_SCAN_SKIP_DIRS``.
    """
    sqlite_paths: list[str] = []
    framework_dirs: list[str] = []
    seen_framework_hints: set[str] = set()
    if not project_root.exists() or not project_root.is_dir():
        logger.debug(
            "publish_checker: project_root=%s missing; skipping file scan",
            project_root,
        )
        return sqlite_paths, framework_dirs

    # Pre-check well-known framework hint dirs at the project root — cheap
    # and high-signal, doesn't depend on the (capped) walk reaching them.
    for hint_path, label in _FRAMEWORK_DIR_HINTS:
        candidate = project_root / hint_path
        if candidate.exists():
            framework_dirs.append(f"{hint_path}::{label}")
            seen_framework_hints.add(hint_path)

    entry_count = 0
    for current, dirnames, filenames in os.walk(project_root):
        # Mutate ``dirnames`` in place so os.walk skips noisy dirs.
        dirnames[:] = [d for d in dirnames if d not in _FILE_SCAN_SKIP_DIRS]

        rel_current = os.path.relpath(current, project_root)
        for filename in filenames:
            entry_count += 1
            if entry_count > _FILE_SCAN_MAX_ENTRIES:
                logger.info(
                    "publish_checker: file scan hit cap=%d at %s; "
                    "results may be incomplete",
                    _FILE_SCAN_MAX_ENTRIES,
                    rel_current,
                )
                return sqlite_paths, framework_dirs
            lower = filename.lower()
            if any(lower.endswith(suffix) for suffix in _SQLITE_GLOB_SUFFIXES):
                rel_path = (
                    filename if rel_current in (".", "") else os.path.join(rel_current, filename)
                )
                sqlite_paths.append(rel_path)

    return sqlite_paths, framework_dirs


def _scan_startup_commands(
    containers: list[Container],
) -> tuple[list[tuple[str, str]], list[tuple[str, str, str]]]:
    """Inspect ``Container.startup_command`` rows.

    Returns:
        (sqlite_hits, framework_hits) where:
          * ``sqlite_hits`` is a list of ``(container_name, command_excerpt)``
            for any startup_command containing a SQLite-bound CLI.
          * ``framework_hits`` is a list of
            ``(container_name, framework_label, implied_writable_path)``
            for any startup_command that matches a known dev-server regex.
    """
    sqlite_hits: list[tuple[str, str]] = []
    framework_hits: list[tuple[str, str, str]] = []
    for container in containers:
        cmd = (container.startup_command or "").strip()
        if not cmd:
            continue
        cmd_lower = cmd.lower()
        for token in _STARTUP_SQLITE_TOKENS:
            if token in cmd_lower:
                sqlite_hits.append((container.name, cmd[:200]))
                break
        for pattern, label, implied in _FRAMEWORK_PATTERNS:
            if re.search(pattern, cmd_lower):
                framework_hits.append((container.name, label, implied))
    return sqlite_hits, framework_hits


def _writable_scope_normalised(manifest: AppManifest2026_05) -> set[str]:
    """Return the manifest's declared write_scope as a set of strings.

    Returns an empty set when no scope is declared; callers treat that as
    "the manifest hasn't said anything", not "the manifest forbids
    everything" — the constraint matrix is what enforces safety.
    """
    storage = manifest.runtime.storage
    if storage is None:
        return set()
    return {p.strip() for p in storage.write_scope if p and p.strip()}


def _path_inside_scope(path: str, scope: set[str]) -> bool:
    """Return True if ``path`` is inside any directory in ``scope``.

    Comparison is structural — we don't resolve symlinks here. A scope of
    ``/app/data`` matches ``/app/data/sessions.db``,
    ``app/data/sessions.db``, and ``./app/data/sessions.db``. Matching
    is intentionally lenient because creators write paths inconsistently.
    """
    if not scope:
        return False
    norm = path.lstrip("./").lstrip("/")
    for entry in scope:
        candidate = entry.lstrip("./").lstrip("/")
        if not candidate:
            continue
        if norm == candidate or norm.startswith(candidate + "/"):
            return True
    return False


def _build_postgres_offer(
    manifest: AppManifest2026_05,
) -> UpgradeOffer:
    """Construct the "Add OpenSail Postgres" upgrade offer.

    The patch is what :mod:`managed_resources.add_postgres` actually
    applies; we surface it here so the Publish Drawer can render a diff
    preview before the creator clicks accept.

    The ``${secret:...}`` template references the per-app Secret name
    minted at upgrade time. The ``${self.id}`` placeholder is the install
    UUID resolved by ``env_resolver`` at pod-start time — already a
    supported pattern (see ``services/apps/env_resolver.py``).
    """
    primary_container: str | None = None
    if manifest.surfaces:
        primary_container = next(
            (s.container for s in manifest.surfaces if s.container),
            None,
        )

    container_env_patch: dict[str, Any] = {
        "DATABASE_URL": "${secret:app-managed-db-${self.id}/url}"
    }

    return UpgradeOffer(
        kind="add_postgres",
        title="Add OpenSail Postgres",
        description=(
            "Provision a per-app managed Postgres database. The platform mints "
            "credentials, injects DATABASE_URL into the primary container, and "
            "raises max_replicas so your app can scale safely."
        ),
        manifest_patch={
            "runtime": {
                "state_model": STATE_MODEL_EXTERNAL,
                "scaling": {"max_replicas": DEFAULT_SCALABLE_MAX_REPLICAS},
            },
            "compute": {
                "containers": [
                    {
                        # The primary container name is recorded so the patch
                        # consumer (managed_resources.add_postgres) can target
                        # the right entry; ``None`` means "first container".
                        "name": primary_container,
                        "env": container_env_patch,
                    }
                ]
            },
        },
    )


async def check_state_model(
    db: AsyncSession,
    *,
    project: Project,
    manifest: AppManifest2026_05,
) -> StateModelVerdict:
    """Run every per-replica-safety heuristic and assemble the verdict.

    Args:
        db: Active SQLAlchemy session — used to load the project's
            Container rows when not eagerly loaded.
        project: The source project the creator is publishing from.
        manifest: The parsed 2026-05 manifest the Publish Drawer is about
            to validate. We READ ONLY — we never mutate it here.

    Returns:
        A populated :class:`StateModelVerdict`.
    """
    warnings: list[StateModelWarning] = []

    # 1. Project file tree (top-level + capped walk).
    project_root = Path(get_project_path(project.owner_id, project.id))
    sqlite_files, framework_dirs = _scan_project_files(project_root)

    # 2. Container.startup_command sniffing.
    container_rows = (
        (
            await db.execute(
                select(Container).where(Container.project_id == project.id)
            )
        )
        .scalars()
        .all()
    )
    sqlite_cmds, framework_cmds = _scan_startup_commands(list(container_rows))

    # 3. Aggregate evidence into typed warnings.
    has_state_evidence = False
    write_scope = _writable_scope_normalised(manifest)

    for relpath in sqlite_files:
        has_state_evidence = True
        warnings.append(
            StateModelWarning(
                kind=WARNING_SQLITE_DETECTED,
                message=(
                    f"SQLite database file detected at {relpath}. "
                    "Per-replica safety pins max_replicas=1 unless you move "
                    "to an external database."
                ),
                detected_at=relpath,
            )
        )
        if write_scope and not _path_inside_scope(relpath, write_scope):
            warnings.append(
                StateModelWarning(
                    kind=WARNING_WRITABLE_OUTSIDE_SCOPE,
                    message=(
                        f"SQLite file {relpath} sits outside the manifest's "
                        f"runtime.storage.write_scope ({sorted(write_scope)})."
                    ),
                    detected_at=relpath,
                )
            )

    for container_name, cmd_excerpt in sqlite_cmds:
        has_state_evidence = True
        warnings.append(
            StateModelWarning(
                kind=WARNING_SQLITE_DETECTED,
                message=(
                    f"Container '{container_name}' startup command invokes a "
                    f"SQLite-bound tool: {cmd_excerpt!r}"
                ),
                detected_at=container_name,
            )
        )

    for raw in framework_dirs:
        # raw is "<rel_path>::<label>" from the file scanner.
        rel_path, _, label = raw.partition("::")
        has_state_evidence = True
        warnings.append(
            StateModelWarning(
                kind=WARNING_FRAMEWORK_PATTERN,
                message=(
                    f"Framework writable directory present: {rel_path} "
                    f"({label}). This implies per-process state."
                ),
                detected_at=rel_path,
            )
        )

    for container_name, framework_label, implied_path in framework_cmds:
        has_state_evidence = True
        warnings.append(
            StateModelWarning(
                kind=WARNING_FRAMEWORK_PATTERN,
                message=(
                    f"Container '{container_name}' runs {framework_label} which "
                    f"writes to {implied_path}. Pin replicas or migrate writes "
                    "to a managed backend."
                ),
                detected_at=container_name,
            )
        )

    # 4. Manifest-vs-evidence contradiction check.
    declared_model = manifest.runtime.state_model
    if declared_model == STATE_MODEL_STATELESS and has_state_evidence:
        warnings.append(
            StateModelWarning(
                kind=WARNING_WRITABLE_OUTSIDE_SCOPE,
                message=(
                    "Manifest declares runtime.state_model='stateless' but the "
                    "project ships writable state. Either remove the writable "
                    "files or change state_model to per_install_volume / external."
                ),
                detected_at="runtime.state_model",
            )
        )

    # 5. Resolve the inferred state model + the pinned ceiling.
    if declared_model == STATE_MODEL_EXTERNAL:
        # Creator already routed state to an external store — trust it.
        # We still surface warnings so the Drawer can show "you said
        # external; we noticed these files locally — make sure they're
        # not authoritative".
        detected_state_model = STATE_MODEL_EXTERNAL
        pinned_max_replicas = manifest.runtime.scaling.max_replicas
    elif declared_model == STATE_MODEL_STATELESS and not has_state_evidence:
        detected_state_model = STATE_MODEL_STATELESS
        pinned_max_replicas = manifest.runtime.scaling.max_replicas
    elif declared_model in (STATE_MODEL_PER_INSTALL_VOLUME, STATE_MODEL_SERVICE_PVC):
        detected_state_model = declared_model
        pinned_max_replicas = 1
    elif has_state_evidence:
        # Evidence + ambiguous (or stateless-but-contradicted) declaration:
        # treat as per-install-volume which is the safest interpretation.
        detected_state_model = STATE_MODEL_PER_INSTALL_VOLUME
        pinned_max_replicas = 1
    elif declared_model == STATE_MODEL_SHARED_VOLUME:
        # We don't (yet) know whether the user's storage class supports
        # ReadWriteMany. Be conservative — pin to 1, leave the upgrade
        # offer in place so a creator can switch to external.
        detected_state_model = STATE_MODEL_SHARED_VOLUME
        pinned_max_replicas = 1
    else:
        detected_state_model = STATE_MODEL_UNKNOWN
        pinned_max_replicas = 1

    # 6. Build upgrade offers. We only offer postgres when the verdict
    # would otherwise pin to 1 — there's no reason to nudge a stateless
    # app onto a managed DB it doesn't need.
    upgrade_offers: list[UpgradeOffer] = []
    if pinned_max_replicas <= 1 and detected_state_model not in (STATE_MODEL_EXTERNAL,):
        upgrade_offers.append(_build_postgres_offer(manifest))
        # add_object_storage / add_kv land in follow-up waves; the offer
        # builders live here next to add_postgres so the UX is a single
        # consistent surface.

    return StateModelVerdict(
        detected_state_model=detected_state_model,
        pinned_max_replicas=pinned_max_replicas,
        warnings=warnings,
        upgrade_offers=upgrade_offers,
    )
