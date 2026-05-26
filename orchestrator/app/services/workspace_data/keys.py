"""Key generation, hashing and CRUD for the Workspace Data API.

Raw keys are shown to the caller exactly once; only the SHA-256 hash is
persisted. ``anon`` keys are browser-safe (rule-restricted by each
collection's public flags); ``service`` keys are server-side secrets with
full project access. This module is the single home for key logic — the
HTTP router, the agent tool and the deploy-time key injection all use it.
"""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from ...models_workspace_data import WorkspaceDataKey
from .store import QuotaExceededError, WorkspaceDataError

VALID_KINDS = ("anon", "service")
MAX_KEYS_PER_PROJECT = 20

# Name of the auto-managed anon key the deploy flow rotates per deploy
# (kept for backward compat — new callers should prefer the stable
# autoinject key below).
DEPLOY_KEY_NAME = "deploy"

# Stable per-project anon key used by both in-cluster startup AND deploy
# injection. Plaintext is derived deterministically (HMAC of project_id
# under SECRET_KEY) so no DB write is needed on cache-hit, and there's
# no plaintext-storage problem. ONE row per project, never rotates
# automatically — explicit user action only.
AUTOINJECT_KEY_NAME = "__tesslate_autoinject__"
_AUTOINJECT_NAMESPACE = b"workspace-data:autoinject:v1"

_KIND_PREFIX = {"anon": "wsk_anon_", "service": "wsk_svc_"}


class InvalidKeyError(WorkspaceDataError):
    """Key kind or name failed validation."""


# --- Generation / hashing ---------------------------------------------------
def generate_key(kind: str) -> tuple[str, str, str]:
    """Mint a new key.

    Returns ``(raw_key, key_hash, key_prefix)``. ``raw_key`` is returned once
    and never stored; ``key_hash`` is persisted and looked up on each request;
    ``key_prefix`` is a non-secret display identifier.
    """
    prefix = _KIND_PREFIX.get(kind)
    if prefix is None:
        raise InvalidKeyError(f"invalid key kind: {kind!r} (expected one of {VALID_KINDS})")
    raw = f"{prefix}{secrets.token_hex(24)}"
    return raw, hash_key(raw), raw[:20]


def hash_key(raw: str) -> str:
    """SHA-256 hex digest of a raw key — what we persist and look up by."""
    return hashlib.sha256(raw.strip().encode("utf-8")).hexdigest()


# --- CRUD -------------------------------------------------------------------
async def list_data_keys(
    db: AsyncSession,
    project_id: UUID,
    *,
    include_revoked: bool = False,
) -> list[WorkspaceDataKey]:
    """Active API keys for a project, newest first.

    Soft-revoked rows (``is_active=False``) are excluded by default so the
    mgmt UI sees the same contract it did before soft-revoke landed. Pass
    ``include_revoked=True`` from a future audit endpoint to surface the
    full history (``last_used_at`` on a revoked row is what makes
    soft-revoke worth doing — it answers "when was this key last used"
    after the fact).
    """
    query = select(WorkspaceDataKey).where(WorkspaceDataKey.project_id == project_id)
    if not include_revoked:
        query = query.where(WorkspaceDataKey.is_active.is_(True))
    result = await db.execute(query.order_by(WorkspaceDataKey.created_at.desc()))
    return list(result.scalars().all())


async def count_data_keys(db: AsyncSession, project_id: UUID) -> int:
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(WorkspaceDataKey)
                .where(WorkspaceDataKey.project_id == project_id)
            )
        ).scalar_one()
    )


async def get_data_key(
    db: AsyncSession, project_id: UUID, key_id: object
) -> WorkspaceDataKey | None:
    """Fetch one key by id, scoped to its project."""
    try:
        kid = key_id if isinstance(key_id, UUID) else UUID(str(key_id))
    except (ValueError, TypeError, AttributeError):
        return None
    result = await db.execute(
        select(WorkspaceDataKey).where(
            WorkspaceDataKey.id == kid,
            WorkspaceDataKey.project_id == project_id,
        )
    )
    return result.scalar_one_or_none()


