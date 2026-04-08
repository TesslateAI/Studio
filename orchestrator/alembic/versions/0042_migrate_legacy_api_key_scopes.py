"""Migrate legacy API key scope values to Permission enum format

Maps old-format scopes (agent:invoke, agent:status) to the RBAC Permission enum
values (chat.send, chat.view). Null scopes are preserved as-is (full-access keys).

Revision ID: 0042_legacy_scopes
Revises: 0041_team_theme_preset
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0042_legacy_scopes"
down_revision: str | Sequence[str] | None = "0041_team_theme_preset"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Old scope → new Permission enum value
SCOPE_MIGRATION_MAP = {
    "agent:invoke": "chat.send",
    "agent:status": "chat.view",
    "agent:events": "chat.view",
    "project:read": "project.view",
    "project:write": "project.edit",
    "files:read": "file.read",
    "files:write": "file.write",
}


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, scopes FROM external_api_keys WHERE scopes IS NOT NULL")
    ).fetchall()

    for row in rows:
        key_id = row[0]
        scopes = row[1]
        if not isinstance(scopes, list):
            continue

        migrated = []
        changed = False
        for scope in scopes:
            if scope in SCOPE_MIGRATION_MAP:
                new_scope = SCOPE_MIGRATION_MAP[scope]
                if new_scope not in migrated:
                    migrated.append(new_scope)
                changed = True
            else:
                if scope not in migrated:
                    migrated.append(scope)

        if changed:
            conn.execute(
                sa.text("UPDATE external_api_keys SET scopes = :scopes::jsonb WHERE id = :id"),
                {"scopes": json.dumps(migrated), "id": str(key_id)},
            )


def downgrade() -> None:
    reverse_map = {
        "chat.send": "agent:invoke",
        "chat.view": "agent:status",
        "project.view": "project:read",
        "project.edit": "project:write",
        "file.read": "files:read",
        "file.write": "files:write",
    }
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, scopes FROM external_api_keys WHERE scopes IS NOT NULL")
    ).fetchall()

    for row in rows:
        key_id = row[0]
        scopes = row[1]
        if not isinstance(scopes, list):
            continue

        reverted = []
        changed = False
        for scope in scopes:
            if scope in reverse_map:
                old_scope = reverse_map[scope]
                if old_scope not in reverted:
                    reverted.append(old_scope)
                changed = True
            else:
                if scope not in reverted:
                    reverted.append(scope)

        if changed:
            conn.execute(
                sa.text("UPDATE external_api_keys SET scopes = :scopes::jsonb WHERE id = :id"),
                {"scopes": json.dumps(reverted), "id": key_id},
            )
