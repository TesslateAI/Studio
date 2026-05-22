"""Key generation, hashing and CRUD for the Workspace Data API.

Raw keys are shown to the caller exactly once; only the SHA-256 hash is
persisted. ``anon`` keys are browser-safe (rule-restricted by each
collection's public flags); ``service`` keys are server-side secrets with
full project access. This module is the single home for key logic — the
HTTP router, the agent tool and the deploy-time key injection all use it.
"""

import hashlib
import secrets
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models_workspace_data import WorkspaceDataKey
from .store import QuotaExceededError, WorkspaceDataError

VALID_KINDS = ("anon", "service")
MAX_KEYS_PER_PROJECT = 20

# Name of the auto-managed anon key the deploy flow injects into apps.
DEPLOY_KEY_NAME = "deploy"

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
async def list_data_keys(db: AsyncSession, project_id: UUID) -> list[WorkspaceDataKey]:
    """All API keys for a project, newest first."""
    result = await db.execute(
        select(WorkspaceDataKey)
        .where(WorkspaceDataKey.project_id == project_id)
        .order_by(WorkspaceDataKey.created_at.desc())
    )
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
    """Delete a key. Returns ``False`` if it did not exist in the project."""
    key = await get_data_key(db, project_id, key_id)
    if key is None:
        return False
    await db.delete(key)
    await db.commit()
    return True


async def resolve_data_key(db: AsyncSession, raw: str) -> WorkspaceDataKey | None:
    """Resolve an active key from its raw value (Data API auth).

    Stamps ``last_used_at`` best-effort — never fails the lookup on a write
    error.
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
    if key is not None:
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
