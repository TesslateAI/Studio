"""Workspace Data Store — HTTP API.

Two surfaces, two routers:

* ``mgmt_router`` — Management API (``/api/workspace-data/projects/{slug}/…``).
  JWT-authed + project-RBAC'd. Powers the Data tab: collections, record
  browsing, API-key management, usage.
* ``data_router`` — Public Data API (``/api/data/v1/{collection}/…``).
  Authenticated by a per-project ``WorkspaceDataKey`` (anon or service).
  This is what deployed frontends (Vercel/Cloudflare) and external callers
  use. CORS for ``/api/data/`` is opened wildcard in ``main.py``; CSRF is
  auto-skipped for Bearer-authed requests.
"""

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_db
from ..models import User
from ..models_workspace_data import WorkspaceCollection, WorkspaceDataKey
from ..permissions import Permission, get_project_with_access
from ..schemas_workspace_data import (
    CollectionCreate,
    CollectionResponse,
    CollectionUpdate,
    DataKeyCreate,
    DataKeyResponse,
    RecordListResponse,
    RecordResponse,
    UsageResponse,
)
from ..services import workspace_data as wd
from ..services.audit_service import log_event as audit_log_event
from ..services.rate_limit import get_token_bucket
from ..users import current_active_user

logger = logging.getLogger(__name__)

# Bumped only when we change the public Data API in a way that requires
# client coordination (response shape, auth header semantics, etc.). Stamped
# on every Data API response by the DynamicCORSMiddleware in main.py so
# deployed apps can hard-fail on a version mismatch — even on error
# responses (401/404/429) where router-level dependencies don't run.
# NEVER bump for additive, backward-compatible changes.
DATA_API_VERSION = "1"


mgmt_router = APIRouter(prefix="/api/workspace-data", tags=["workspace-data"])
data_router = APIRouter(prefix="/api/data/v1", tags=["workspace-data-api"])


async def _audit(
    db: AsyncSession,
    request: Request,
    project,
    user: User,
    action: str,
    *,
    resource_id=None,
    details: dict | None = None,
) -> None:
    """Thin wrapper that fills in the workspace-data-specific defaults.

    Opens a FRESH session for the write so the row survives the request's
    own session-teardown (``get_db`` doesn't commit on exit, so a write on
    the request session gets silently rolled back — mirrors the
    ``rate_limit.py`` audit pattern). Failure NEVER blocks the primary
    operation — ``log_event`` already swallows its own exceptions.

    ``team_id`` is required by the AuditLog row; pull it off the project
    (every project belongs to exactly one team).
    """
    team_id = getattr(project, "team_id", None)
    if team_id is None:  # defensive — shouldn't happen for a fetched project
        return
    try:
        from ..database import AsyncSessionLocal

        async with AsyncSessionLocal() as audit_db:
            await audit_log_event(
                db=audit_db,
                team_id=team_id,
                user_id=user.id,
                action=action,
                resource_type="workspace_data",
                resource_id=resource_id,
                project_id=project.id,
                details=details or {},
                request=request,
            )
            await audit_db.commit()
    except Exception:
        # Never block the primary operation on an audit failure. We log
        # at debug so a flaky DB doesn't spam ERROR; log_event already
        # logs its own exceptions at exception level.
        logger.debug("audit write failed for action=%s (non-blocking)", action, exc_info=True)


# Map store/key errors to HTTP status codes (most-specific first).
_ERROR_STATUS: list[tuple[type, int]] = [
    (wd.InvalidNameError, 400),
    (wd.InvalidRecordError, 400),
    (wd.InvalidKeyError, 400),
    (wd.CollectionExistsError, 409),
    (wd.CollectionNotFoundError, 404),
    (wd.RecordNotFoundError, 404),
    (wd.QuotaExceededError, 429),
]


