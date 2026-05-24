"""Workspace Data Store — collection + record CRUD.

Pure data-access layer over the ``WorkspaceCollection`` / ``WorkspaceRecord``
models. Used by *both* the HTTP routers and the agent tool, so every access
rule, validation check and quota lives here in exactly one place.

All functions are dialect-agnostic (Postgres + desktop SQLite).
"""

import json
import re
from uuid import UUID

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...models_workspace_data import WorkspaceCollection, WorkspaceRecord

# --- Limits -----------------------------------------------------------------
# v1 module constants. Named + centralised so they can be promoted to
# Settings (per-env / per-tier tuning) without touching call sites.
MAX_COLLECTIONS_PER_PROJECT = 50
MAX_RECORDS_PER_PROJECT = 10_000
MAX_RECORD_BYTES = 64 * 1024
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

# Per-record structural limits. These bound the work that downstream
# helpers (infer_schema, _hashable, JSON encode) do on a single document.
# Without them a 64 KB record can still hold pathological structures —
# 5 K one-char keys, or 1 K-deep nesting that crashes ``json.dumps`` with
# a RecursionError before ever hitting the byte cap.
MAX_RECORD_TOP_LEVEL_KEYS = 256
MAX_RECORD_NESTING_DEPTH = 32

_COLLECTION_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")

# Names reserved by the Data API's route layout — a collection named
# ``collections`` would alias the REST-style ``/api/data/v1/collections/{c}/records``
# prefix and become unaddressable through the canonical ``/{collection}`` shape.
# Existing rows are left untouched; only NEW creates are blocked.
RESERVED_COLLECTION_NAMES: frozenset[str] = frozenset({"collections"})


# --- Errors -----------------------------------------------------------------
class WorkspaceDataError(Exception):
    """Base class for workspace-data store errors."""


class CollectionNotFoundError(WorkspaceDataError):
    """The named/identified collection does not exist in this project."""


class CollectionExistsError(WorkspaceDataError):
    """A collection with this name already exists in the project."""


class RecordNotFoundError(WorkspaceDataError):
    """The identified record does not exist in this collection."""


class InvalidNameError(WorkspaceDataError):
    """Collection name failed validation."""


class InvalidRecordError(WorkspaceDataError):
    """Record payload is not a valid / sized JSON object."""


class QuotaExceededError(WorkspaceDataError):
    """A per-project collection or record limit has been reached."""


# --- Validation helpers -----------------------------------------------------
def _maybe_uuid(value: object) -> UUID | None:
    """Best-effort coerce a value to UUID; ``None`` if it is not one."""
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def validate_collection_name(name: str) -> str:
    """Normalise + validate a collection name, or raise ``InvalidNameError``."""
    cleaned = (name or "").strip()
    if not _COLLECTION_NAME_RE.match(cleaned):
        raise InvalidNameError(
            "Collection name must be 1-64 characters, start with a letter or "
            "digit, and contain only letters, digits, '-' and '_'."
        )
    if cleaned.lower() in RESERVED_COLLECTION_NAMES:
        raise InvalidNameError(
            f"Collection name '{cleaned}' is reserved by the Data API route "
            "layout and would conflict with the REST-style /collections/* prefix."
        )
    return cleaned


def _check_structure(value: object, depth: int = 0) -> None:
    """Walk a JSON value, rejecting unsafe structure.

    Three guards, all O(n) over reachable nodes:
      * **Depth cap** — prevents the C ``json`` encoder's RecursionError
        on pathological nesting and ``_hashable``'s same-shape recursion
        in the aggregate helpers. Raises before any work.
      * **NUL byte / lone surrogate scrub** — Postgres ``text`` rejects
        ``\\u0000`` mid-INSERT (turns into a 500); lone surrogates aren't
        UTF-8 encodable. Catch them at the API boundary as 400, not 500.
      * **Top-level key cap** — only enforced at depth 0 by the caller.
    """
    if depth > MAX_RECORD_NESTING_DEPTH:
        raise InvalidRecordError(
            f"Record nesting exceeds the {MAX_RECORD_NESTING_DEPTH}-level limit."
        )
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(k, str) and ("\x00" in k or _has_lone_surrogate(k)):
                raise InvalidRecordError("Record keys cannot contain NUL bytes or lone surrogates.")
            _check_structure(v, depth + 1)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _check_structure(v, depth + 1)
    elif isinstance(value, str):
        if "\x00" in value:
            raise InvalidRecordError(
                "Record string values cannot contain NUL bytes (Postgres rejects them)."
            )
        if _has_lone_surrogate(value):
            raise InvalidRecordError("Record string values cannot contain lone UTF-16 surrogates.")


