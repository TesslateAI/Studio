"""Tests for the unified workspace-data env-injection resolver.

Covers ``services/workspace_data_env.py`` — the single source of truth for
computing OPENSAIL_DATA_* env maps shared by the external-deploy injector
and in-cluster container startup.

Key boundaries exercised:
  * Empty-project: no env when there are no collections AND no overrides
  * Default key strategy is ``autoinject`` (stable; passes 100x without blowing the cap)
  * Override URL / key honoured
  * compute_env_for_containers: graph wiring drives per-container output
  * compute_env_for_containers: blanket fallback for unwired containers
  * compute_env_for_containers: env_mapping rename ON TOP of canonical names
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def _alembic_cfg() -> Config:
    orchestrator_dir = Path(__file__).resolve().parents[2]
    cfg = Config(str(orchestrator_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(orchestrator_dir / "alembic"))
    return cfg


@pytest.fixture
def maker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    url = f"sqlite+aiosqlite:///{tmp_path / 'wsdata_env.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("SECRET_KEY", "test-secret-for-env-resolver")
    monkeypatch.setenv("APP_DOMAIN", "test.example.com")
    from app.config import get_settings

    get_settings.cache_clear()
    orchestrator_dir = Path(__file__).resolve().parents[2]
    original = os.getcwd()
    os.chdir(orchestrator_dir)
    try:
        command.upgrade(_alembic_cfg(), "head")
    finally:
        os.chdir(original)

    # SQLite quirk: migration 0063 creates a *partial* unique index
    # ``ix_containers_one_primary`` with ``postgresql_where=is_primary`` —
    # SQLite drops the WHERE clause and applies the unique constraint
    # globally, breaking any test that creates multiple containers per
    # project. Drop it so tests can mirror production behaviour.
    import sqlite3
    sqlite_path = str(tmp_path / "wsdata_env.db")
    with sqlite3.connect(sqlite_path) as raw:
        raw.execute("DROP INDEX IF EXISTS ix_containers_one_primary")

    engine = create_async_engine(url, future=True)

    @event.listens_for(engine.sync_engine, "connect")
    def _now(dbapi_conn, _record):
        dbapi_conn.create_function("now", 0, lambda: datetime.now(UTC).isoformat(sep=" "))

    yield async_sessionmaker(engine, expire_on_commit=False)
    get_settings.cache_clear()


async def _make_project(db) -> uuid.UUID:
    """Create a minimal Project — owner_id is the only field the resolver reads."""
    from app.models import Project

    project = Project(
        id=uuid.uuid4(),
        name="p",
        slug=f"p-{uuid.uuid4().hex[:8]}",
        owner_id=uuid.uuid4(),  # synthetic; resolver only reads ``.id`` and ``.owner_id``
    )
    db.add(project)
    await db.commit()
    return project.id


# --- resolve_workspace_data_env --------------------------------------------
async def test_no_collections_returns_empty(maker) -> None:
    from app.models import Project
    from app.services.workspace_data_env import resolve_workspace_data_env

    async with maker() as db:
        pid = await _make_project(db)
        project = await db.get(Project, pid)
        out = await resolve_workspace_data_env(db, project, user_id=project.owner_id)
    assert out == {}


async def test_collections_present_returns_full_contract(maker) -> None:
    from app.models import Project
    from app.services import workspace_data as wd
    from app.services.workspace_data_env import resolve_workspace_data_env

    async with maker() as db:
        pid = await _make_project(db)
        await wd.create_collection(db, pid, "subs")
        project = await db.get(Project, pid)
        out = await resolve_workspace_data_env(db, project, user_id=project.owner_id)

    # 3 prefixes × {URL, URL alias, KEY} = 9 keys
    assert len(out) == 9
    for prefix in ("OPENSAIL", "VITE_OPENSAIL", "NEXT_PUBLIC_OPENSAIL"):
        assert out[f"{prefix}_DATA_API_URL"].endswith("/api/data/v1")
        assert out[f"{prefix}_DATA_URL"] == out[f"{prefix}_DATA_API_URL"]
        assert out[f"{prefix}_DATA_KEY"].startswith("wsk_anon_")


async def test_default_strategy_is_autoinject_stable_under_load(maker) -> None:
    """Production hazard guard: 50 resolver calls must not mint 50 keys."""
    from app.models import Project
    from app.services import workspace_data as wd
    from app.services.workspace_data_env import resolve_workspace_data_env

    async with maker() as db:
        pid = await _make_project(db)
        await wd.create_collection(db, pid, "subs")
        project = await db.get(Project, pid)

        keys_seen = set()
        for _ in range(50):
            env = await resolve_workspace_data_env(db, project, user_id=project.owner_id)
            keys_seen.add(env["OPENSAIL_DATA_KEY"])

    assert len(keys_seen) == 1, f"autoinject must be stable; got {len(keys_seen)}"
    async with maker() as db:
        assert await wd.count_data_keys(db, pid) == 1


async def test_override_url_honoured(maker) -> None:
    from app.models import Project
    from app.services import workspace_data as wd
    from app.services.workspace_data_env import resolve_workspace_data_env

    async with maker() as db:
        pid = await _make_project(db)
        await wd.create_collection(db, pid, "subs")
        project = await db.get(Project, pid)
        out = await resolve_workspace_data_env(
            db, project, user_id=project.owner_id,
            override_url="https://other.example/api/data/v1",
        )
    assert out["OPENSAIL_DATA_API_URL"] == "https://other.example/api/data/v1"


async def test_override_key_honoured(maker) -> None:
    from app.models import Project
    from app.services import workspace_data as wd
    from app.services.workspace_data_env import resolve_workspace_data_env

    async with maker() as db:
        pid = await _make_project(db)
        await wd.create_collection(db, pid, "subs")
        project = await db.get(Project, pid)
        out = await resolve_workspace_data_env(
            db, project, user_id=project.owner_id,
            override_key="wsk_anon_user_supplied",
        )
    assert out["OPENSAIL_DATA_KEY"] == "wsk_anon_user_supplied"


async def test_skip_key_strategy_url_only(maker) -> None:
    from app.models import Project
    from app.services import workspace_data as wd
    from app.services.workspace_data_env import resolve_workspace_data_env

    async with maker() as db:
        pid = await _make_project(db)
        await wd.create_collection(db, pid, "subs")
        project = await db.get(Project, pid)
        out = await resolve_workspace_data_env(
            db, project, user_id=project.owner_id, key_strategy="skip_key",
        )
    assert "OPENSAIL_DATA_API_URL" in out
    assert "OPENSAIL_DATA_KEY" not in out


# --- compute_env_for_containers (graph-aware) -------------------------------
async def _make_base_container(db, project_id: uuid.UUID, name: str) -> uuid.UUID:
    from app.models import Container

    c = Container(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        directory=".",
        container_name=name,
        container_type="base",
        status="running",
        internal_port=3000,
    )
    db.add(c)
    await db.commit()
    return c.id


async def _wire_workspace_data_to(
    db, project_id: uuid.UUID, target_container_id: uuid.UUID, *, config: dict | None = None
) -> uuid.UUID:
    from app.models import Container, ContainerConnection

    src = Container(
        id=uuid.uuid4(),
        project_id=project_id,
        name="workspace-data",
        directory=".",
        container_name="workspace-data",
        container_type="service",
        service_slug="workspace-data",
        status="running",
    )
    db.add(src)
    await db.flush()
    db.add(ContainerConnection(
        id=uuid.uuid4(),
        project_id=project_id,
        source_container_id=src.id,
        target_container_id=target_container_id,
        connector_type="env_injection",
        config=config or {},
    ))
    await db.commit()
    return src.id


async def test_compute_env_empty_list_returns_empty(maker) -> None:
    from app.models import Project
    from app.services.workspace_data_env import compute_env_for_containers

    async with maker() as db:
        pid = await _make_project(db)
        project = await db.get(Project, pid)
        out = await compute_env_for_containers(db, project, [])
    assert out == {}


async def test_compute_env_graph_wired(maker) -> None:
    from app.models import Project
    from app.services import workspace_data as wd
    from app.services.workspace_data_env import compute_env_for_containers

    async with maker() as db:
        pid = await _make_project(db)
        await wd.create_collection(db, pid, "subs")
        target = await _make_base_container(db, pid, "web")
        await _wire_workspace_data_to(db, pid, target)
        project = await db.get(Project, pid)
        out = await compute_env_for_containers(db, project, [target], user_id=project.owner_id)

    assert target in out
    assert "OPENSAIL_DATA_API_URL" in out[target]
    assert out[target]["OPENSAIL_DATA_KEY"].startswith("wsk_anon_")


async def test_compute_env_fallback_for_unwired(maker) -> None:
    """Unwired container + collections exist + fallback on → blanket inject."""
    from app.models import Project
    from app.services import workspace_data as wd
    from app.services.workspace_data_env import compute_env_for_containers

    async with maker() as db:
        pid = await _make_project(db)
        await wd.create_collection(db, pid, "subs")
        target = await _make_base_container(db, pid, "web")
        project = await db.get(Project, pid)
        out = await compute_env_for_containers(db, project, [target], user_id=project.owner_id)

    assert out.get(target, {}).get("OPENSAIL_DATA_API_URL", "").endswith("/api/data/v1")


async def test_compute_env_fallback_disabled_skips(maker) -> None:
    from app.models import Project
    from app.services import workspace_data as wd
    from app.services.workspace_data_env import compute_env_for_containers

    async with maker() as db:
        pid = await _make_project(db)
        await wd.create_collection(db, pid, "subs")
        target = await _make_base_container(db, pid, "web")
        project = await db.get(Project, pid)
        out = await compute_env_for_containers(
            db, project, [target], user_id=project.owner_id, fallback_when_unwired=False,
        )
    assert out == {}


async def test_compute_env_env_mapping_rename_on_top(maker) -> None:
    """env_mapping adds aliases on top — canonical names still present."""
    from app.models import Project
    from app.services import workspace_data as wd
    from app.services.workspace_data_env import compute_env_for_containers

    async with maker() as db:
        pid = await _make_project(db)
        await wd.create_collection(db, pid, "subs")
        target = await _make_base_container(db, pid, "web")
        await _wire_workspace_data_to(
            db, pid, target,
            config={"env_mapping": {"MY_DATA_URL": "OPENSAIL_DATA_API_URL"}},
        )
        project = await db.get(Project, pid)
        out = await compute_env_for_containers(db, project, [target], user_id=project.owner_id)

    env = out[target]
    assert env["MY_DATA_URL"] == env["OPENSAIL_DATA_API_URL"]
    assert "VITE_OPENSAIL_DATA_API_URL" in env


async def test_compute_env_connection_override_url(maker) -> None:
    from app.models import Project
    from app.services import workspace_data as wd
    from app.services.workspace_data_env import compute_env_for_containers

    async with maker() as db:
        pid = await _make_project(db)
        await wd.create_collection(db, pid, "subs")
        target = await _make_base_container(db, pid, "web")
        await _wire_workspace_data_to(
            db, pid, target,
            config={"override_url": "https://other.example/api/data/v1"},
        )
        project = await db.get(Project, pid)
        out = await compute_env_for_containers(db, project, [target], user_id=project.owner_id)

    assert out[target]["OPENSAIL_DATA_API_URL"] == "https://other.example/api/data/v1"


async def test_compute_env_mixed_wired_and_unwired_share_key(maker) -> None:
    """One wired + one unwired: both get env; both see the SAME autoinject key."""
    from app.models import Project
    from app.services import workspace_data as wd
    from app.services.workspace_data_env import compute_env_for_containers

    async with maker() as db:
        pid = await _make_project(db)
        await wd.create_collection(db, pid, "subs")
        wired = await _make_base_container(db, pid, "web")
        unwired = await _make_base_container(db, pid, "admin")
        await _wire_workspace_data_to(db, pid, wired)
        project = await db.get(Project, pid)
        out = await compute_env_for_containers(
            db, project, [wired, unwired], user_id=project.owner_id,
        )

    assert wired in out and unwired in out
    assert out[wired]["OPENSAIL_DATA_KEY"] == out[unwired]["OPENSAIL_DATA_KEY"]


# --- materialiser shell-prefix ---------------------------------------------
def test_materialize_dotenv_local_command_shape() -> None:
    """Smoke: shell prefix targets .env.development.local + broad allowlist."""
    from app.services.base_config_parser import get_node_modules_fix_prefix

    prefix = get_node_modules_fix_prefix()
    assert ".env.development.local" in prefix
    # Must not own the user-visible filename
    assert ".env.local " not in prefix and ".env.local;" not in prefix
    # Broad allowlist covers all three public-env conventions
    assert "OPENSAIL_" in prefix
    assert "VITE_" in prefix
    assert "NEXT_PUBLIC_" in prefix
