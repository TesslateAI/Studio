"""Managed-resource provisioning hooks for the publish-time upgrade flow.

Phase 5 — see plan §"Per-Replica Safety for Vibecoded Apps" / "Add OpenSail
Postgres upgrade flow".

The Publish Drawer asks :func:`add_postgres` (and, in follow-up waves,
``add_object_storage`` / ``add_kv``) when the creator clicks "Make
scalable". Each function is responsible for:

1. **Provisioning the backing resource** — for Postgres, a logical DB in
   the platform's managed pool. **Phase 5 stubs this**: the actual
   provisioning needs ops-side work (a managed Postgres, credential
   rotation policy, network policy) that ships in a separate PR.
   The stub returns a deterministic-shape connection URL so the rest of
   the pipeline can wire end-to-end without waiting on ops.
2. **Minting credentials** — username + password generated locally.
3. **Writing the K8s Secret** — this part is REAL. The Secret is small,
   harmless, and wiring it now means the manifest patch resolves
   correctly the day the real provisioner lands.
4. **Patching the manifest** — a JSON-merge-patch is computed and, when
   ``opensail.app.yaml`` exists in the project workspace, written back
   to disk. When it doesn't, the patch is returned to the caller so the
   Publish Drawer can merge it client-side before the creator saves.
5. **Writing a one-time SQLite-→-Postgres migration helper** into
   ``scripts/migrate-from-sqlite.{ts,py}`` based on the project's
   primary language. The creator runs this once locally / in CI; the
   platform never executes it.

Stubbing rationale
------------------
Real provisioning requires:

* A managed Postgres pool (RDS / CloudNativePG / a single shared HA
  cluster — TBD by ops).
* A credential-rotation policy (the K8s Secret should be re-rolled on a
  cadence and apps should be restarted).
* A network policy that lets ``proj-*`` namespaces talk to the pool.

None of those exist yet in the platform's K8s overlays — and Phase 5 of
the runtime plan is explicitly UX-shaped, not infra-shaped. The stub
documents the expected behaviour loudly so the follow-up PR replaces
exactly one function (``_provision_postgres_db``) without touching the
manifest patch / migration helper / Secret pipeline.
"""

from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project, User
from ...utils.resource_naming import get_project_path
from .publish_checker import (
    DEFAULT_SCALABLE_MAX_REPLICAS,
    STATE_MODEL_EXTERNAL,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ManagedDbResult",
    "add_postgres",
    "managed_db_secret_name",
    "MANAGED_DB_LABEL_KEY",
    "MANAGED_DB_LABEL_VALUE",
]


MANAGED_DB_LABEL_KEY = "tesslate.io/managed-by"
MANAGED_DB_LABEL_VALUE = "managed-resources"
APP_PROJECT_LABEL_KEY = "tesslate.io/project-id"


def managed_db_secret_name(project_id: UUID | str) -> str:
    """Canonical name for the per-app managed-db Secret.

    The plan calls this ``app-managed-db-{app_id}``. Pre-publish there is
    no AppVersion yet, so we key on the source ``project_id`` — every
    publish from the same source project reuses the same Secret, and the
    install pipeline carries the value over to the AppInstance namespace.
    """
    return f"app-managed-db-{project_id}"


@dataclass
class ManagedDbResult:
    """Return shape from :func:`add_postgres`.

    ``manifest_patch`` is the JSON-merge-patch the caller should apply to
    ``opensail.app.yaml``. We also write the patched file directly when
    one is present in the workspace; the caller still receives the patch
    so it can render a diff or merge into an in-memory draft.

    ``connection_url`` is the **stub** value injected into the K8s
    Secret. The real provisioner will overwrite this shape with the
    address of the actually-provisioned database.
    """

    secret_name: str
    secret_namespace: str
    connection_url: str
    db_name: str
    db_user: str
    manifest_patch: dict[str, Any]
    manifest_path: str | None = None
    migration_script_path: str | None = None
    is_stub_provisioner: bool = True
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Stubbed provisioning. Replaced by ops-side PR — see module docstring.
# ---------------------------------------------------------------------------


def _stub_db_name(project_slug: str, nonce: str) -> str:
    """Compose a deterministic-shape stub DB name.

    Slug is sanitised so the result fits Postgres' identifier rules
    (alphanumeric + underscore, ASCII, leading non-digit). The trailing
    nonce keeps two publishes from the same slug from colliding once the
    real provisioner lands.
    """
    safe = "".join(ch if ch.isalnum() else "_" for ch in project_slug.lower())
    safe = safe.lstrip("_") or "app"
    return f"app_{safe}_{nonce}"[:63]


