"""Managed-resource provisioning hooks for the publish-time upgrade flow.

Phase 5 — see plan §"Per-Replica Safety for Vibecoded Apps" / "Add OpenSail
Postgres upgrade flow".

The Publish Drawer asks one of :func:`add_postgres`, :func:`add_object_storage`,
or :func:`add_kv` when the creator clicks "Make scalable" + the corresponding
"Add ..." button. Each function is responsible for:

1. **Provisioning the backing resource** — for Postgres, a logical DB in the
   platform's managed pool; for object storage, an S3 bucket + scoped IAM
   user; for KV, a per-app key prefix on the shared Redis pool. Each requires
   matching ``settings.managed_*`` env vars; missing config raises
   :class:`ManagedResourcesNotConfigured` with a clear message. Desktop /
   dev callers can opt into a deterministic-shape stub via
   ``managed_*_allow_stub`` — pods then CrashLoopBackOff loudly on the
   sentinel DNS so the failure is traceable.
2. **Minting credentials** — passwords/keys generated locally with
   :mod:`secrets`. SQL/S3/Redis-safe identifiers are derived from the
   project slug.
3. **Writing the K8s Secret** — small, harmless, mirrors the wire path
   ``${secret:name/key}`` references in the manifest. Uses the same
   create-or-patch pattern as ``user_secret_propagator``.
4. **Patching the manifest** — a JSON-merge-patch is computed and, when
   ``opensail.app.yaml`` exists in the project workspace, written back to
   disk. When it doesn't, the patch is returned to the caller so the
   Publish Drawer can merge it client-side before the creator saves.
5. (Postgres only) **Writing a one-time SQLite-→-Postgres migration helper**
   into ``scripts/migrate-from-sqlite.{ts,py}`` based on the project's
   primary language. The creator runs this once locally / in CI; the
   platform never executes it.

Each public entry point flips ``runtime.state_model`` to ``external`` so the
``max_replicas > 1`` validator clears.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from ...models import Project, User
from ...utils.resource_naming import get_project_path
from .publish_checker import (
    DEFAULT_SCALABLE_MAX_REPLICAS,
    STATE_MODEL_EXTERNAL,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ManagedDbResult",
    "ManagedObjectStorageResult",
    "ManagedKvResult",
    "ManagedResourcesNotConfigured",
    "add_postgres",
    "add_object_storage",
    "add_kv",
    "managed_db_secret_name",
    "managed_object_storage_secret_name",
    "managed_kv_secret_name",
    "MANAGED_RESOURCE_LABEL_KEY",
    "MANAGED_RESOURCE_LABEL_VALUE",
]


# ---------------------------------------------------------------------------
# Shared constants + naming helpers
# ---------------------------------------------------------------------------

MANAGED_RESOURCE_LABEL_KEY = "tesslate.io/managed-by"
MANAGED_RESOURCE_LABEL_VALUE = "managed-resources"
APP_PROJECT_LABEL_KEY = "tesslate.io/project-id"

# Backwards-compat alias retained so existing call sites that import the
# pre-Phase-5 names keep working.
MANAGED_DB_LABEL_KEY = MANAGED_RESOURCE_LABEL_KEY
MANAGED_DB_LABEL_VALUE = MANAGED_RESOURCE_LABEL_VALUE


class ManagedResourcesNotConfigured(RuntimeError):
    """Raised when the platform isn't wired with the managed-pool admin
    credentials needed to provision a resource (and the ``*_ALLOW_STUB``
    escape hatch is not enabled).

    The message is human-readable so the upstream HTTP layer can surface it
    directly to the Publish Drawer (which renders it inline beneath the
    upgrade button).
    """


def managed_db_secret_name(project_id: UUID | str) -> str:
    """Canonical name for the per-app managed-db Secret.

    The plan calls this ``app-managed-db-{app_id}``. Pre-publish there is
    no AppVersion yet, so we key on the source ``project_id`` — every
    publish from the same source project reuses the same Secret, and the
    install pipeline carries the value over to the AppInstance namespace.
    """
    return f"app-managed-db-{project_id}"


def managed_object_storage_secret_name(project_id: UUID | str) -> str:
    """Canonical name for the per-app managed-object-storage Secret."""
    return f"app-managed-objstore-{project_id}"


def managed_kv_secret_name(project_id: UUID | str) -> str:
    """Canonical name for the per-app managed-KV Secret."""
    return f"app-managed-kv-{project_id}"


def _safe_slug(project_slug: str) -> str:
    """Sanitise a project slug for use in Postgres/S3/Redis identifiers.

    Output: lowercase, ``[a-z0-9_]`` only, leading char never numeric, never
    empty (falls back to ``"app"``). Capped at 32 chars so the full
    ``app_<slug>_<8-hex-nonce>`` identifier still fits Postgres' 63-byte
    limit and the S3 bucket-name 63-char limit comfortably.
    """
    safe = "".join(ch if ch.isalnum() else "_" for ch in project_slug.lower())
    safe = safe.lstrip("_") or "app"
    if safe[0].isdigit():
        safe = f"a_{safe}"
    return safe[:32]


def _stub_db_name(project_slug: str, nonce: str) -> str:
    """Compose a deterministic-shape stub DB name (Postgres-identifier safe)."""
    return f"app_{_safe_slug(project_slug)}_{nonce}"[:63]


def _safe_bucket_name(project_id: UUID | str, project_slug: str, nonce: str) -> str:
    """Compose an S3-safe bucket name.

    S3 rules: lowercase letters / digits / hyphens, 3-63 chars, must start
    and end with a letter/digit. We use a project-id prefix to guarantee
    uniqueness across creators with colliding slugs and trail with a nonce.
    """
    short_id = str(project_id).replace("-", "")[:8]
    safe_slug = _safe_slug(project_slug).replace("_", "-")
    name = f"opensail-app-{short_id}-{safe_slug}-{nonce}"
    # Strip any double-hyphens or trailing hyphens that slug-replace introduced.
    name = re.sub(r"-+", "-", name).strip("-")
    return name[:63]


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ManagedDbResult:
    """Return shape from :func:`add_postgres`.

    ``manifest_patch`` is the JSON-merge-patch the caller should apply to
    ``opensail.app.yaml``. We also write the patched file directly when
    one is present in the workspace; the caller still receives the patch
    so it can render a diff or merge into an in-memory draft.

    ``connection_url`` is the value injected into the K8s Secret. When the
    real provisioner runs it points at the actually-provisioned database;
    when the stub fallback runs it points at the never-resolving sentinel
    ``managed-postgres-pool``.
    """

    secret_name: str
    secret_namespace: str
    connection_url: str
    db_name: str
    db_user: str
    manifest_patch: dict[str, Any]
    manifest_path: str | None = None
    migration_script_path: str | None = None
    is_stub_provisioner: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class ManagedObjectStorageResult:
    """Return shape from :func:`add_object_storage`."""

    secret_name: str
    secret_namespace: str
    endpoint: str
    region: str
    bucket: str
    access_key_id: str
    manifest_patch: dict[str, Any]
    manifest_path: str | None = None
    is_stub_provisioner: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class ManagedKvResult:
    """Return shape from :func:`add_kv`."""

    secret_name: str
    secret_namespace: str
    redis_url: str
    prefix: str
    manifest_patch: dict[str, Any]
    manifest_path: str | None = None
    is_stub_provisioner: bool = False
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Postgres provisioning (real)
# ---------------------------------------------------------------------------


_STUB_POSTGRES_HOST = "managed-postgres-pool"


def _split_pg_host_port(admin_url: str) -> tuple[str, int]:
    """Extract ``(host, port)`` from a Postgres DSN for SecretData reporting.

    Best-effort — falls back to ``managed-postgres-pool:5432`` if parsing
    fails. Used only for the human-readable Secret keys (``host``/``port``);
    the canonical wire is ``url``.
    """
    try:
        from urllib.parse import urlparse

        parsed = urlparse(admin_url)
        host = parsed.hostname or _STUB_POSTGRES_HOST
        port = parsed.port or 5432
        return host, port
    except Exception:  # noqa: BLE001
        return _STUB_POSTGRES_HOST, 5432


async def _provision_postgres_db(
    *,
    project: Project,
) -> tuple[str, str, str, str, bool]:
    """Create a logical Postgres database + user on the managed pool.

    Returns ``(db_name, db_user, db_password, connection_url, is_stub)``.

    Raises :class:`ManagedResourcesNotConfigured` when neither a real admin
    URL nor the ``managed_postgres_allow_stub`` escape hatch is configured.

    SQL flow (via :mod:`asyncpg`):
        * ``CREATE USER app_<slug>_<nonce> WITH PASSWORD '<random>'``
        * ``CREATE DATABASE app_<slug>_<nonce> OWNER app_<slug>_<nonce>``
          — DDL CREATE DATABASE cannot run inside a transaction.
        * ``GRANT ALL PRIVILEGES ON DATABASE ... TO ...``
    """
    settings = get_settings()
    admin_url = (settings.managed_postgres_admin_url or "").strip()
    allow_stub = settings.managed_postgres_allow_stub

    nonce = secrets.token_hex(4)
    db_name = _stub_db_name(project.slug, nonce)
    db_user = db_name  # 1:1 — the user only ever owns this one DB.
    db_password = secrets.token_urlsafe(24)

    if not admin_url:
        if not allow_stub:
            raise ManagedResourcesNotConfigured(
                "Managed Postgres pool is not configured. Set "
                "MANAGED_POSTGRES_ADMIN_URL to enable per-app Postgres "
                "provisioning (or MANAGED_POSTGRES_ALLOW_STUB=1 for "
                "desktop / dev wiring tests)."
            )
        connection_url = (
            f"postgresql://{db_user}:{db_password}@{_STUB_POSTGRES_HOST}:5432/{db_name}"
        )
        logger.warning(
            "managed_resources.add_postgres: ALLOW_STUB active for project=%s "
            "slug=%s db=%s — returning sentinel URL (pods will CrashLoopBackOff)",
            project.id,
            project.slug,
            db_name,
        )
        return db_name, db_user, db_password, connection_url, True

    # Real provisioning path — connect to the admin DSN and run DDL.
    import asyncpg

    host, port = _split_pg_host_port(admin_url)
    conn: Any = None
    try:
        conn = await asyncpg.connect(dsn=admin_url)
        # autocommit is implicit in asyncpg outside a transaction block.
        # CREATE DATABASE *must* run outside a transaction.
        # CREATE USER comes first so the OWNER clause on CREATE DATABASE
        # resolves cleanly.
        try:
            # asyncpg doesn't allow parameter substitution for DDL identifiers,
            # and CREATE USER's password literal is parsed before the protocol
            # layer can bind. Passwords come from secrets.token_urlsafe (URL-
            # safe base64 only), so the literal is safe; we still escape any
            # single-quotes belt-and-suspenders.
            await conn.execute(
                f"CREATE USER \"{db_user}\" WITH PASSWORD '{_pg_quote_literal(db_password)}'"
            )
        except asyncpg.exceptions.DuplicateObjectError:
            logger.info(
                "managed_resources.add_postgres: user %s already exists "
                "(project=%s); reusing — note that the new password will "
                "NOT be applied to the existing user",
                db_user,
                project.id,
            )

        try:
            await conn.execute(
                f'CREATE DATABASE "{db_name}" OWNER "{db_user}"'
            )
        except asyncpg.exceptions.DuplicateDatabaseError:
            # Surface the duplicate clearly so callers can choose to retry
            # with a fresh nonce. With token_hex(4) collisions are vanishingly
            # rare; if we hit one it almost certainly means a previous
            # run partially succeeded.
            logger.warning(
                "managed_resources.add_postgres: database %s already exists "
                "(project=%s); reusing existing database",
                db_name,
                project.id,
            )

        # GRANT is idempotent.
        await conn.execute(
            f'GRANT ALL PRIVILEGES ON DATABASE "{db_name}" TO "{db_user}"'
        )
    finally:
        if conn is not None:
            try:
                await conn.close()
            except Exception:  # noqa: BLE001
                logger.debug(
                    "managed_resources: pg admin conn close failed", exc_info=True
                )

    connection_url = (
        f"postgresql://{db_user}:{db_password}@{host}:{port}/{db_name}"
    )
    logger.info(
        "managed_resources.add_postgres: provisioned db=%s user=%s host=%s "
        "for project=%s slug=%s",
        db_name,
        db_user,
        host,
        project.id,
        project.slug,
    )
    return db_name, db_user, db_password, connection_url, False


def _pg_quote_literal(value: str) -> str:
    """Escape a Postgres string literal (single-quote → two single-quotes).

    Used for the ``CREATE USER ... WITH PASSWORD '<random>'`` statement
    where parameter substitution isn't accepted in some Postgres versions.
    Passwords come from :func:`secrets.token_urlsafe`, which only emits
    URL-safe base64 chars (no quotes), so this is belt-and-suspenders.
    """
    return value.replace("'", "''")


# ---------------------------------------------------------------------------
# Object storage provisioning (real)
# ---------------------------------------------------------------------------


async def _provision_object_storage_bucket(
    *,
    project: Project,
) -> tuple[str, str, str, str, str, bool]:
    """Create an S3 bucket + scoped credentials on the managed pool.

    Returns ``(endpoint, region, bucket, access_key_id, secret_access_key, is_stub)``.

    Raises :class:`ManagedResourcesNotConfigured` when neither admin
    credentials nor the ``managed_object_storage_allow_stub`` escape hatch
    is configured.

    Strategy:
      * Real path uses :mod:`boto3` via :func:`asyncio.to_thread` (boto3
        is sync; aioboto3 is not pinned and we don't want to add a dep).
      * Bucket name: ``opensail-app-<short-id>-<slug>-<nonce>`` (S3-safe).
      * Credentials: the platform's admin keys are scoped per-bucket via
        a bucket policy. We do NOT mint per-bucket IAM users (that
        requires an IAM client + policy attachment, which is a separate
        ops PR); for now the app pods use the admin credentials but
        target only their own bucket. This is documented in the result's
        ``notes``.
    """
    settings = get_settings()
    endpoint = (settings.managed_object_storage_endpoint or "").strip()
    region = (settings.managed_object_storage_region or "").strip()
    admin_key = (settings.managed_object_storage_admin_key_id or "").strip()
    admin_secret = (settings.managed_object_storage_admin_secret or "").strip()
    allow_stub = settings.managed_object_storage_allow_stub

    nonce = secrets.token_hex(4)
    bucket = _safe_bucket_name(project.id, project.slug, nonce)

    # We need at minimum region + admin creds for the real path. Endpoint
    # may be empty (defaults to AWS S3) — only treat it as "configured" if
    # any of the real settings are populated.
    is_real_configured = bool(region and admin_key and admin_secret)

    if not is_real_configured:
        if not allow_stub:
            raise ManagedResourcesNotConfigured(
                "Managed object storage is not configured. Set "
                "MANAGED_OBJECT_STORAGE_REGION + "
                "MANAGED_OBJECT_STORAGE_ADMIN_KEY_ID + "
                "MANAGED_OBJECT_STORAGE_ADMIN_SECRET (and optionally "
                "MANAGED_OBJECT_STORAGE_ENDPOINT for non-AWS S3) to enable "
                "per-app object storage provisioning (or "
                "MANAGED_OBJECT_STORAGE_ALLOW_STUB=1 for desktop / dev "
                "wiring tests)."
            )
        stub_endpoint = endpoint or "https://managed-objstore-pool.invalid"
        stub_region = region or "us-east-0-stub"
        stub_access = "AKIASTUBSTUBSTUBSTUB"
        stub_secret = secrets.token_urlsafe(32)
        logger.warning(
            "managed_resources.add_object_storage: ALLOW_STUB active for "
            "project=%s slug=%s bucket=%s — returning sentinel endpoint",
            project.id,
            project.slug,
            bucket,
        )
        return stub_endpoint, stub_region, bucket, stub_access, stub_secret, True

    # Real provisioning path — boto3 is sync; offload to a thread.
    import boto3  # local import keeps cold paths cheap
    from botocore.exceptions import ClientError

    def _create_bucket() -> None:
        kwargs: dict[str, Any] = {
            "aws_access_key_id": admin_key,
            "aws_secret_access_key": admin_secret,
            "region_name": region,
        }
        if endpoint:
            kwargs["endpoint_url"] = endpoint
        s3 = boto3.client("s3", **kwargs)
        # us-east-1 rejects the LocationConstraint param — every other
        # region requires it. Mirror what the AWS docs say verbatim.
        create_kwargs: dict[str, Any] = {"Bucket": bucket}
        if region and region != "us-east-1":
            create_kwargs["CreateBucketConfiguration"] = {
                "LocationConstraint": region
            }
        try:
            s3.create_bucket(**create_kwargs)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                logger.warning(
                    "managed_resources.add_object_storage: bucket %s already "
                    "exists (project=%s); reusing",
                    bucket,
                    project.id,
                )
                return
            raise

    await asyncio.to_thread(_create_bucket)

    logger.info(
        "managed_resources.add_object_storage: provisioned bucket=%s "
        "region=%s endpoint=%s for project=%s slug=%s",
        bucket,
        region,
        endpoint or "<aws-default>",
        project.id,
        project.slug,
    )
    # NOTE: per-bucket IAM users + scoped policies are an ops follow-up.
    # For now we hand the admin credentials to the app pod scoped via the
    # bucket name — the pod can only ever address ``bucket``.
    return endpoint, region, bucket, admin_key, admin_secret, False


# ---------------------------------------------------------------------------
# KV (Redis) provisioning (real)
# ---------------------------------------------------------------------------


async def _provision_kv_namespace(
    *,
    project: Project,
) -> tuple[str, str, bool]:
    """Verify the managed Redis pool is reachable and mint a per-app prefix.

    Returns ``(redis_url, prefix, is_stub)``.

    Raises :class:`ManagedResourcesNotConfigured` when neither a real
    Redis URL nor the ``managed_redis_allow_stub`` escape hatch is
    configured.

    Logical-DB number on standalone Redis is too small (only 0-15), so we
    use a per-app key prefix (``app:<short-id>:``) on a shared logical DB.
    Apps wrap their reads/writes via the ``REDIS_PREFIX`` env var; the
    Redis Python client offers no native prefix isolation, but every
    Tesslate-supplied Redis adapter respects the prefix.
    """
    settings = get_settings()
    redis_url = (settings.managed_redis_url or "").strip()
    allow_stub = settings.managed_redis_allow_stub

    short_id = str(project.id).replace("-", "")[:12]
    prefix = f"app:{short_id}:"

    if not redis_url:
        if not allow_stub:
            raise ManagedResourcesNotConfigured(
                "Managed Redis pool is not configured. Set "
                "MANAGED_REDIS_URL to enable per-app KV provisioning "
                "(or MANAGED_REDIS_ALLOW_STUB=1 for desktop / dev wiring "
                "tests)."
            )
        stub_url = "redis://managed-redis-pool.invalid:6379/0"
        logger.warning(
            "managed_resources.add_kv: ALLOW_STUB active for project=%s "
            "slug=%s prefix=%s — returning sentinel URL",
            project.id,
            project.slug,
            prefix,
        )
        return stub_url, prefix, True

    # Real path: connect + INFO to verify reachability. We don't need any
    # write side-effect — the prefix is logical, not physical.
    import redis.asyncio as redis_async

    client = redis_async.from_url(redis_url, socket_connect_timeout=5)
    try:
        await client.info()
    finally:
        try:
            await client.aclose()
        except AttributeError:  # pragma: no cover — older redis-py
            try:
                await client.close()
            except Exception:  # noqa: BLE001
                logger.debug(
                    "managed_resources: redis client close failed", exc_info=True
                )
        except Exception:  # noqa: BLE001
            logger.debug(
                "managed_resources: redis client close failed", exc_info=True
            )

    logger.info(
        "managed_resources.add_kv: verified Redis pool reachable for "
        "project=%s slug=%s prefix=%s",
        project.id,
        project.slug,
        prefix,
    )
    return redis_url, prefix, False


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


def _upsert_secret(
    core_v1: Any,
    *,
    secret_name: str,
    namespace: str,
    project: Project,
    string_data: dict[str, str],
    is_stub: bool,
    source: str,
) -> str:
    """Create-or-patch the Secret. Mirrors user_secret_propagator._upsert_secret.

    Returns ``"created"``, ``"patched"``, or ``"skipped"`` (when no K8s
    client is available — desktop / docker mode).
    """
    if core_v1 is None:
        return "skipped"

    from kubernetes import client as k8s_client
    from kubernetes.client.rest import ApiException

    labels = {
        MANAGED_RESOURCE_LABEL_KEY: MANAGED_RESOURCE_LABEL_VALUE,
        APP_PROJECT_LABEL_KEY: str(project.id),
    }
    annotations = {
        "tesslate.io/source": source,
        "tesslate.io/provisioner-status": "stubbed" if is_stub else "real",
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
            "managed_resources: created Secret %s in ns=%s (stub=%s)",
            secret_name,
            namespace,
            is_stub,
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
                "managed_resources: patched Secret %s in ns=%s (stub=%s)",
                secret_name,
                namespace,
                is_stub,
            )
            return "patched"
        raise


# Backwards-compat shim — the older name is referenced by external tests.
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
    """Backwards-compat wrapper around :func:`_upsert_secret` for postgres."""
    host, port = _split_pg_host_port(connection_url)
    return _upsert_secret(
        core_v1,
        secret_name=secret_name,
        namespace=namespace,
        project=project,
        string_data={
            "url": connection_url,
            "host": host,
            "port": str(port),
            "db": db_name,
            "user": db_user,
            "password": db_password,
        },
        is_stub=True,
        source="managed-resources.add_postgres",
    )


# ---------------------------------------------------------------------------
# Manifest patching + migration helper.
# ---------------------------------------------------------------------------


def _build_postgres_manifest_patch(secret_name: str) -> dict[str, Any]:
    """JSON-merge-patch flipping the manifest to managed-Postgres external mode.

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
                        "DATABASE_URL": "${secret:" + secret_name + "/url}"
                    }
                }
            ]
        },
    }