def _http_error(exc: wd.WorkspaceDataError) -> HTTPException:
    """Translate a store error into the right HTTPException."""
    for cls, status in _ERROR_STATUS:
        if isinstance(exc, cls):
            return HTTPException(status_code=status, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


def _require_uuid(ref: str, kind: str) -> str:
    """Reject a destructive-route ref that isn't a UUID.

    The store's name-or-UUID fallback is convenient on read paths but a
    footgun on DELETE — a typo'd name becomes a silent wrong-object delete
    if the project happens to have a collection by that name. Destructive
    mgmt routes (delete collection, delete record) require the canonical
    UUID; the studio UI already passes ``collection.id`` and ``record.id``.
    """
    from uuid import UUID

    try:
        UUID(str(ref))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(
            status_code=400,
            detail=f"{kind}_id must be a UUID. Look it up first if you only have the name.",
        ) from None
    return ref


def _collection_response(c: WorkspaceCollection, record_count: int) -> CollectionResponse:
    return CollectionResponse(
        id=c.id,
        project_id=c.project_id,
        name=c.name,
        public_insert=c.public_insert,
        public_read=c.public_read,
        public_update=c.public_update,
        public_delete=c.public_delete,
        record_count=record_count,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


def _record_response(r) -> RecordResponse:
    return RecordResponse(
        id=r.id,
        collection_id=r.collection_id,
        data=r.data or {},
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


def _key_response(k: WorkspaceDataKey, raw: str | None = None) -> DataKeyResponse:
    return DataKeyResponse(
        id=k.id,
        project_id=k.project_id,
        name=k.name,
        kind=k.kind,
        key_prefix=k.key_prefix,
        is_active=k.is_active,
        last_used_at=k.last_used_at,
        created_at=k.created_at,
        key=raw,
    )


# ============================================================================
# Management API — JWT auth + project RBAC
# ============================================================================
@mgmt_router.get("/projects/{project_slug}/collections", response_model=list[CollectionResponse])
async def list_collections(
    project_slug: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List all data collections in a project (single GROUP BY for counts)."""
    project, _ = await get_project_with_access(db, project_slug, user.id, Permission.PROJECT_VIEW)
    collections = await wd.list_collections(db, project.id)
    # One query for every collection's record count instead of N. At
    # MAX_COLLECTIONS_PER_PROJECT=50 that's 51 → 2 DB roundtrips per page load.
    counts = await wd.collection_record_counts(db, project.id)
    return [_collection_response(c, counts.get(c.id, 0)) for c in collections]


@mgmt_router.post(
    "/projects/{project_slug}/collections",
    response_model=CollectionResponse,
    status_code=201,
)
async def create_collection(
    project_slug: str,
    payload: CollectionCreate,
    request: Request,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new data collection."""
    project, _ = await get_project_with_access(db, project_slug, user.id, Permission.PROJECT_EDIT)
    try:
        collection = await wd.create_collection(
            db,
            project.id,
            payload.name,
            public_insert=payload.public_insert,
            public_read=payload.public_read,
            public_update=payload.public_update,
            public_delete=payload.public_delete,
        )
    except wd.WorkspaceDataError as exc:
        raise _http_error(exc) from exc
    await _audit(
        db,
        request,
        project,
        user,
        "workspace_data.collection.create",
        resource_id=collection.id,
        details={
            "name": collection.name,
            "public_insert": collection.public_insert,
            "public_read": collection.public_read,
            "public_update": collection.public_update,
            "public_delete": collection.public_delete,
        },
    )
    return _collection_response(collection, 0)


@mgmt_router.patch(
    "/projects/{project_slug}/collections/{collection_id}",
    response_model=CollectionResponse,
)
async def update_collection(
    project_slug: str,
    collection_id: str,
    payload: CollectionUpdate,
    request: Request,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a collection's public access flags."""
    project, _ = await get_project_with_access(db, project_slug, user.id, Permission.PROJECT_EDIT)
    try:
        collection = await wd.require_collection(db, project.id, collection_id)
        # Capture before-state so the audit row records the actual diff.
        before = {
            f: getattr(collection, f)
            for f in ("public_insert", "public_read", "public_update", "public_delete")
        }
        collection = await wd.update_collection(
            db, collection, **payload.model_dump(exclude_unset=True)
        )
    except wd.WorkspaceDataError as exc:
        raise _http_error(exc) from exc
    after = {
        f: getattr(collection, f)
        for f in ("public_insert", "public_read", "public_update", "public_delete")
    }
    changed = {k: {"from": before[k], "to": after[k]} for k in after if before[k] != after[k]}
    if changed:
        await _audit(
            db,
            request,
            project,
            user,
            "workspace_data.collection.flags_changed",
            resource_id=collection.id,
            details={"name": collection.name, "changed": changed},
        )
    count = await wd.collection_record_count(db, collection.id)
    return _collection_response(collection, count)


@mgmt_router.delete("/projects/{project_slug}/collections/{collection_id}", status_code=204)
async def delete_collection(
    project_slug: str,
    collection_id: str,
    request: Request,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a collection and all of its records (UUID-only)."""
    project, _ = await get_project_with_access(db, project_slug, user.id, Permission.PROJECT_EDIT)
    collection_id = _require_uuid(collection_id, "collection")
    try:
        collection = await wd.require_collection(db, project.id, collection_id)
    except wd.WorkspaceDataError as exc:
        raise _http_error(exc) from exc
    # High-blast-radius: cascades to every record + every external consumer.
    record_count = await wd.collection_record_count(db, collection.id)
    name = collection.name
    await wd.delete_collection(db, collection)
    await _audit(
        db,
        request,
        project,
        user,
        "workspace_data.collection.delete",
        resource_id=collection.id,
        details={"name": name, "deleted_record_count": record_count},
    )


@mgmt_router.get(
    "/projects/{project_slug}/collections/{collection_id}/records",
    response_model=RecordListResponse,
)
async def list_records(
    project_slug: str,
    collection_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Browse records in a collection (newest first, paginated)."""
    project, _ = await get_project_with_access(db, project_slug, user.id, Permission.PROJECT_VIEW)
    try:
        collection = await wd.require_collection(db, project.id, collection_id)
    except wd.WorkspaceDataError as exc:
        raise _http_error(exc) from exc
    records, total = await wd.list_records(db, collection.id, limit=limit, offset=offset)
    return RecordListResponse(
        records=[_record_response(r) for r in records],
        total=total,
        limit=limit,
        offset=offset,
    )


@mgmt_router.delete(
    "/projects/{project_slug}/collections/{collection_id}/records/{record_id}",
    status_code=204,
)
async def delete_record(
    project_slug: str,
    collection_id: str,
    record_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a single record (UUID-only on both path params)."""
    project, _ = await get_project_with_access(db, project_slug, user.id, Permission.PROJECT_EDIT)
    collection_id = _require_uuid(collection_id, "collection")
    record_id = _require_uuid(record_id, "record")
    try:
        collection = await wd.require_collection(db, project.id, collection_id)
        record = await wd.require_record(db, collection.id, record_id)
    except wd.WorkspaceDataError as exc:
        raise _http_error(exc) from exc
    await wd.delete_record(db, record)


@mgmt_router.get("/projects/{project_slug}/usage", response_model=UsageResponse)
async def get_usage(
    project_slug: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Per-project data-store usage against quota."""
    project, _ = await get_project_with_access(db, project_slug, user.id, Permission.PROJECT_VIEW)
    collections = await wd.list_collections(db, project.id)
    record_count = await wd.project_record_count(db, project.id)
    return UsageResponse(
        collection_count=len(collections),
        record_count=record_count,
        max_collections=wd.MAX_COLLECTIONS_PER_PROJECT,
        max_records=wd.MAX_RECORDS_PER_PROJECT,
        max_record_bytes=wd.MAX_RECORD_BYTES,
    )


# --- API keys ---------------------------------------------------------------
@mgmt_router.get("/projects/{project_slug}/keys", response_model=list[DataKeyResponse])
async def list_keys(
    project_slug: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List a project's Data API keys (prefixes only — secrets never returned)."""
    project, _ = await get_project_with_access(db, project_slug, user.id, Permission.PROJECT_VIEW)
    keys = await wd.list_data_keys(db, project.id)
    return [_key_response(k) for k in keys]


@mgmt_router.post("/projects/{project_slug}/keys", response_model=DataKeyResponse, status_code=201)
async def create_key(
    project_slug: str,
    payload: DataKeyCreate,
    request: Request,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Mint a new Data API key. The raw secret is returned exactly once."""
    project, _ = await get_project_with_access(db, project_slug, user.id, Permission.PROJECT_EDIT)
    try:
        key, raw = await wd.create_data_key(
            db, project.id, payload.name, payload.kind, created_by_id=user.id
        )
    except wd.WorkspaceDataError as exc:
        raise _http_error(exc) from exc
    # Most security-relevant op in this subsystem — audit on every mint.
    # Raw secret is NEVER persisted (only the SHA-256 hash); record the
    # non-secret prefix so post-incident teams can correlate with logs.
    await _audit(
        db,
        request,
        project,
        user,
        "workspace_data.key.create",
        resource_id=key.id,
        details={"name": key.name, "kind": key.kind, "key_prefix": key.key_prefix},
    )
    return _key_response(key, raw=raw)


@mgmt_router.delete("/projects/{project_slug}/keys/{key_id}", status_code=204)
async def revoke_key(
    project_slug: str,
    key_id: str,
    request: Request,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke (soft-delete) a Data API key."""
    project, _ = await get_project_with_access(db, project_slug, user.id, Permission.PROJECT_EDIT)
    # Look up the key BEFORE revoke so the audit row records what it was.
    key_row = await wd.get_data_key(db, project.id, key_id)
    if not await wd.revoke_data_key(db, project.id, key_id):
        raise HTTPException(status_code=404, detail="API key not found.")
    await _audit(
        db,
        request,
        project,
        user,
        "workspace_data.key.revoke",
        resource_id=key_row.id if key_row else None,
        details={
            "name": key_row.name if key_row else None,
            "kind": key_row.kind if key_row else None,
            "key_prefix": key_row.key_prefix if key_row else None,
        },
    )


# ============================================================================
# Public Data API — per-project key auth + tiered rate limiting
# ============================================================================
_data_key_header = APIKeyHeader(name="Authorization", auto_error=False)


def _client_ip(request: Request) -> str:
    """Best-effort client IP, trusting the proxy headers middleware.

    The orchestrator runs behind NGINX Ingress (k8s) / Traefik (docker);
    ``ProxyHeadersMiddleware`` already rewrites ``request.client.host`` to the
    real client. Falls back to a sentinel so the bucket key is never empty
    (Starlette can drop ``client`` on test/transport corner cases).
    """
    client = request.client
    return client.host if client and client.host else "unknown"


def _rate_limit_headers(remaining: int, reset: int, capacity: int) -> dict[str, str]:
    return {
        "Retry-After": str(reset),
        "X-RateLimit-Limit": str(capacity),
        "X-RateLimit-Remaining": str(max(0, remaining)),
        "X-RateLimit-Reset": str(reset),
    }


async def authenticate_data_key(
    request: Request,
    authorization: str | None = Security(_data_key_header),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceDataKey:
    """Resolve + validate a ``WorkspaceDataKey`` with tiered rate limiting.

    Two buckets run in order so attackers without a valid key never reach the
    auth DB lookup, and a leaked anon key can't take out an entire project:

    1. **Per-IP** (``wsdata:ip``): fires *before* the DB hit. Catches bad-key
       spammers, OPTIONS-free amplification, and bot loops.
    2. **Per-key** (``wsdata:key``): fires after a successful lookup. Stricter
       than per-IP so a single leaked anon key can't burn the whole budget.

    Both buckets are Redis-backed (``RedisTokenBucket``) with in-process
    fallback when Redis is down. Limits live in ``Settings`` so per-env tuning
    is one env var away.
    """
    settings = get_settings()
    bucket = get_token_bucket()

    # 1. Per-IP throttle — no auth, no DB hit. Always runs.
    ip = _client_ip(request)
    allowed, remaining, reset = await bucket.check_and_consume(
        "wsdata:ip",
        ip,
        capacity=settings.wsdata_api_per_ip_capacity,
        window_seconds=settings.wsdata_api_per_ip_window_seconds,
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Try again shortly.",
            headers=_rate_limit_headers(remaining, reset, settings.wsdata_api_per_ip_capacity),
        )

    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Missing API key. Pass 'Authorization: Bearer <key>'.",
        )
    raw = authorization[7:] if authorization.startswith("Bearer ") else authorization
    key = await wd.resolve_data_key(db, raw)
    if key is None:
        raise HTTPException(status_code=401, detail="Invalid API key.")

    # 2. Per-key throttle — stricter, scoped to the resolved key.
    allowed, remaining, reset = await bucket.check_and_consume(
        "wsdata:key",
        str(key.id),
        capacity=settings.wsdata_api_per_key_capacity,
        window_seconds=settings.wsdata_api_per_key_window_seconds,
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded for this API key. Try again shortly.",
            headers=_rate_limit_headers(remaining, reset, settings.wsdata_api_per_key_capacity),
        )

    return key


# Opaque "missing-or-closed" response. Anon keys must not be able to use the
# 404-vs-403 distinction to enumerate which collections exist in a project.
# Service keys (which have full project access) get the same canonical 404
# only when the collection truly does not exist — they have no public_* flags
# to fail against, so _enforce short-circuits and they never see this code path.
_DATA_API_NOT_FOUND = "Collection not found or not accessible to this key."


def _enforce(key: WorkspaceDataKey, collection: WorkspaceCollection, op: str) -> None:
    """Gate an operation: service keys bypass; anon keys obey collection flags.

    A closed-flag rejection is returned as a 404 with the same opaque detail
    as ``_resolve_collection``'s real 404 — so an anon-key holder cannot
    distinguish "collection does not exist" from "exists but op disallowed".
    """
    if key.kind == "service":
        return
    if not getattr(collection, f"public_{op}", False):
        raise HTTPException(status_code=404, detail=_DATA_API_NOT_FOUND)


async def _resolve_collection(db: AsyncSession, project_id, ref: str) -> WorkspaceCollection:
    collection = await wd.get_collection(db, project_id, ref)
    if collection is None:
        raise HTTPException(status_code=404, detail=_DATA_API_NOT_FOUND)
    return collection


@data_router.post("/{collection}", response_model=RecordResponse, status_code=201)
async def data_insert(
    collection: str,
    payload: dict[str, Any] = Body(...),
    key: WorkspaceDataKey = Depends(authenticate_data_key),
    db: AsyncSession = Depends(get_db),
):
    """Insert a JSON document into a collection."""
    coll = await _resolve_collection(db, key.project_id, collection)
    _enforce(key, coll, "insert")
    try:
        record = await wd.insert_record(db, coll, payload)
    except wd.WorkspaceDataError as exc:
        raise _http_error(exc) from exc
    return _record_response(record)


@data_router.get("/{collection}", response_model=RecordListResponse)
async def data_list(
    collection: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    key: WorkspaceDataKey = Depends(authenticate_data_key),
    db: AsyncSession = Depends(get_db),
):
    """List records in a collection (newest first, paginated)."""
    coll = await _resolve_collection(db, key.project_id, collection)
    _enforce(key, coll, "read")
    records, total = await wd.list_records(db, coll.id, limit=limit, offset=offset)
    return RecordListResponse(
        records=[_record_response(r) for r in records],
        total=total,
        limit=limit,
        offset=offset,
    )


@data_router.get("/{collection}/{record_id}", response_model=RecordResponse)
async def data_get(
    collection: str,
    record_id: str,
    key: WorkspaceDataKey = Depends(authenticate_data_key),
    db: AsyncSession = Depends(get_db),
):
    """Fetch one record by id."""
    coll = await _resolve_collection(db, key.project_id, collection)
    _enforce(key, coll, "read")
    record = await wd.get_record(db, coll.id, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Record not found.")
    return _record_response(record)


@data_router.patch("/{collection}/{record_id}", response_model=RecordResponse)
async def data_update(
    collection: str,
    record_id: str,
    payload: dict[str, Any] = Body(...),
    key: WorkspaceDataKey = Depends(authenticate_data_key),
    db: AsyncSession = Depends(get_db),
):
    """Replace a record's JSON document."""
    coll = await _resolve_collection(db, key.project_id, collection)
    _enforce(key, coll, "update")
    record = await wd.get_record(db, coll.id, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Record not found.")
    try:
        record = await wd.update_record(db, record, payload)
    except wd.WorkspaceDataError as exc:
        raise _http_error(exc) from exc
    return _record_response(record)


@data_router.delete("/{collection}/{record_id}", status_code=204)
async def data_delete(
    collection: str,
    record_id: str,
    key: WorkspaceDataKey = Depends(authenticate_data_key),
    db: AsyncSession = Depends(get_db),
):
    """Delete a single record."""
    coll = await _resolve_collection(db, key.project_id, collection)
    _enforce(key, coll, "delete")
    record = await wd.get_record(db, coll.id, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Record not found.")
    await wd.delete_record(db, record)


# ============================================================================
# REST-style path aliases — `/collections/{c}/records[/{id}]`
#
# LLM-generated client code defaults to this REST CRUD shape from training
# data. Rather than fight that, we accept both URL styles so generated apps
# just work. The handlers delegate to the canonical functions above — no
# duplicated logic.
# ============================================================================
@data_router.post(
    "/collections/{collection}/records", response_model=RecordResponse, status_code=201
)
async def data_insert_rest(
    collection: str,
    payload: dict[str, Any] = Body(...),
    key: WorkspaceDataKey = Depends(authenticate_data_key),
    db: AsyncSession = Depends(get_db),
):
    return await data_insert(collection, payload, key, db)


@data_router.get("/collections/{collection}/records", response_model=RecordListResponse)
async def data_list_rest(
    collection: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    key: WorkspaceDataKey = Depends(authenticate_data_key),
    db: AsyncSession = Depends(get_db),
):
    return await data_list(collection, limit, offset, key, db)


@data_router.get("/collections/{collection}/records/{record_id}", response_model=RecordResponse)
async def data_get_rest(
    collection: str,
    record_id: str,
    key: WorkspaceDataKey = Depends(authenticate_data_key),
    db: AsyncSession = Depends(get_db),
):
    return await data_get(collection, record_id, key, db)


@data_router.patch("/collections/{collection}/records/{record_id}", response_model=RecordResponse)
async def data_update_rest(
    collection: str,
    record_id: str,
    payload: dict[str, Any] = Body(...),
    key: WorkspaceDataKey = Depends(authenticate_data_key),
    db: AsyncSession = Depends(get_db),
):
    return await data_update(collection, record_id, payload, key, db)


@data_router.delete("/collections/{collection}/records/{record_id}", status_code=204)
async def data_delete_rest(
    collection: str,
    record_id: str,
    key: WorkspaceDataKey = Depends(authenticate_data_key),
    db: AsyncSession = Depends(get_db),
):
    return await data_delete(collection, record_id, key, db)
