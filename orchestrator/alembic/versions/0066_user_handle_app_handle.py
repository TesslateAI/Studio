"""Add creator-branded handles for users and marketplace apps (Wave 9 B1).

Revision ID: 0066_user_handle_app_handle
Revises: 0065_app_install_attempt
Create Date: 2026-04-15 12:00:00.000000

App runtime URLs used to read as gibberish:
``{project-slug}-{container-dir}.{app_domain}``. Wave 9 Track B1
introduces creator-branded URLs:
``{container-dir}-{app-handle}-{creator-handle}.{app_domain}`` (or
``{app-handle}-{creator-handle}.{app_domain}`` for single-container
apps). Both shapes stay under one DNS label so the existing
``*.{app_domain}`` wildcard cert keeps covering them — no per-creator
cert needed for this wave.

This migration:
1. Adds nullable ``users.handle`` (String(32)) and ``marketplace_apps.handle``
   (String(48)).
2. Backfills both columns idempotently:
   - ``users.handle`` derives from ``username`` when it matches the
     handle regex; otherwise from the email local-part slugified.
     Collisions resolved by appending the first 6 chars of the user id.
   - ``marketplace_apps.handle`` derives from the slug. Collisions
     within the same creator are resolved by appending an integer
     suffix (``-2``, ``-3``, …).
3. Adds the unique constraints AFTER the backfill so partial data
   doesn't trip the index build.

Reserved handles (admin, api, app, …) are skipped during backfill — if
a user/app would land on one, we append the id-suffix to dodge it.

Online-safe: no FK changes, only nullable columns + unique indexes
created after backfill. Existing rows with NULL handle stay NULL until
the next ``PATCH /users/me/handle`` (UI prompt).
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0066_user_handle_app_handle"
down_revision: str | Sequence[str] | None = "0065_app_install_attempt"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Mirrors orchestrator/app/services/apps/reserved_handles.py — duplicated
# here so migrations stay self-contained (alembic doesn't depend on app
# code at upgrade time).
RESERVED_HANDLES: frozenset[str] = frozenset(
    {
        "admin",
        "api",
        "app",
        "apps",
        "marketplace",
        "studio",
        "www",
        "docs",
        "status",
        "health",
        "blog",
        "support",
        "help",
        "about",
        "login",
        "logout",
        "signup",
        "signin",
        "settings",
        "account",
        "user",
        "users",
        "team",
        "teams",
        "billing",
        "pricing",
        "security",
        "privacy",
        "terms",
        "tesslate",
        "mail",
        "smtp",
        "pop",
        "imap",
        "ftp",
        "ssh",
        "git",
        "vpn",
        "cdn",
        "s3",
        "staging",
        "prod",
        "production",
        "dev",
        "test",
        "localhost",
    }
)

_HANDLE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,30}[a-z0-9]$")
_SLUGIFY_BAD = re.compile(r"[^a-z0-9-]+")
_COLLAPSE_DASH = re.compile(r"-{2,}")


def _slugify(raw: str, *, max_len: int) -> str:
    s = (raw or "").lower().strip()
    s = _SLUGIFY_BAD.sub("-", s)
    s = _COLLAPSE_DASH.sub("-", s).strip("-")
    if len(s) > max_len:
        s = s[:max_len].rstrip("-")
    if len(s) < 3:
        s = (s + "user")[:max_len]
    return s


def _safe_handle(candidate: str, *, user_id_hex: str, max_len: int) -> str:
    """Return a candidate that's regex-valid and not reserved."""
    handle = _slugify(candidate, max_len=max_len)
    if handle in RESERVED_HANDLES or not _HANDLE_RE.match(handle):
        suffix = "-" + user_id_hex[:6]
        handle = (handle[: max_len - len(suffix)] + suffix).strip("-")
    return handle


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    # 1. Add nullable columns.
    op.add_column("users", sa.Column("handle", sa.String(32), nullable=True))
    op.add_column("marketplace_apps", sa.Column("handle", sa.String(48), nullable=True))

    # 2. Backfill users.handle.
    # PostgreSQL UUIDs need ::text cast; SQLite stores them as TEXT already.
    _id_cast = "::text" if is_pg else ""
    user_rows = bind.execute(
        sa.text(f"SELECT id{_id_cast} AS id, username, email FROM users WHERE handle IS NULL")
    ).fetchall()
    used: set[str] = set()
    # Pre-seed with anything already present (none after add_column, but defensive).
    for row in bind.execute(
        sa.text("SELECT handle FROM users WHERE handle IS NOT NULL")
    ).fetchall():
        used.add(row[0])

    for row in user_rows:
        uid = row.id
        username = (row.username or "").lower()
        email_local = (row.email or "").split("@", 1)[0].lower() if row.email else ""
        if username and _HANDLE_RE.match(username) and username not in RESERVED_HANDLES:
            base = username
        else:
            base = email_local or "user"
        handle = _safe_handle(base, user_id_hex=uid.replace("-", ""), max_len=32)
        # Collision resolution: append id-suffix, then numeric.
        if handle in used:
            handle = _safe_handle(handle, user_id_hex=uid.replace("-", ""), max_len=32)
        n = 2
        while handle in used:
            tail = f"-{n}"
            handle = handle[: 32 - len(tail)].rstrip("-") + tail
            n += 1
        used.add(handle)
        bind.execute(
            sa.text("UPDATE users SET handle = :h WHERE id = :id"),
            {"h": handle, "id": uid},
        )

    # 3. Backfill marketplace_apps.handle (uniqueness scoped per creator).
    app_rows = bind.execute(
        sa.text(
            f"SELECT id{_id_cast} AS id, slug, creator_user_id{_id_cast} AS creator_user_id "
            "FROM marketplace_apps WHERE handle IS NULL"
        )
    ).fetchall()
    used_per_creator: dict[str, set[str]] = {}
    for row in bind.execute(
        sa.text(
            f"SELECT creator_user_id{_id_cast} AS creator, handle FROM marketplace_apps "
            "WHERE handle IS NOT NULL AND creator_user_id IS NOT NULL"
        )
    ).fetchall():
        used_per_creator.setdefault(row[0], set()).add(row[1])

    for row in app_rows:
        creator = row.creator_user_id or ""
        slug = (row.slug or "").lower()
        base = _slugify(slug, max_len=48)
        if base in RESERVED_HANDLES or not _HANDLE_RE.match(base):
            base = _safe_handle(base, user_id_hex=row.id.replace("-", ""), max_len=48)
        bucket = used_per_creator.setdefault(creator, set())
        handle = base
        n = 2
        while handle in bucket:
            tail = f"-{n}"
            handle = base[: 48 - len(tail)].rstrip("-") + tail
            n += 1
        bucket.add(handle)
        bind.execute(
            sa.text("UPDATE marketplace_apps SET handle = :h WHERE id = :id"),
            {"h": handle, "id": row.id},
        )

    # 4. Add unique constraints AFTER backfill.
    op.create_index(
        "ux_users_handle",
        "users",
        ["handle"],
        unique=True,
        postgresql_where=sa.text("handle IS NOT NULL"),
    )
    op.create_index(
        "uq_marketplace_apps_creator_handle",
        "marketplace_apps",
        ["creator_user_id", "handle"],
        unique=True,
        postgresql_where=sa.text("handle IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_marketplace_apps_creator_handle", table_name="marketplace_apps")
    op.drop_index("ux_users_handle", table_name="users")
    op.drop_column("marketplace_apps", "handle")
    op.drop_column("users", "handle")
