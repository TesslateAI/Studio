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

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

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
from ..users import current_active_user

logger = logging.getLogger(__name__)

mgmt_router = APIRouter(prefix="/api/workspace-data", tags=["workspace-data"])
data_router = APIRouter(prefix="/api/data/v1", tags=["workspace-data-api"])

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
    """List all data collections in a project."""
    project, _ = await get_project_with_access(db, project_slug, user.id, Permission.PROJECT_VIEW)
    collections = await wd.list_collections(db, project.id)
    return [
        _collection_response(c, await wd.collection_record_count(db, c.id)) for c in collections
    ]


@mgmt_router.post(
    "/projects/{project_slug}/collections",
    response_model=CollectionResponse,
    status_code=201,
)
async def create_collection(
    project_slug: str,
    payload: CollectionCreate,
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
    return _collection_response(collection, 0)


@mgmt_router.patch(
    "/projects/{project_slug}/collections/{collection_id}",
    response_model=CollectionResponse,
)
async def update_collection(
    project_slug: str,
    collection_id: str,
    payload: CollectionUpdate,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a collection's public access flags."""
    project, _ = await get_project_with_access(db, project_slug, user.id, Permission.PROJECT_EDIT)
    try:
        collection = await wd.require_collection(db, project.id, collection_id)
        collection = await wd.update_collection(
            db, collection, **payload.model_dump(exclude_unset=True)
        )
    except wd.WorkspaceDataError as exc:
        raise _http_error(exc) from exc
    count = await wd.collection_record_count(db, collection.id)
    return _collection_response(collection, count)


@mgmt_router.delete("/projects/{project_slug}/collections/{collection_id}", status_code=204)
async def delete_collection(
    project_slug: str,
    collection_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a collection and all of its records."""
    project, _ = await get_project_with_access(db, project_slug, user.id, Permission.PROJECT_EDIT)
    try:
        collection = await wd.require_collection(db, project.id, collection_id)
    except wd.WorkspaceDataError as exc:
        raise _http_error(exc) from exc
    await wd.delete_collection(db, collection)


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
    """Delete a single record."""
    project, _ = await get_project_with_access(db, project_slug, user.id, Permission.PROJECT_EDIT)
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
    return _key_response(key, raw=raw)


@mgmt_router.delete("/projects/{project_slug}/keys/{key_id}", status_code=204)
async def revoke_key(
    project_slug: str,
    key_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke (delete) a Data API key."""
    project, _ = await get_project_with_access(db, project_slug, user.id, Permission.PROJECT_EDIT)
    if not await wd.revoke_data_key(db, project.id, key_id):
        raise HTTPException(status_code=404, detail="API key not found.")


# ============================================================================
# Public Data API — per-project key auth
# ============================================================================
_data_key_header = APIKeyHeader(name="Authorization", auto_error=False)


async def authenticate_data_key(
    authorization: str | None = Security(_data_key_header),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceDataKey:
    """Resolve and validate a ``WorkspaceDataKey`` from the Bearer header."""
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Missing API key. Pass 'Authorization: Bearer <key>'.",
        )
    raw = authorization[7:] if authorization.startswith("Bearer ") else authorization
    key = await wd.resolve_data_key(db, raw)
    if key is None:
        raise HTTPException(status_code=401, detail="Invalid API key.")
    return key


def _enforce(key: WorkspaceDataKey, collection: WorkspaceCollection, op: str) -> None:
    """Gate an operation: service keys bypass; anon keys obey collection flags."""
    if key.kind == "service":
        return
    if not getattr(collection, f"public_{op}", False):
        raise HTTPException(
            status_code=403,
            detail=f"Collection '{collection.name}' does not allow public {op}.",
        )


async def _resolve_collection(db: AsyncSession, project_id, ref: str) -> WorkspaceCollection:
    collection = await wd.get_collection(db, project_id, ref)
    if collection is None:
        raise HTTPException(status_code=404, detail=f"Collection '{ref}' not found.")
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
