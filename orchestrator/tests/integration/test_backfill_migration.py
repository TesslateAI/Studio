"""Integration test for migration 0061_backfill_container_secrets.

Runs the migration's ``upgrade()`` body directly against the test DB,
inserting a Container with base64-shaped secret keys in ``environment_vars``
and asserting they are moved to ``encrypted_secrets`` and Fernet-decryptable.

We run ``upgrade()`` + ``downgrade()`` against the live schema (already at
``head``). The migration is idempotent per-container — if any row already
has an ``encrypted_secrets`` entry for a key we insert, the backfill will
overwrite it, which is acceptable for the test.
"""

from __future__ import annotations

import base64
import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text


def _insert_legacy_container(
    conn,
    owner_id: UUID,
    team_id: UUID,
    *,
    secret_plaintext: str,
) -> tuple[UUID, UUID]:
    project_id = uuid4()
    container_id = uuid4()
    slug = f"migtest-{uuid4().hex[:6]}"

    conn.execute(
        text(
            "INSERT INTO projects (id, name, slug, owner_id, team_id) "
            "VALUES (:id, :name, :slug, :owner, :team)"
        ),
        {
            "id": project_id,
            "name": "migration-test",
            "slug": slug,
            "owner": owner_id,
            "team": team_id,
        },
    )

    legacy_b64 = base64.b64encode(secret_plaintext.encode()).decode()
    env_vars_json = json.dumps(
        {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_ANON_KEY": legacy_b64}
    )

    conn.execute(
        text(
            "INSERT INTO containers "
            "(id, project_id, name, directory, container_name, "
            "container_type, service_slug, deployment_mode, environment_vars) "
            "VALUES (:id, :pid, 'supabase', '.', :cname, 'service', "
            "'supabase', 'external', CAST(:env AS JSONB))"
        ),
        {
            "id": container_id,
            "pid": project_id,
            "cname": f"{slug}-supabase",
            "env": env_vars_json,
        },
    )
    return project_id, container_id


@pytest.mark.integration
def test_backfill_upgrade_moves_base64_secrets_to_encrypted_secrets(authenticated_client):
    import asyncio

    from sqlalchemy import create_engine
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    _, user_data = authenticated_client
    owner_id = UUID(user_data["id"])

    # Fetch the team id on an async loop (schema uses asyncpg-only URL)
    loop = asyncio.new_event_loop()

    async def _get_team_id() -> UUID:
        from sqlalchemy import select

        from app.models_team import TeamMembership

        engine = create_async_engine(
            "postgresql+asyncpg://tesslate_test:testpass@localhost:5433/tesslate_test",
            pool_pre_ping=True,
        )
        Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with Session() as db:
            tm = (
                await db.execute(
                    select(TeamMembership).where(TeamMembership.user_id == owner_id).limit(1)
                )
            ).scalar_one()
        await engine.dispose()
        return tm.team_id

    try:
        team_id = loop.run_until_complete(_get_team_id())
    finally:
        loop.close()

    # Use a sync engine (no asyncpg) — the migration's bind is sync.
    sync_url = "postgresql://tesslate_test:testpass@localhost:5433/tesslate_test"
    try:
        sync_engine = create_engine(sync_url)
    except Exception:
        pytest.skip("no sync postgres driver available (psycopg2)")

    secret_plaintext = "legacy-supabase-anon-value-zzz"

    with sync_engine.connect() as conn:
        trans = conn.begin()
        try:
            project_id, container_id = _insert_legacy_container(
                conn, owner_id, team_id, secret_plaintext=secret_plaintext
            )
            conn.commit()
        except Exception:
            trans.rollback()
            raise

    # Directly invoke the migration's upgrade body via alembic's op context.
    # Simpler: call the SQL logic the migration would execute. We reuse the
    # migration module's helpers so regex + encrypt semantics match exactly.
    # Migration file is under alembic/versions/ which isn't a package — load
    # by path.
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    mig_path = (
        Path(__file__).parent.parent.parent
        / "alembic"
        / "versions"
        / "0061_backfill_container_secrets.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0061_backfill", str(mig_path))
    assert spec and spec.loader
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)

    with sync_engine.connect() as conn:
        ctx = MigrationContext.configure(connection=conn)
        with Operations.context(ctx):
            mig.upgrade()
        conn.commit()

    # Verify the row: base64 key moved, plaintext recoverable via Fernet
    from app.services.deployment_encryption import get_deployment_encryption_service

    enc = get_deployment_encryption_service()

    with sync_engine.connect() as conn:
        row = conn.execute(
            text("SELECT environment_vars, encrypted_secrets FROM containers WHERE id = :id"),
            {"id": container_id},
        ).one()

    env_vars = row._mapping["environment_vars"] or {}
    encrypted = row._mapping["encrypted_secrets"] or {}

    assert "SUPABASE_ANON_KEY" not in env_vars, (
        f"secret should have been moved out of environment_vars, got {env_vars}"
    )
    assert env_vars.get("SUPABASE_URL") == "https://x.supabase.co"
    assert "SUPABASE_ANON_KEY" in encrypted
    assert enc.decrypt(encrypted["SUPABASE_ANON_KEY"]) == secret_plaintext

    # Downgrade reverts (secret re-encoded as base64 in environment_vars)
    with sync_engine.connect() as conn:
        ctx = MigrationContext.configure(connection=conn)
        with Operations.context(ctx):
            mig.downgrade()
        conn.commit()

    with sync_engine.connect() as conn:
        row = conn.execute(
            text("SELECT environment_vars, encrypted_secrets FROM containers WHERE id = :id"),
            {"id": container_id},
        ).one()

    env_vars2 = row._mapping["environment_vars"] or {}
    encrypted2 = row._mapping["encrypted_secrets"]

    assert encrypted2 in (None, {}), (
        f"encrypted_secrets should be cleared after downgrade, got {encrypted2}"
    )
    # Round-trip: base64 decode yields original plaintext
    assert "SUPABASE_ANON_KEY" in env_vars2
    assert base64.b64decode(env_vars2["SUPABASE_ANON_KEY"]).decode() == secret_plaintext

    # Cleanup
    with sync_engine.connect() as conn:
        conn.execute(text("DELETE FROM containers WHERE id = :id"), {"id": container_id})
        conn.execute(text("DELETE FROM projects WHERE id = :id"), {"id": project_id})
        conn.commit()

    sync_engine.dispose()