def _has_lone_surrogate(s: str) -> bool:
    """True if ``s`` contains an unpaired surrogate codepoint (U+D800..U+DFFF).

    Lone surrogates are valid Python ``str`` but not valid Unicode — they
    fail UTF-8 encoding (which both Postgres' text type and our size check
    require). Detect explicitly to give a 400 with a clear message rather
    than the cryptic UnicodeEncodeError from the json/encode layer below.
    """
    try:
        s.encode("utf-8")
    except UnicodeEncodeError:
        return True
    return False


def validate_record_data(data: object) -> dict:
    """Validate a record payload is a JSON object within size + structural caps.

    Guards (in order — fail fast on the cheapest checks):
      1. ``isinstance(dict)`` — wrong type.
      2. Top-level key count ≤ ``MAX_RECORD_TOP_LEVEL_KEYS``.
      3. Recursive structural walk — depth, NUL bytes, lone surrogates.
      4. ``json.dumps`` round-trip — catches anything we missed
         (datetime, set, etc.) as ``InvalidRecordError`` instead of 500.
      5. UTF-8 byte size ≤ ``MAX_RECORD_BYTES``.
    """
    if not isinstance(data, dict):
        raise InvalidRecordError("Record data must be a JSON object.")
    if len(data) > MAX_RECORD_TOP_LEVEL_KEYS:
        raise InvalidRecordError(
            f"Record exceeds the {MAX_RECORD_TOP_LEVEL_KEYS} top-level-key limit."
        )
    # Structural walk first — cheaper than json.dumps and gives a clearer
    # message for the specific failure (depth vs NUL vs surrogate).
    _check_structure(data)
    try:
        encoded = json.dumps(data)
    except (TypeError, ValueError, RecursionError) as exc:
        raise InvalidRecordError(f"Record data is not JSON-serialisable: {exc}") from exc
    if len(encoded.encode("utf-8")) > MAX_RECORD_BYTES:
        raise InvalidRecordError(f"Record exceeds the {MAX_RECORD_BYTES // 1024} KB size limit.")
    return data


# --- Collections ------------------------------------------------------------
async def list_collections(db: AsyncSession, project_id: UUID) -> list[WorkspaceCollection]:
    """All collections in a project, ordered by name."""
    result = await db.execute(
        select(WorkspaceCollection)
        .where(WorkspaceCollection.project_id == project_id)
        .order_by(WorkspaceCollection.name)
    )
    return list(result.scalars().all())


async def get_collection(
    db: AsyncSession, project_id: UUID, ref: object
) -> WorkspaceCollection | None:
    """Resolve a collection within a project by UUID or by name."""
    query = select(WorkspaceCollection).where(WorkspaceCollection.project_id == project_id)
    coll_id = _maybe_uuid(ref)
    if coll_id is not None:
        query = query.where(WorkspaceCollection.id == coll_id)
    else:
        query = query.where(WorkspaceCollection.name == str(ref))
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def require_collection(
    db: AsyncSession, project_id: UUID, ref: object
) -> WorkspaceCollection:
    """Like :func:`get_collection` but raises ``CollectionNotFoundError``."""
    coll = await get_collection(db, project_id, ref)
    if coll is None:
        raise CollectionNotFoundError(f"Collection '{ref}' not found.")
    return coll