def _provision_postgres_db(
    *,
    project: Project,
) -> tuple[str, str, str, str]:
    """**STUB** — return a fake (db_name, db_user, db_password, connection_url).

    Real implementation will:
      * Connect to the platform's managed Postgres pool.
      * ``CREATE DATABASE app_{slug}_{nonce};``
      * ``CREATE USER app_{slug}_{nonce} WITH PASSWORD '<random>';``
      * ``GRANT ALL PRIVILEGES ON DATABASE app_{slug}_{nonce} TO app_{slug}_{nonce};``
      * Return the credential triple.

    Until that ships, we generate a deterministic-shape URL that points
    at the never-resolving DNS host ``managed-postgres-pool`` so app
    pods FAIL FAST (CrashLoopBackOff with a clear "host not found"
    error) instead of silently running on a missing DB. The Publish
    Drawer surfaces ``ManagedDbResult.is_stub_provisioner=True`` so the
    creator knows the env wiring is in place but the DB itself isn't
    real yet.
    """
    nonce = secrets.token_hex(4)
    db_name = _stub_db_name(project.slug, nonce)
    db_user = db_name  # Real impl uses a separate user; stub keeps it 1:1.
    db_password = secrets.token_urlsafe(24)
    # Host points at a sentinel DNS name that intentionally won't resolve
    # so the failure mode is loud + traceable.
    connection_url = (
        f"postgresql://{db_user}:{db_password}@managed-postgres-pool:5432/{db_name}"
    )
    logger.warning(
        "managed_resources.add_postgres: returning STUBBED Postgres URL for "
        "project=%s slug=%s db=%s — real provisioner pending ops PR",
        project.id,
        project.slug,
        db_name,
    )
    return db_name, db_user, db_password, connection_url


# ---------------------------------------------------------------------------
# K8s Secret write. REAL — uses the same pattern as user_secret_propagator.
# ---------------------------------------------------------------------------


def _build_secret_namespace(project: Project) -> str:
    """Mirror the platform's per-project namespace pattern (``proj-<uuid>``).

    See ``orchestrator/app/routers/snapshots.py:368`` and friends for the
    ground-truth references; we cannot import the K8s client here without
    pulling a heavyweight dependency into the publish-checker stack, so
    we hand-string-format the same template they all use.
    """
    return f"proj-{project.id}"


def _resolve_core_v1_api():  # pragma: no cover — exercised by integration tests
    """Lazily build a ``CoreV1Api`` client.

    Mirrors :class:`KubernetesClient.__init__` — try in-cluster first,
    fall back to ``~/.kube/config`` for dev. Returns ``None`` when no
    config is loadable so callers in non-K8s environments (desktop /
    docker mode) can swallow the failure cleanly.
    """
    try:
        from kubernetes import client as k8s_client
        from kubernetes import config as k8s_config

        try:
            k8s_config.load_incluster_config()
        except k8s_config.ConfigException:
            try:
                k8s_config.load_kube_config()
            except k8s_config.ConfigException:
                logger.info(
                    "managed_resources: no kube config found; skipping Secret write"
                )
                return None
        return k8s_client.CoreV1Api()
    except ImportError:
        logger.info(
            "managed_resources: kubernetes python client not installed; "
            "skipping Secret write"
        )
        return None