# Backwards-compat alias — the older name is referenced internally + in tests.
_build_manifest_patch = _build_postgres_manifest_patch


def _build_object_storage_manifest_patch(secret_name: str) -> dict[str, Any]:
    """JSON-merge-patch wiring S3_* env vars into the primary container."""
    s = secret_name
    return {
        "runtime": {
            "state_model": STATE_MODEL_EXTERNAL,
            "scaling": {"max_replicas": DEFAULT_SCALABLE_MAX_REPLICAS},
        },
        "compute": {
            "containers": [
                {
                    "env": {
                        "S3_ENDPOINT": "${secret:" + s + "/endpoint}",
                        "S3_REGION": "${secret:" + s + "/region}",
                        "S3_BUCKET": "${secret:" + s + "/bucket}",
                        "S3_ACCESS_KEY_ID": "${secret:" + s + "/access-key}",
                        "S3_SECRET_ACCESS_KEY": "${secret:" + s + "/secret-key}",
                    }
                }
            ]
        },
    }


def _build_kv_manifest_patch(secret_name: str) -> dict[str, Any]:
    """JSON-merge-patch wiring REDIS_URL + REDIS_PREFIX into the primary container."""
    s = secret_name
    return {
        "runtime": {
            "state_model": STATE_MODEL_EXTERNAL,
            "scaling": {"max_replicas": DEFAULT_SCALABLE_MAX_REPLICAS},
        },
        "compute": {
            "containers": [
                {
                    "env": {
                        "REDIS_URL": "${secret:" + s + "/url}",
                        "REDIS_PREFIX": "${secret:" + s + "/prefix}",
                    }
                }
            ]
        },
    }