async def create_collection(
    db: AsyncSession,
    project_id: UUID,
    name: str,
    *,
    public_insert: bool = False,
    public_read: bool = False,
    public_update: bool = False,
    public_delete: bool = False,
) -> WorkspaceCollection:
    """Create a new collection. Raises on bad name, duplicate, or quota.

    All ``public_*`` flags default to ``False`` (secure default). Callers
    must explicitly opt-in to each operation they want anonymous keys to
    perform. See migration 0119 for the matching server-default.
    """
    name = validate_collection_name(name)
    if await get_collection(db, project_id, name) is not None:
        raise CollectionExistsError(f"Collection '{name}' already exists.")
    if await _count_collections(db, project_id) >= MAX_COLLECTIONS_PER_PROJECT:
        raise QuotaExceededError(
            f"Project has reached the {MAX_COLLECTIONS_PER_PROJECT}-collection limit."
        )
    coll = WorkspaceCollection(
        project_id=project_id,
        name=name,
        public_insert=public_insert,
        public_read=public_read,
        public_update=public_update,
        public_delete=public_delete,
    )
    db.add(coll)
    try:
        await db.commit()
    except IntegrityError as exc:
        # A concurrent creator won the race for this (project_id, name) —
        # the uq_workspace_collections_project_name constraint caught it.
        await db.rollback()
        raise CollectionExistsError(f"Collection '{name}' already exists.") from exc
    await db.refresh(coll)
    return coll


async def update_collection(
    db: AsyncSession, collection: WorkspaceCollection, **flags: bool | None
) -> WorkspaceCollection:
    """Update a collection's public access flags (only provided keys)."""
    for field in ("public_insert", "public_read", "public_update", "public_delete"):
        value = flags.get(field)
        if value is not None:
            setattr(collection, field, bool(value))
    await db.commit()
    await db.refresh(collection)
    return collection


async def delete_collection(db: AsyncSession, collection: WorkspaceCollection) -> None:
    """Delete a collection and all of its records.

    Records are bulk-deleted explicitly so the behaviour is identical on
    Postgres and SQLite regardless of the ``foreign_keys`` pragma, and to
    avoid an async-unsafe lazy load of the relationship on parent delete.
    """
    await db.execute(
        sa_delete(WorkspaceRecord).where(WorkspaceRecord.collection_id == collection.id)
    )
    await db.delete(collection)
    await db.commit()


