"""Backfill webhook_secrets[] for existing slack_message/email_inbound triggers.

Revision ID: 0114_backfill_typed_trigger_secrets
Revises: 0113_workflow_event_index
Create Date: 2026-05-17

The Phase E adapter refactor unified all HTTP-fed trigger kinds onto
the same HMAC infrastructure that develop's per-automation webhook
already uses (``trigger.config["webhook_secrets"][]`` with
rotation-friendly kid + secret + revoked_at entries). Pre-existing
``slack_message`` / ``email_inbound`` triggers minted under the
old global env-var scheme have no per-trigger secret and would
return 503 ("inbound trigger missing webhook_secrets — re-save the
automation") at the verifier.

This migration auto-provisions a single ``v1`` secret entry per
affected row so existing automations keep working without forcing
every user to round-trip the edit UI. The new secret is a
URL-safe 32-byte token — the same shape ``_mint_webhook_secret``
emits at save time. The migration is idempotent: it only touches
rows whose config is missing both ``webhook_secrets`` and the
legacy ``webhook_secret``.

Postgres-only path uses jsonb_set; SQLite is skipped (the test
fixture builds the schema fresh via ``create_all`` so backfill
is a no-op there).
"""

import secrets as _stdlib_secrets
from datetime import UTC, datetime

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = "0114_backfill_typed_trigger_secrets"
down_revision = "0113_workflow_event_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # Find affected rows (typed inbound triggers without any secret).
    rows = bind.execute(
        text(
            """
            SELECT id
            FROM automation_triggers
            WHERE kind IN ('slack_message', 'email_inbound')
              AND (config->'webhook_secrets' IS NULL OR jsonb_typeof(config->'webhook_secrets') <> 'array' OR jsonb_array_length(config->'webhook_secrets') = 0)
              AND (config->>'webhook_secret' IS NULL OR config->>'webhook_secret' = '')
            """
        )
    ).fetchall()

    if not rows:
        return

    now_iso = datetime.now(tz=UTC).isoformat()
    for (trigger_id,) in rows:
        entry = {
            "kid": "v1",
            "secret": _stdlib_secrets.token_urlsafe(32),
            "created_at": now_iso,
            "revoked_at": None,
        }
        # Append into config.webhook_secrets[] (creates the key if missing).
        bind.execute(
            text(
                """
                UPDATE automation_triggers
                SET config = jsonb_set(
                    COALESCE(config, '{}'::jsonb),
                    '{webhook_secrets}',
                    to_jsonb(ARRAY[CAST(:entry AS jsonb)]),
                    true
                )
                WHERE id = :id
                """
            ),
            {"entry": _json_dumps(entry), "id": trigger_id},
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    # Best-effort: drop the auto-provisioned secrets we added. We can't
    # tell post-hoc which ones were ours vs. user-provided, so we only
    # remove the key when the list is exactly one v1 entry (our exact
    # output shape). Users who rotated keep their full list intact.
    bind.execute(
        text(
            """
            UPDATE automation_triggers
            SET config = config - 'webhook_secrets'
            WHERE kind IN ('slack_message', 'email_inbound')
              AND jsonb_typeof(config->'webhook_secrets') = 'array'
              AND jsonb_array_length(config->'webhook_secrets') = 1
              AND config->'webhook_secrets'->0->>'kid' = 'v1'
            """
        )
    )


def _json_dumps(value: dict) -> str:
    import json

    return json.dumps(value)