def _write_managed_db_secret(
    core_v1: Any,
    *,
    secret_name: str,
    namespace: str,
    project: Project,
    connection_url: str,
    db_name: str,
    db_user: str,
    db_password: str,
) -> str:
    """Create-or-patch the Secret. Mirrors user_secret_propagator._upsert_secret.

    Returns ``"created"``, ``"patched"``, or ``"skipped"`` (when no K8s
    client is available — desktop / docker mode).
    """
    if core_v1 is None:
        return "skipped"

    from kubernetes import client as k8s_client
    from kubernetes.client.rest import ApiException

    string_data = {
        "url": connection_url,
        "host": "managed-postgres-pool",
        "port": "5432",
        "db": db_name,
        "user": db_user,
        "password": db_password,
    }
    labels = {
        MANAGED_DB_LABEL_KEY: MANAGED_DB_LABEL_VALUE,
        APP_PROJECT_LABEL_KEY: str(project.id),
    }
    annotations = {
        "tesslate.io/source": "managed-resources.add_postgres",
        # Loud marker so anybody inspecting the Secret in kubectl knows
        # the URL is a stub until the ops PR lands.
        "tesslate.io/provisioner-status": "stubbed",
    }
    body = k8s_client.V1Secret(
        metadata=k8s_client.V1ObjectMeta(
            name=secret_name,
            namespace=namespace,
            labels=labels,
            annotations=annotations,
        ),
        type="Opaque",
        string_data=string_data,
    )
    try:
        core_v1.create_namespaced_secret(namespace=namespace, body=body)
        logger.info(
            "managed_resources: created Secret %s in ns=%s (stubbed URL)",
            secret_name,
            namespace,
        )
        return "created"
    except ApiException as e:
        if e.status == 409:
            core_v1.patch_namespaced_secret(
                name=secret_name,
                namespace=namespace,
                body={
                    "stringData": string_data,
                    "metadata": {
                        "labels": labels,
                        "annotations": annotations,
                    },
                },
            )
            logger.info(
                "managed_resources: patched Secret %s in ns=%s (stubbed URL)",
                secret_name,
                namespace,
            )
            return "patched"
        raise


# ---------------------------------------------------------------------------
# Manifest patching + migration helper.
# ---------------------------------------------------------------------------


def _build_manifest_patch(secret_name: str) -> dict[str, Any]:
    """The JSON-merge-patch applied to the workspace's ``opensail.app.yaml``.

    Patch shape:

    * ``runtime.state_model = 'external'`` — the Pydantic validator
      explicitly forbids ``per_install_volume``/``service_pvc`` with
      ``max_replicas > 1``, so flipping the model is required before the
      replicas bump is legal.
    * ``runtime.scaling.max_replicas = DEFAULT_SCALABLE_MAX_REPLICAS``
    * ``compute.containers[<primary>].env.DATABASE_URL`` — uses the
      ``${secret:...}`` template the env_resolver already understands.
    """
    return {
        "runtime": {
            "state_model": STATE_MODEL_EXTERNAL,
            "scaling": {"max_replicas": DEFAULT_SCALABLE_MAX_REPLICAS},
        },
        "compute": {
            "containers": [
                {
                    "env": {
                        "DATABASE_URL": (
                            "${secret:" + secret_name + "/url}"
                        )
                    }
                }
            ]
        },
    }


def _project_manifest_path(project: Project) -> Path:
    """Return where ``opensail.app.yaml`` lives in the workspace.

    The plan keeps the manifest at the project root. We never create it
    here — :func:`add_postgres` only writes through if the file exists,
    so the Publish Drawer (which owns the canonical manifest draft)
    stays the single source of truth on shape.
    """
    return Path(get_project_path(project.owner_id, project.id)) / "opensail.app.yaml"


def _apply_manifest_patch_to_disk(
    manifest_path: Path,
    patch: dict[str, Any],
) -> str | None:
    """Best-effort YAML merge into ``opensail.app.yaml``.

    Returns the absolute path of the file written, or ``None`` when the
    file did not exist (caller surfaces the patch to the UI instead).
    Errors are logged and swallowed — the manifest_patch is what the
    Publish Drawer renders authoritatively, and we don't want a
    YAML-parse hiccup to roll back the K8s Secret write.
    """
    if not manifest_path.exists():
        return None
    try:
        import yaml  # type: ignore
    except ImportError:
        logger.warning(
            "managed_resources: yaml not installed; cannot patch %s",
            manifest_path,
        )
        return None
    try:
        with manifest_path.open("r", encoding="utf-8") as f:
            current = yaml.safe_load(f) or {}
        if not isinstance(current, dict):
            logger.warning(
                "managed_resources: %s is not a YAML mapping; refusing to patch",
                manifest_path,
            )
            return None
        merged = _deep_merge(current, patch)
        with manifest_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(merged, f, sort_keys=False)
        return str(manifest_path)
    except Exception as exc:  # noqa: BLE001 — best-effort write
        logger.warning(
            "managed_resources: failed to patch %s: %r", manifest_path, exc
        )
        return None