# --- Records ----------------------------------------------------------------
async def insert_record(
    db: AsyncSession, collection: WorkspaceCollection, data: object
) -> WorkspaceRecord:
    """Insert a JSON document into a collection. Raises on bad data or quota."""
    data = validate_record_data(data)
    if await project_record_count(db, collection.project_id) >= MAX_RECORDS_PER_PROJECT:
        raise QuotaExceededError(f"Project has reached the {MAX_RECORDS_PER_PROJECT}-record limit.")
    record = WorkspaceRecord(
        collection_id=collection.id,
        project_id=collection.project_id,
        data=data,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def list_records(
    db: AsyncSession,
    collection_id: UUID,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> tuple[list[WorkspaceRecord], int]:
    """Return ``(page, total)`` — records newest-first, paginated.

    ``limit``/``offset`` are clamped, not rejected: ``None`` means "use the
    default", any supplied integer is clamped into ``[1, MAX_PAGE_SIZE]`` /
    ``[0, ∞)`` — so ``limit=0`` yields one row rather than the default page.
    """
    limit = DEFAULT_PAGE_SIZE if limit is None else int(limit)
    limit = max(1, min(limit, MAX_PAGE_SIZE))
    offset = max(0, 0 if offset is None else int(offset))
    total = (
        await db.execute(
            select(func.count())
            .select_from(WorkspaceRecord)
            .where(WorkspaceRecord.collection_id == collection_id)
        )
    ).scalar_one()
    result = await db.execute(
        select(WorkspaceRecord)
        .where(WorkspaceRecord.collection_id == collection_id)
        .order_by(WorkspaceRecord.created_at.desc(), WorkspaceRecord.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), int(total)


async def get_record(
    db: AsyncSession, collection_id: UUID, record_id: object
) -> WorkspaceRecord | None:
    """Fetch one record by id, scoped to its collection."""
    rec_id = _maybe_uuid(record_id)
    if rec_id is None:
        return None
    result = await db.execute(
        select(WorkspaceRecord).where(
            WorkspaceRecord.collection_id == collection_id,
            WorkspaceRecord.id == rec_id,
        )
    )
    return result.scalar_one_or_none()


async def require_record(
    db: AsyncSession, collection_id: UUID, record_id: object
) -> WorkspaceRecord:
    """Like :func:`get_record` but raises ``RecordNotFoundError``."""
    rec = await get_record(db, collection_id, record_id)
    if rec is None:
        raise RecordNotFoundError(f"Record '{record_id}' not found.")
    return rec


async def update_record(db: AsyncSession, record: WorkspaceRecord, data: object) -> WorkspaceRecord:
    """Replace a record's JSON document."""
    record.data = validate_record_data(data)
    await db.commit()
    await db.refresh(record)
    return record


async def delete_record(db: AsyncSession, record: WorkspaceRecord) -> None:
    """Delete a single record."""
    await db.delete(record)
    await db.commit()


# --- Counts / quota ---------------------------------------------------------
async def _count_collections(db: AsyncSession, project_id: UUID) -> int:
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(WorkspaceCollection)
                .where(WorkspaceCollection.project_id == project_id)
            )
        ).scalar_one()
    )


async def collection_record_count(db: AsyncSession, collection_id: UUID) -> int:
    """Number of records in a single collection."""
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(WorkspaceRecord)
                .where(WorkspaceRecord.collection_id == collection_id)
            )
        ).scalar_one()
    )


async def project_record_count(db: AsyncSession, project_id: UUID) -> int:
    """Total records across all collections in a project (quota check)."""
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(WorkspaceRecord)
                .where(WorkspaceRecord.project_id == project_id)
            )
        ).scalar_one()
    )


# --- Discovery / analysis helpers ------------------------------------------
SUMMARY_SAMPLE = 20
SCHEMA_SAMPLE = 50
AGGREGATE_SAMPLE = 500
AGGREGATE_TOPN_DEFAULT = 10
AGGREGATE_OPS = ("count_present", "count_unique", "value_distribution")