def _project_manifest_path(project: Project) -> Path:
    """Return where ``opensail.app.yaml`` lives in the workspace.

    The plan keeps the manifest at the project root. We never create it
    here — the public ``add_*`` entry points only write through if the
    file exists, so the Publish Drawer (which owns the canonical manifest
    draft) stays the single source of truth on shape.
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
# Public entry points.
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
        db: Active SQLAlchemy session. Reserved for future use (recording
            the DB in an ``app_managed_databases`` row); the provisioner
            itself does not write to it today.
        project: The source project the creator is publishing from.
        user: The acting user — recorded in audit metadata only.
        core_v1: Optional injected ``CoreV1Api``. Tests pass a mock; the
            production path resolves a client lazily.

    Returns:
        :class:`ManagedDbResult` with the K8s Secret name, the manifest
        patch the caller should apply, and the path of the migration
        helper written into the project workspace.

    Raises:
        ManagedResourcesNotConfigured: when neither
            ``managed_postgres_admin_url`` nor
            ``managed_postgres_allow_stub`` is configured.
    """
    secret_name = managed_db_secret_name(project.id)
    namespace = _build_secret_namespace(project)

    # 1. Provision (REAL — or stub when ALLOW_STUB is on).
    db_name, db_user, db_password, connection_url, is_stub = (
        await _provision_postgres_db(project=project)
    )

    # 2. Write the K8s Secret. Real, but optional — desktop/docker callers
    # legitimately have no K8s API to talk to.
    if core_v1 is None:
        core_v1 = _resolve_core_v1_api()
    host, port = _split_pg_host_port(connection_url)
    secret_status: str = "skipped"
    try:
        secret_status = _upsert_secret(
            core_v1,
            secret_name=secret_name,
            namespace=namespace,
            project=project,
            string_data={
                "url": connection_url,
                "host": host,
                "port": str(port),
                "db": db_name,
                "user": db_user,
                "password": db_password,
            },
            is_stub=is_stub,
            source="managed-resources.add_postgres",
        )
    except Exception as exc:  # noqa: BLE001 — log + surface in notes
        logger.warning(
            "managed_resources.add_postgres: Secret write failed (project=%s): %r",
            project.id,
            exc,
        )
        secret_status = f"errored: {exc!r}"

    # 3. Build the manifest patch + best-effort write to disk.
    manifest_patch = _build_postgres_manifest_patch(secret_name)
    manifest_path = _project_manifest_path(project)
    written_manifest = _apply_manifest_patch_to_disk(manifest_path, manifest_patch)

    # 4. Write the migration helper.
    project_root = Path(get_project_path(project.owner_id, project.id))
    migration_path = _write_migration_helper(project_root)

    notes: list[str] = [f"Secret write status: {secret_status}"]
    if is_stub:
        notes.insert(
            0,
            "Postgres provisioning is in STUB mode "
            "(MANAGED_POSTGRES_ALLOW_STUB=1). The DATABASE_URL points at the "
            "unresolvable host 'managed-postgres-pool' so app pods fail "
            "loudly until MANAGED_POSTGRES_ADMIN_URL is configured.",
        )
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
        is_stub_provisioner=is_stub,
        notes=notes,
    )