async def create_data_key(
    db: AsyncSession,
    project_id: UUID,
    name: str,
    kind: str = "anon",
    created_by_id: UUID | None = None,
) -> tuple[WorkspaceDataKey, str]:
    """Mint and persist a key. Returns ``(key, raw_secret)``."""
    if kind not in VALID_KINDS:
        raise InvalidKeyError(f"Key kind must be one of {VALID_KINDS}.")
    name = (name or "").strip()
    if not name:
        raise InvalidKeyError("Key name cannot be empty.")
    if len(name) > 100:
        raise InvalidKeyError("Key name cannot exceed 100 characters.")
    if await count_data_keys(db, project_id) >= MAX_KEYS_PER_PROJECT:
        raise QuotaExceededError(f"Project has reached the {MAX_KEYS_PER_PROJECT}-key limit.")
    raw, key_hash, key_prefix = generate_key(kind)
    key = WorkspaceDataKey(
        project_id=project_id,
        created_by_id=created_by_id,
        key_hash=key_hash,
        key_prefix=key_prefix,
        name=name,
        kind=kind,
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    return key, raw


async def revoke_data_key(db: AsyncSession, project_id: UUID, key_id: object) -> bool:
    """Soft-revoke a key (flip ``is_active=False``). Returns ``False`` if it
    did not exist in the project.

    Soft-revoke (not hard-delete) so the audit trail and ``key_prefix`` /
    ``last_used_at`` history survive — useful for post-incident forensics
    ("when was this key used last, and by whom"). ``resolve_data_key``
    filters on ``is_active`` so revoked keys stop authenticating
    immediately; the row hangs around for the audit team.
    """
    key = await get_data_key(db, project_id, key_id)
    if key is None or not key.is_active:
        return False
    key.is_active = False
    await db.commit()
    return True


# ``last_used_at`` debounce — only one Postgres UPDATE per (key_id, window).
# Without it every Data API request triggers a write on the hot path, which
# both serializes the request through a DB roundtrip and creates a DoS
# amplification vector against the platform DB. The window is short enough
# (60s) that "last used" is still meaningful for forensics; the hot
# in-flight path costs at most one INCR + one EXPIRE on Redis.
_LAST_USED_DEBOUNCE_SECONDS = 60
_LAST_USED_REDIS_KEY = "tesslate:wsdata:last_used:{key_id}"


async def _should_stamp_last_used(key_id: UUID) -> bool:
    """Redis-throttle helper: True iff no other request stamped within the window.

    Best-effort — when Redis is unreachable we fall back to stamping every
    request (the v1 behaviour), so the audit info stays fresh at the cost
    of the extra writes.
    """
    try:
        from ..cache_service import get_redis_client

        client = await get_redis_client()
    except Exception:
        client = None
    if client is None:
        return True
    try:
        # SET NX EX: returns truthy only when the key didn't already exist.
        # Equivalent to "first request in the window" → caller stamps.
        ok = await client.set(
            _LAST_USED_REDIS_KEY.format(key_id=key_id),
            "1",
            nx=True,
            ex=_LAST_USED_DEBOUNCE_SECONDS,
        )
        return bool(ok)
    except Exception:
        return True


async def resolve_data_key(db: AsyncSession, raw: str) -> WorkspaceDataKey | None:
    """Resolve an active key from its raw value (Data API auth).

    Stamps ``last_used_at`` best-effort, debounced through Redis so the
    hot request path doesn't serialize through a DB write on every call.
    Never fails the lookup on a write error.
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    result = await db.execute(
        select(WorkspaceDataKey).where(
            WorkspaceDataKey.key_hash == hash_key(raw),
            WorkspaceDataKey.is_active.is_(True),
        )
    )
    key = result.scalar_one_or_none()
    if key is not None and await _should_stamp_last_used(key.id):
        try:
            key.last_used_at = datetime.now(UTC)
            await db.commit()
        except Exception:
            await db.rollback()
    return key


async def rotate_deploy_key(
    db: AsyncSession, project_id: UUID, created_by_id: UUID | None = None
) -> tuple[WorkspaceDataKey, str]:
    """Mint a fresh anon ``deploy`` key, revoking any prior one.

    Used by the deployment flow so each deploy injects a current key into the
    deployed app. Rotation keeps exactly one deploy key and refreshes it on
    every deploy (good hygiene — old build artifacts' keys stop working).
    """
    for k in await list_data_keys(db, project_id):
        if k.name == DEPLOY_KEY_NAME:
            await db.delete(k)
    await db.commit()
    return await create_data_key(db, project_id, DEPLOY_KEY_NAME, "anon", created_by_id)


# --- Auto-inject key (stable, deterministic) -------------------------------
def _derive_autoinject_raw(project_id: UUID) -> str:
    """HMAC-derive a stable anon-key plaintext from project_id + SECRET_KEY.

    Pure function — same inputs → same plaintext. This is what lets in-cluster
    container restarts re-mint the SAME plaintext on demand, so we never
    invalidate a previously-issued key and we never store plaintext on disk.

    Rotation surface: changing the server's ``SECRET_KEY`` invalidates ALL
    autoinject keys cluster-wide (deliberate — same blast radius as session
    secrets). Per-project rotation needs an explicit ``revoke`` + re-mint cycle.
    """
    secret = (get_settings().secret_key or "").encode("utf-8")
    if not secret:
        raise InvalidKeyError("SECRET_KEY is unset — workspace-data autoinject requires it.")
    msg = _AUTOINJECT_NAMESPACE + b":" + str(project_id).encode("utf-8")
    digest = hmac.new(secret, msg, hashlib.sha256).hexdigest()
    return f"{_KIND_PREFIX['anon']}{digest[:48]}"


async def get_or_create_autoinject_key(db: AsyncSession, project_id: UUID) -> str:
    """Stable per-project autoinject anon key (plaintext).

    Idempotent: safe to call on every container restart and every deploy.
    Internally:
      1. Derive the plaintext deterministically (no DB read).
      2. Look up by hash — common case after the first call, no write.
      3. Cold path: INSERT one row. Race-safe via the unique hash constraint
         — concurrent inserts collide on hash, the loser rolls back and the
         derived plaintext is identical so the caller is unaffected.

    Does NOT count against ``MAX_KEYS_PER_PROJECT`` quota for re-derives
    because we read first. The single one-time INSERT does count.
    """
    raw = _derive_autoinject_raw(project_id)
    key_hash = hash_key(raw)

    existing = await db.execute(
        select(WorkspaceDataKey).where(
            WorkspaceDataKey.project_id == project_id,
            WorkspaceDataKey.key_hash == key_hash,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return raw

    row = WorkspaceDataKey(
        project_id=project_id,
        key_hash=key_hash,
        key_prefix=raw[:20],
        name=AUTOINJECT_KEY_NAME,
        kind="anon",
        is_active=True,
    )
    db.add(row)
    try:
        await db.commit()
    except Exception:
        # Concurrent worker raced us; the derived plaintext is identical so
        # the caller is unaffected. Roll back and return.
        await db.rollback()
    return raw