def _deep_merge(target: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """JSON-merge-patch semantics for nested dicts.

    Lists are NOT merged element-wise — the patch list replaces the
    target list. This matches RFC 7396 and what every UI diff tool
    expects.
    """
    out = dict(target)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _detect_primary_language(project_root: Path) -> str:
    """Pick a language for the migration helper script.

    Heuristic: ``package.json`` at root → ``ts``; ``pyproject.toml``,
    ``requirements.txt``, or ``Pipfile`` → ``py``. Default ``py`` —
    Python's stdlib has ``sqlite3`` so the helper runs without any
    install.
    """
    if (project_root / "package.json").exists():
        return "ts"
    if any(
        (project_root / name).exists()
        for name in ("pyproject.toml", "requirements.txt", "Pipfile")
    ):
        return "py"
    return "py"


_MIGRATION_PY_TEMPLATE = '''"""One-time SQLite → Postgres migration helper.

Generated by OpenSail managed_resources.add_postgres. Run ONCE locally
or in CI before redeploying the app:

    SQLITE_PATH=./app/data/sessions.db DATABASE_URL=postgres://... python scripts/migrate-from-sqlite.py

This script copies every table from the SQLite file at ``SQLITE_PATH``
into the Postgres database at ``DATABASE_URL``. Tables are created in
Postgres with permissive types (TEXT for everything) — refine by hand
afterward.

The script is intentionally dependency-light: stdlib ``sqlite3`` plus
``psycopg2`` (or ``psycopg``). Install one of those before running.
"""

import os
import sqlite3

DATABASE_URL = os.environ.get("DATABASE_URL")
SQLITE_PATH = os.environ.get("SQLITE_PATH", "./app/data/app.db")

if not DATABASE_URL:
    raise SystemExit("DATABASE_URL is required")

try:
    import psycopg2 as pg
except ImportError:  # pragma: no cover
    raise SystemExit("psycopg2 not installed: pip install psycopg2-binary")

src = sqlite3.connect(SQLITE_PATH)
src.row_factory = sqlite3.Row
dst = pg.connect(DATABASE_URL)
dst.autocommit = False

cur = src.cursor()
tables = [row[0] for row in cur.execute(
    "SELECT name FROM sqlite_master WHERE type=\\"table\\" AND name NOT LIKE \\"sqlite_%\\""
).fetchall()]

with dst.cursor() as pgcur:
    for table in tables:
        rows = list(cur.execute(f"SELECT * FROM {table}").fetchall())
        if not rows:
            continue
        cols = rows[0].keys()
        col_defs = ", ".join(f"{c} TEXT" for c in cols)
        pgcur.execute(f"CREATE TABLE IF NOT EXISTS {table} ({col_defs})")
        placeholders = ", ".join(["%s"] * len(cols))
        col_list = ", ".join(cols)
        pgcur.executemany(
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})",
            [tuple(str(r[c]) if r[c] is not None else None for c in cols) for r in rows],
        )
        print(f"migrated {len(rows)} rows from {table}")
    dst.commit()

print("Migration complete.")
'''


_MIGRATION_TS_TEMPLATE = '''/**
 * One-time SQLite → Postgres migration helper.
 *
 * Generated by OpenSail managed_resources.add_postgres. Run ONCE before
 * redeploying the app:
 *
 *     SQLITE_PATH=./app/data/sessions.db DATABASE_URL=postgres://... \\
 *         npx ts-node scripts/migrate-from-sqlite.ts
 *
 * Requires `better-sqlite3` and `pg`. Install with:
 *     npm i -D better-sqlite3 pg @types/pg
 */

import Database from "better-sqlite3";
import { Client } from "pg";

const DATABASE_URL = process.env.DATABASE_URL;
const SQLITE_PATH = process.env.SQLITE_PATH ?? "./app/data/app.db";

if (!DATABASE_URL) {
  throw new Error("DATABASE_URL is required");
}

async function main() {
  const src = new Database(SQLITE_PATH, { readonly: true });
  const dst = new Client({ connectionString: DATABASE_URL });
  await dst.connect();

  const tables = src
    .prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    .all()
    .map((r: any) => r.name);

  for (const table of tables) {
    const rows = src.prepare(`SELECT * FROM ${table}`).all() as Record<string, unknown>[];
    if (rows.length === 0) continue;
    const cols = Object.keys(rows[0]);
    const colDefs = cols.map((c) => `${c} TEXT`).join(", ");
    await dst.query(`CREATE TABLE IF NOT EXISTS ${table} (${colDefs})`);
    const placeholders = cols.map((_, i) => `$${i + 1}`).join(", ");
    for (const row of rows) {
      await dst.query(
        `INSERT INTO ${table} (${cols.join(", ")}) VALUES (${placeholders})`,
        cols.map((c) => (row[c] === null ? null : String(row[c]))),
      );
    }
    console.log(`migrated ${rows.length} rows from ${table}`);
  }

  await dst.end();
  src.close();
  console.log("Migration complete.");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
'''


def _write_migration_helper(project_root: Path) -> str | None:
    """Write ``scripts/migrate-from-sqlite.{ts,py}`` once.

    Idempotent: existing files are left in place so we don't clobber the
    creator's hand-edits. Returns the absolute path written or pre-
    existing, or ``None`` if the project root doesn't exist.
    """
    if not project_root.exists():
        return None
    scripts_dir = project_root / "scripts"
    try:
        scripts_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning(
            "managed_resources: cannot create %s: %r", scripts_dir, exc
        )
        return None

    language = _detect_primary_language(project_root)
    if language == "ts":
        target = scripts_dir / "migrate-from-sqlite.ts"
        template = _MIGRATION_TS_TEMPLATE
    else:
        target = scripts_dir / "migrate-from-sqlite.py"
        template = _MIGRATION_PY_TEMPLATE

    if target.exists():
        return str(target)
    try:
        target.write_text(template, encoding="utf-8")
        os.chmod(target, 0o644)
        return str(target)
    except OSError as exc:
        logger.warning(
            "managed_resources: failed to write %s: %r", target, exc
        )
        return None


# ---------------------------------------------------------------------------
# Public entry point.
# ---------------------------------------------------------------------------


async def add_postgres(
    db: AsyncSession,
    *,
    project: Project,
    user: User,
    core_v1: Any | None = None,
) -> ManagedDbResult:
    """Provision per-app Postgres + patch the manifest + write the migration helper.

    Args:
        db: Active SQLAlchemy session. Reserved for the real provisioner
            (which will record the DB in an ``app_managed_databases`` row);
            the stub does not need it.
        project: The source project the creator is publishing from.
        user: The acting user — recorded in audit metadata only.
        core_v1: Optional injected ``CoreV1Api``. Tests pass a mock; the
            production path resolves a client lazily.

    Returns:
        :class:`ManagedDbResult` with the K8s Secret name, the manifest
        patch the caller should apply, and the path of the migration
        helper written into the project workspace.
    """
    secret_name = managed_db_secret_name(project.id)
    namespace = _build_secret_namespace(project)

    # 1. Provision (STUB).
    db_name, db_user, db_password, connection_url = _provision_postgres_db(project=project)

    # 2. Write the K8s Secret. Real, but optional — desktop/docker callers
    # legitimately have no K8s API to talk to.
    if core_v1 is None:
        core_v1 = _resolve_core_v1_api()
    secret_status: str = "skipped"
    try:
        secret_status = _write_managed_db_secret(
            core_v1,
            secret_name=secret_name,
            namespace=namespace,
            project=project,
            connection_url=connection_url,
            db_name=db_name,
            db_user=db_user,
            db_password=db_password,
        )
    except Exception as exc:  # noqa: BLE001 — log + surface in notes
        logger.warning(
            "managed_resources.add_postgres: Secret write failed (project=%s): %r",
            project.id,
            exc,
        )
        secret_status = f"errored: {exc!r}"

    # 3. Build the manifest patch + best-effort write to disk.
    manifest_patch = _build_manifest_patch(secret_name)
    manifest_path = _project_manifest_path(project)
    written_manifest = _apply_manifest_patch_to_disk(manifest_path, manifest_patch)

    # 4. Write the migration helper.
    project_root = Path(get_project_path(project.owner_id, project.id))
    migration_path = _write_migration_helper(project_root)

    notes: list[str] = [
        "Postgres provisioning is STUBBED in Phase 5. The DATABASE_URL "
        "in the K8s Secret points at the unresolvable host "
        "'managed-postgres-pool' so app pods fail loudly until the ops "
        "PR replaces _provision_postgres_db.",
        f"Secret write status: {secret_status}",
    ]
    if written_manifest is None:
        notes.append(
            "opensail.app.yaml not present in workspace; returning patch "
            "for the Publish Drawer to merge."
        )
    if migration_path is None:
        notes.append(
            "Migration helper not written (project root missing or unwritable)."
        )

    return ManagedDbResult(
        secret_name=secret_name,
        secret_namespace=namespace,
        connection_url=connection_url,
        db_name=db_name,
        db_user=db_user,
        manifest_patch=manifest_patch,
        manifest_path=written_manifest,
        migration_script_path=migration_path,
        is_stub_provisioner=True,
        notes=notes,
    )