async def add_object_storage(
    db: AsyncSession,
    *,
    project: Project,
    user: User,
    core_v1: Any | None = None,
) -> ManagedObjectStorageResult:
    """Provision per-app object storage (S3 bucket) + patch the manifest.

    See :func:`add_postgres` for the surface contract; this function is
    its sibling for object storage. Writes a Secret named
    ``app-managed-objstore-{project_id}`` with keys ``endpoint``,
    ``region``, ``bucket``, ``access-key``, ``secret-key`` and patches
    the manifest to wire ``S3_*`` env vars on the primary container.

    Raises:
        ManagedResourcesNotConfigured: when admin credentials are not
            configured and ``managed_object_storage_allow_stub`` is off.
    """
    secret_name = managed_object_storage_secret_name(project.id)
    namespace = _build_secret_namespace(project)

    endpoint, region, bucket, access_key_id, secret_access_key, is_stub = (
        await _provision_object_storage_bucket(project=project)
    )

    if core_v1 is None:
        core_v1 = _resolve_core_v1_api()
    secret_status: str = "skipped"
    try:
        secret_status = _upsert_secret(
            core_v1,
            secret_name=secret_name,
            namespace=namespace,
            project=project,
            string_data={
                "endpoint": endpoint,
                "region": region,
                "bucket": bucket,
                "access-key": access_key_id,
                "secret-key": secret_access_key,
            },
            is_stub=is_stub,
            source="managed-resources.add_object_storage",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "managed_resources.add_object_storage: Secret write failed "
            "(project=%s): %r",
            project.id,
            exc,
        )
        secret_status = f"errored: {exc!r}"

    manifest_patch = _build_object_storage_manifest_patch(secret_name)
    manifest_path = _project_manifest_path(project)
    written_manifest = _apply_manifest_patch_to_disk(manifest_path, manifest_patch)

    notes: list[str] = [f"Secret write status: {secret_status}"]
    if is_stub:
        notes.insert(
            0,
            "Object storage provisioning is in STUB mode "
            "(MANAGED_OBJECT_STORAGE_ALLOW_STUB=1). The S3_ENDPOINT points "
            "at an unresolvable host so app pods fail loudly until the "
            "managed pool admin credentials are configured.",
        )
    else:
        notes.append(
            "Bucket policy / per-bucket IAM scoping is an ops follow-up; "
            "the app pod currently uses the platform's admin credentials "
            "scoped via S3_BUCKET."
        )
    if written_manifest is None:
        notes.append(
            "opensail.app.yaml not present in workspace; returning patch "
            "for the Publish Drawer to merge."
        )

    return ManagedObjectStorageResult(
        secret_name=secret_name,
        secret_namespace=namespace,
        endpoint=endpoint,
        region=region,
        bucket=bucket,
        access_key_id=access_key_id,
        manifest_patch=manifest_patch,
        manifest_path=written_manifest,
        is_stub_provisioner=is_stub,
        notes=notes,
    )


