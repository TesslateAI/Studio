"""Scrub OAuth tokens embedded in projects.git_remote_url.

Revision ID: 0071_scrub_git_remote_url_tokens
Revises: 0070_agent_task_message_id
Create Date: 2026-04-20

Strips embedded credentials (``token@host``, ``oauth2:token@host``,
``x-token-auth:token@host``) from every non-NULL ``git_remote_url`` row so
that only the clean HTTPS URL is stored going forward.  The operation is
idempotent: rows that already contain no userinfo are unchanged.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0071_scrub_git_remote_url_tokens"
down_revision: str | None = "0070_agent_task_message_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _strip_userinfo(url: str) -> str:
    """Remove ``userinfo@`` from the netloc of an HTTP(S) URL."""
    from urllib.parse import urlparse, urlunparse

    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return url
        clean = parsed._replace(netloc=parsed.hostname or "")
        return urlunparse(clean)
    except Exception:
        return url


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, git_remote_url FROM projects WHERE git_remote_url IS NOT NULL")
    ).fetchall()

    updated = 0
    for row in rows:
        original: str = row[1]
        cleaned = _strip_userinfo(original)
        if cleaned != original:
            conn.execute(
                sa.text("UPDATE projects SET git_remote_url = :url WHERE id = :id"),
                {"url": cleaned, "id": row[0]},
            )
            updated += 1

    if updated:
        print(f"[0071] Scrubbed tokens from {updated} git_remote_url row(s)")


def downgrade() -> None:
    # Credentials cannot be re-embedded; downgrade is a no-op by design.
    pass
