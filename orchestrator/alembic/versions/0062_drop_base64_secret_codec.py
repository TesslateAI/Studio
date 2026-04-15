"""Safety marker for dropping the base64 secret_codec.

Revision ID: 0062_drop_base64_secret_codec
Revises: 0061_backfill_container_secrets
Create Date: 2026-04-14 10:10:00.000000

No schema changes. Verifies that 0057 has been applied cleanly by ensuring
no container still has a secret-shaped key living in ``environment_vars``
without a corresponding entry in ``encrypted_secrets``. Aborts with a clear
message pointing operators at 0057 if data is in an inconsistent state.

The matching ``secret_codec.py`` module is removed in the same patch.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0062_drop_base64_secret_codec"
down_revision: str | Sequence[str] | None = "0061_backfill_container_secrets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration.0058_drop_base64_secret_codec")

_SECRET_KEY_RE = re.compile(r"(?i)(KEY|SECRET|TOKEN|PASSWORD|PASS|CREDENTIAL|PRIVATE)")


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, environment_vars, encrypted_secrets FROM containers "
            "WHERE environment_vars IS NOT NULL"
        )
    ).fetchall()

    offenders: list[tuple[str, list[str]]] = []
    for row in rows:
        env_vars = row._mapping.get("environment_vars") or {}
        encrypted = row._mapping.get("encrypted_secrets") or {}
        missing = [k for k in env_vars if _SECRET_KEY_RE.search(k) and k not in (encrypted or {})]
        if missing:
            offenders.append((str(row._mapping["id"]), missing))

    if offenders:
        detail = "; ".join(f"{cid}: {keys}" for cid, keys in offenders[:10])
        raise RuntimeError(
            "0058_drop_base64_secret_codec aborted — containers still have "
            "secret-shaped env keys that were not migrated to encrypted_secrets. "
            "Run migration 0057_backfill_container_secrets (and review "
            "scripts/secrets_migrate_audit.py) before applying this revision. "
            f"Offending containers ({len(offenders)}): {detail}"
        )

    logger.info(
        "[0058] Verified %d container(s): no base64 secret residue in environment_vars.",
        len(rows),
    )


def downgrade() -> None:
    # Pure safety marker — nothing to revert.
    pass