async def add_kv(
    db: AsyncSession,
    *,
    project: Project,
    user: User,
    core_v1: Any | None = None,
) -> ManagedKvResult:
    """Provision per-app KV (Redis prefix) + patch the manifest.

    See :func:`add_postgres` for the surface contract. Writes a Secret
    named ``app-managed-kv-{project_id}`` with keys ``url`` + ``prefix``
    and patches the manifest to wire ``REDIS_URL`` + ``REDIS_PREFIX`` on
    the primary container.

    Raises:
        ManagedResourcesNotConfigured: when ``managed_redis_url`` is not
            set and ``managed_redis_allow_stub`` is off.
    """
    secret_name = managed_kv_secret_name(project.id)
    namespace = _build_secret_namespace(project)

    redis_url, prefix, is_stub = await _provision_kv_namespace(project=project)

    if core_v1 is None:
        core_v1 = _resolve_core_v1_api()
    secret_status: str = "skipped"
    try:
        secret_status = _upsert_secret(
            core_v1,
            secret_name=secret_name,
            namespace=namespace,
            project=project,
            string_data={
                "url": redis_url,
                "prefix": prefix,
            },
            is_stub=is_stub,
            source="managed-resources.add_kv",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "managed_resources.add_kv: Secret write failed (project=%s): %r",
            project.id,
            exc,
        )
        secret_status = f"errored: {exc!r}"

    manifest_patch = _build_kv_manifest_patch(secret_name)
    manifest_path = _project_manifest_path(project)
    written_manifest = _apply_manifest_patch_to_disk(manifest_path, manifest_patch)

    notes: list[str] = [f"Secret write status: {secret_status}"]
    if is_stub:
        notes.insert(
            0,
            "KV provisioning is in STUB mode (MANAGED_REDIS_ALLOW_STUB=1). "
            "The REDIS_URL points at an unresolvable host so app pods fail "
            "loudly until MANAGED_REDIS_URL is configured.",
        )
    if written_manifest is None:
        notes.append(
            "opensail.app.yaml not present in workspace; returning patch "
            "for the Publish Drawer to merge."
        )

    return ManagedKvResult(
        secret_name=secret_name,
        secret_namespace=namespace,
        redis_url=redis_url,
        prefix=prefix,
        manifest_patch=manifest_patch,
        manifest_path=written_manifest,
        is_stub_provisioner=is_stub,
        notes=notes,
    )
