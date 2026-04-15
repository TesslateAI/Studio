"""Backfill container secrets from base64 environment_vars → Fernet encrypted_secrets.

Revision ID: 0061_backfill_container_secrets
Revises: 0060_container_encrypted_secrets
Create Date: 2026-04-14 10:05:00.000000

For every container row:
  1. Determine secret keys using the service preset (if ``service_slug`` maps
     to a known definition with ``credential_fields``) OR the regex
     ``(?i)(KEY|SECRET|TOKEN|PASSWORD|PASS|CREDENTIAL|PRIVATE)``.
  2. For each matched key present in ``environment_vars``:
       * try base64-decode; fall back to the raw value (plaintext).
       * re-encrypt with ``deployment_encryption_service.encrypt``.
       * move to ``encrypted_secrets[key]``.
       * remove from ``environment_vars``.
  3. Log every touched row + key at INFO.

Downgrade reverses: decrypt with Fernet, base64-encode, push back into
``environment_vars``, null ``encrypted_secrets``.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0061_backfill_container_secrets"
down_revision: str | Sequence[str] | None = "0060_container_encrypted_secrets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration.0057_backfill_container_secrets")

_SECRET_KEY_RE = re.compile(r"(?i)(KEY|SECRET|TOKEN|PASSWORD|PASS|CREDENTIAL|PRIVATE)")


def _maybe_base64_decode(value: str) -> str:
    """Best-effort base64 decode; fall back to raw string."""
    if not isinstance(value, str) or not value:
        return value or ""
    try:
        decoded = base64.b64decode(value.encode("utf-8"), validate=True).decode("utf-8")
        return decoded
    except Exception:
        return value


def _secret_keys_for_row(row) -> set[str]:
    """Resolve which keys in environment_vars are secrets for this container."""
    keys: set[str] = set()

    # Try preset lookup via service_slug
    slug = row._mapping.get("service_slug") if hasattr(row, "_mapping") else row["service_slug"]
    if slug:
        try:
            # Import lazily to avoid forcing app import order at alembic boot.
            from app.services.service_definitions import get_service

            svc = get_service(slug)
            if svc and svc.credential_fields:
                for field in svc.credential_fields:
                    keys.add(field.key)
        except Exception:
            logger.debug("preset lookup failed for slug=%s", slug, exc_info=True)

    env_vars = (
        row._mapping.get("environment_vars")
        if hasattr(row, "_mapping")
        else row["environment_vars"]
    )
    if env_vars:
        for k in env_vars:
            if _SECRET_KEY_RE.search(k):
                keys.add(k)
    return keys


def upgrade() -> None:
    # Import lazily — alembic is invoked from orchestrator/ with app on sys.path
    from app.services.deployment_encryption import get_deployment_encryption_service

    enc = get_deployment_encryption_service()

    bind = op.get_bind()
    rows = bind.execute(
        _sql_select("SELECT id, service_slug, environment_vars, encrypted_secrets FROM containers")
    ).fetchall()

    total_rows = 0
    total_keys = 0
    for row in rows:
        env_vars = dict(row._mapping.get("environment_vars") or {})
        encrypted = dict(row._mapping.get("encrypted_secrets") or {})
        secret_keys = _secret_keys_for_row(row)
        matched = [k for k in list(env_vars.keys()) if k in secret_keys]
        if not matched:
            continue

        container_id = row._mapping["id"]
        logger.info(
            "[0057] container=%s backfilling %d secret key(s): %s",
            container_id,
            len(matched),
            matched,
        )

        for key in matched:
            raw = env_vars.pop(key)
            plaintext = _maybe_base64_decode(raw) if isinstance(raw, str) else ""
            encrypted[key] = enc.encrypt(plaintext)
            total_keys += 1

        bind.execute(
            _sql_update(
                "UPDATE containers SET environment_vars = :env, encrypted_secrets = :enc "
                "WHERE id = :id"
            ),
            {
                "env": json.dumps(env_vars),
                "enc": json.dumps(encrypted),
                "id": container_id,
            },
        )
        total_rows += 1

    logger.info(
        "[0057] Backfill complete: %d row(s) updated, %d key(s) migrated to encrypted_secrets",
        total_rows,
        total_keys,
    )


def downgrade() -> None:
    from app.services.deployment_encryption import get_deployment_encryption_service

    enc = get_deployment_encryption_service()
    bind = op.get_bind()
    rows = bind.execute(
        _sql_select(
            "SELECT id, environment_vars, encrypted_secrets FROM containers "
            "WHERE encrypted_secrets IS NOT NULL"
        )
    ).fetchall()

    for row in rows:
        env_vars = dict(row._mapping.get("environment_vars") or {})
        encrypted = dict(row._mapping.get("encrypted_secrets") or {})
        if not encrypted:
            continue

        container_id = row._mapping["id"]
        logger.info(
            "[0057][downgrade] container=%s restoring %d key(s) to base64 env",
            container_id,
            len(encrypted),
        )

        for key, enc_val in list(encrypted.items()):
            try:
                plaintext = enc.decrypt(enc_val)
            except Exception:
                logger.exception(
                    "[0057][downgrade] container=%s key=%s decrypt failed, skipping",
                    container_id,
                    key,
                )
                continue
            env_vars[key] = base64.b64encode(plaintext.encode("utf-8")).decode("utf-8")

        bind.execute(
            _sql_update(
                "UPDATE containers SET environment_vars = :env, encrypted_secrets = NULL "
                "WHERE id = :id"
            ),
            {"env": json.dumps(env_vars), "id": container_id},
        )


def _sql_select(sql: str):
    """Wrap in text() — placed in a helper so both dialects stay readable."""
    import sqlalchemy as sa  # local import keeps migration self-contained

    return sa.text(sql)


def _sql_update(sql: str):
    import sqlalchemy as sa

    return sa.text(sql)
