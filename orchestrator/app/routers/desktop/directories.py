"""Directory CRUD endpoints (list/create/delete with git-root detection)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import get_db
from ...models import Directory, User
from ...users import current_active_user
from ._helpers import _canonical_path, _detect_git_root, _serialize_directory

router = APIRouter()


class DirectoryCreate(BaseModel):
    path: str
    runtime: str | None = None
    project_id: uuid.UUID | None = None


@router.get("/directories")
async def list_directories(
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(Directory).where(Directory.user_id == user.id).order_by(Directory.created_at)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return {"directories": [_serialize_directory(d) for d in rows]}


@router.post("/directories")
async def create_directory(
    body: DirectoryCreate,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    canonical = _canonical_path(body.path)
    existing = await db.execute(
        select(Directory).where(Directory.user_id == user.id, Directory.path == canonical)
    )
    row = existing.scalar_one_or_none()
    if row is not None:
        row.last_opened_at = datetime.now(UTC)
        if body.runtime:
            row.runtime = body.runtime
        if body.project_id is not None:
            row.project_id = body.project_id
        await db.commit()
        await db.refresh(row)
        return _serialize_directory(row)

    directory = Directory(
        id=uuid.uuid4(),
        user_id=user.id,
        path=canonical,
        runtime=body.runtime,
        project_id=body.project_id,
        git_root=_detect_git_root(canonical),
        last_opened_at=datetime.now(UTC),
    )
    db.add(directory)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await db.execute(
            select(Directory).where(Directory.user_id == user.id, Directory.path == canonical)
        )
        row = existing.scalar_one()
        return _serialize_directory(row)
    await db.refresh(directory)
    return _serialize_directory(directory)


@router.delete("/directories/{directory_id}", status_code=204)
async def delete_directory(
    directory_id: uuid.UUID,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    existing = await db.execute(
        select(Directory).where(Directory.id == directory_id, Directory.user_id == user.id)
    )
    row = existing.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="directory not found")
    await db.delete(row)
    await db.commit()