async def _sample_records(
    db: AsyncSession, collection_id: UUID, limit: int
) -> list[WorkspaceRecord]:
    """Newest-first sample, bounded — for summary / schema / aggregation."""
    limit = max(1, min(int(limit), MAX_PAGE_SIZE))
    result = await db.execute(
        select(WorkspaceRecord)
        .where(WorkspaceRecord.collection_id == collection_id)
        .order_by(WorkspaceRecord.created_at.desc(), WorkspaceRecord.id.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


def _field_frequencies(records: list[WorkspaceRecord]) -> dict[str, int]:
    """Count top-level field occurrences across the sample."""
    freq: dict[str, int] = {}
    for r in records:
        for k in r.data or {}:
            freq[k] = freq.get(k, 0) + 1
    return dict(sorted(freq.items(), key=lambda kv: (-kv[1], kv[0])))


def _type_name(v: object) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    return type(v).__name__


def _hashable(v: object):
    """Make any JSON value hashable for set/dict-key usage."""
    if isinstance(v, list):
        return tuple(_hashable(x) for x in v)
    if isinstance(v, dict):
        return tuple(sorted((k, _hashable(val)) for k, val in v.items()))
    return v


async def summarize_collection(
    db: AsyncSession, collection: WorkspaceCollection, sample_size: int = SUMMARY_SAMPLE
) -> dict:
    """One-call discovery payload — total + sample + field frequencies."""
    sample = await _sample_records(db, collection.id, sample_size)
    total = await collection_record_count(db, collection.id)
    return {
        "collection": collection.name,
        "collection_id": str(collection.id),
        "total_records": total,
        "sample_size": len(sample),
        "field_frequencies": _field_frequencies(sample),
        "sample": [
            {
                "id": str(r.id),
                "data": r.data,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in sample
        ],
        "public_insert": collection.public_insert,
        "public_read": collection.public_read,
        "public_update": collection.public_update,
        "public_delete": collection.public_delete,
    }


async def project_data_summary(db: AsyncSession, project_id: UUID, *, sample_size: int = 3) -> dict:
    """Tiny per-project overview for passive discovery in agent context.

    Returns ``{collections: [...], total_records: N}``. Each collection entry
    has ``name``, ``total_records`` and ``top_fields`` (up to 6 most-common
    top-level keys from a tiny sample).
    """
    colls = await list_collections(db, project_id)
    out_colls: list[dict] = []
    total = 0
    for c in colls:
        n = await collection_record_count(db, c.id)
        total += n
        sample = await _sample_records(db, c.id, sample_size) if n else []
        out_colls.append(
            {
                "name": c.name,
                "total_records": n,
                "top_fields": list(_field_frequencies(sample).keys())[:6],
            }
        )
    return {
        "collections": out_colls,
        "collection_count": len(out_colls),
        "total_records": total,
    }


async def infer_schema(
    db: AsyncSession, collection: WorkspaceCollection, sample_size: int = SCHEMA_SAMPLE
) -> dict:
    """Infer field types from a sample. Returns per-field type set + counts."""
    sample = await _sample_records(db, collection.id, sample_size)
    fields: dict[str, dict] = {}
    for r in sample:
        for k, v in (r.data or {}).items():
            entry = fields.setdefault(k, {"types": set(), "present_in": 0})
            entry["types"].add(_type_name(v))
            entry["present_in"] += 1
    return {
        "collection": collection.name,
        "sampled": len(sample),
        "fields": {
            k: {"types": sorted(v["types"]), "present_in": v["present_in"]}
            for k, v in sorted(fields.items())
        },
    }


async def aggregate_field(
    db: AsyncSession,
    collection: WorkspaceCollection,
    field: str,
    op: str,
    *,
    top_n: int = AGGREGATE_TOPN_DEFAULT,
    sample_size: int = AGGREGATE_SAMPLE,
) -> dict:
    """Bounded aggregate over the most-recent ``sample_size`` records.

    ``op`` ∈ {``count_present``, ``count_unique``, ``value_distribution``}.
    Sets ``is_full_scan`` so the agent knows when the result is exact.
    """
    if op not in AGGREGATE_OPS:
        raise InvalidRecordError(
            f"Unsupported aggregate op '{op}'. Choose one of: {', '.join(AGGREGATE_OPS)}."
        )
    if not field or not isinstance(field, str):
        raise InvalidRecordError("'field' must be a non-empty string.")
    sample = await _sample_records(db, collection.id, sample_size)
    total = await collection_record_count(db, collection.id)
    values: list = []
    for r in sample:
        v = (r.data or {}).get(field, None)
        if v is not None:
            values.append(v)
    out: dict = {
        "collection": collection.name,
        "field": field,
        "op": op,
        "sampled": len(sample),
        "total_records": total,
        "is_full_scan": total <= len(sample),
    }
    if op == "count_present":
        out["count_present"] = len(values)
    elif op == "count_unique":
        out["count_unique"] = len({_hashable(v) for v in values})
    elif op == "value_distribution":
        counts: dict = {}
        for v in values:
            key = _hashable(v)
            counts[key] = counts.get(key, 0) + 1
        top_n = max(1, min(int(top_n), 100))
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0])))[:top_n]
        out["top_values"] = [
            {"value": list(k) if isinstance(k, tuple) else k, "count": n} for k, n in ranked
        ]
        out["distinct_count_in_sample"] = len(counts)
    return out
