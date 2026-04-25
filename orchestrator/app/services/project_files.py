"""Race-safe ProjectFile upsert.

Backed by the ``uq_project_files_project_path`` unique constraint
(migration 0072). The single correct way to write a row into
``project_files`` — never use ``db.add(ProjectFile(...))`` directly,
since concurrent callers will collide on the unique constraint.

Used by every code path that persists project file content:
  - agent file writes (chat router)
  - manual user saves (projects router)
  - design-bridge install (frontend-frameworks only:
    Next.js / Vite / CRA / Vue / Svelte / Astro / Angular / plain HTML —
    see ``app/src/components/views/design/bridgeInstaller.ts``)

Caller owns the transaction (no commit here) so this composes cleanly
with other work in the same request.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ProjectFile


async def upsert_project_file(
    db: AsyncSession,
    *,
    project_id: Any,
    file_path: str,
    content: str,
) -> None:
    """Insert or update a ``project_files`` row atomically.

    Uses the dialect-native ``INSERT ... ON CONFLICT DO UPDATE`` so two
    concurrent saves of the same ``(project_id, file_path)`` collapse
    to a single row instead of racing into duplicates that later
    explode ``scalar_one_or_none()`` queries.
    """
    bind = db.get_bind()
    dialect_name = bind.dialect.name
    now = datetime.utcnow()

    values = {
        "project_id": project_id,
        "file_path": file_path,
        "content": content,
    }
    update_set = {"content": content, "updated_at": now}

    if dialect_name == "postgresql":
        stmt = pg_insert(ProjectFile).values(**values).on_conflict_do_update(
            index_elements=["project_id", "file_path"],
            set_=update_set,
        )
    elif dialect_name == "sqlite":
        stmt = sqlite_insert(ProjectFile).values(**values).on_conflict_do_update(
            index_elements=["project_id", "file_path"],
            set_=update_set,
        )
    else:
        raise NotImplementedError(
            f"upsert_project_file: unsupported dialect {dialect_name!r}"
        )

    await db.execute(stmt)
