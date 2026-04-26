"""Tests for the App Composition runtime (Phase 3).

Covered:
  * dispatch_via_link with action in granted_actions → succeeds, calls
    dispatch_app_action with the child install id.
  * dispatch_via_link with action NOT in granted_actions → ActionNotInGrants.
  * dispatch_via_link with no link for the alias → AliasNotFound.
  * mint_embed_token + verify_embed_token round-trip.
  * mint_embed_token with view NOT in granted_views → ViewNotInGrants.
  * Expired token → verify_embed_token raises EmbedTokenInvalid.
  * Tampered token → verify_embed_token raises EmbedTokenInvalid.
  * query_data_resource with cache_ttl > 0: 1st call hits dispatcher,
    2nd call hits cache.
  * query_data_resource with force_refresh=True bypasses the cache and
    re-dispatches.
  * wire_install_links creates correct positive-list grants from
    manifest.dependencies[].needs.
  * wire_install_links raises MissingDependencyError for required deps
    that aren't installed; silently skips optional ones.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Importing models + models_automations registers all tables on Base.metadata.
from app import models, models_automations  # noqa: F401
from app.database import Base
from app.models_automations import (
    AppAction,
    AppDataResource,
    AppEmbed,
    AppInstance,
    AppInstanceLink,
)
from app.services.apps import composition
from app.services.apps.action_dispatcher import ActionDispatchResult
from app.services.apps.app_manifest import (
    AppManifest2026_05,
    DependencyNeedsSpec,
    DependencySpec,
)
from app.services.apps.embed_token import (
    EmbedTokenInvalid,
    sign_embed_token,
    verify_embed_token,
)


# ---------------------------------------------------------------------------
# Fixtures — fresh in-memory SQLite per test.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    """Per-test SQLite engine + session with the full app schema."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


# ---------------------------------------------------------------------------
# Seed helpers — minimal users / apps / installs.
# ---------------------------------------------------------------------------


async def _seed_user(db: AsyncSession, suffix: str) -> models.User:
    suffix = f"{suffix}-{uuid.uuid4().hex[:6]}"
    user = models.User(
        id=uuid.uuid4(),
        email=f"u-{suffix}@example.com",
        hashed_password="x",
        is_active=True,
        is_verified=True,
        is_superuser=False,
        name=f"User {suffix}",
        username=f"user-{suffix}",
        slug=f"user-{suffix}",
    )
    db.add(user)
    await db.flush()
    return user


async def _seed_app_install(
    db: AsyncSession,
    *,
    creator_user_id: UUID,
    app_slug: str = "child-app",
    actions: list[dict[str, Any]] | None = None,
    data_resources: list[dict[str, Any]] | None = None,
) -> tuple[models.MarketplaceApp, models.AppVersion, AppInstance]:
    """Create a marketplace app + version + an installed AppInstance.

    The AppVersion carries a minimal 2026-05 manifest so the dispatcher's
    tenancy check passes (default per_install). Actions are also written
    as AppAction projection rows so the dispatcher's _load_app_action
    lookup succeeds.
    """
    app = models.MarketplaceApp(
        id=uuid.uuid4(),
        slug=app_slug + "-" + uuid.uuid4().hex[:6],
        name=f"App {app_slug}",
        creator_user_id=creator_user_id,
    )
    db.add(app)
    av = models.AppVersion(
        id=uuid.uuid4(),
        app_id=app.id,
        version="1.0.0",
        manifest_schema_version="2026-05",
        manifest_json={
            "manifest_schema_version": "2026-05",
            "app": {
                "id": f"com.example.{app_slug}",
                "name": app_slug,
                "slug": app.slug,
                "version": "1.0.0",
            },
            "runtime": {
                "tenancy_model": "per_install",
                "state_model": "stateless",
            },
            "billing": {
                "ai_compute": {"payer_default": "installer"},
                "general_compute": {"payer_default": "installer"},
                "platform_fee": {"model": "free", "rate_percent": 0, "price_usd": 0},
            },
        },
        manifest_hash="hash-" + uuid.uuid4().hex,
        feature_set_hash="fs-" + uuid.uuid4().hex,
    )
    db.add(av)
    await db.flush()

    # Action projection rows so the dispatcher can resolve names.
    action_id_by_name: dict[str, UUID] = {}
    for spec in actions or []:
        row = AppAction(
            id=uuid.uuid4(),
            app_version_id=av.id,
            name=spec["name"],
            handler=spec.get("handler") or {"kind": "http_post", "path": "/"},
            input_schema=spec.get("input_schema"),
            output_schema=spec.get("output_schema"),
        )
        db.add(row)
        await db.flush()
        action_id_by_name[spec["name"]] = row.id

    # Data resource projections — backed_by_action_id resolves through the
    # action map above.
    for spec in data_resources or []:
        backing_id = action_id_by_name.get(spec["backed_by_action"])
        assert backing_id is not None, (
            f"data resource {spec['name']!r} references unknown action "
            f"{spec['backed_by_action']!r} — fix the test fixture"
        )
        db.add(
            AppDataResource(
                id=uuid.uuid4(),
                app_version_id=av.id,
                name=spec["name"],
                backed_by_action_id=backing_id,
                schema=spec.get("schema") or {"type": "object"},
                cache_ttl_seconds=spec.get("cache_ttl_seconds", 0),
            )
        )

    instance = AppInstance(
        id=uuid.uuid4(),
        app_id=app.id,
        app_version_id=av.id,
        installer_user_id=creator_user_id,
        state="installed",
    )
    db.add(instance)
    await db.flush()
    return app, av, instance


async def _seed_link(
    db: AsyncSession,
    *,
    parent_install: AppInstance,
    child_install: AppInstance,
    alias: str = "crm",
    granted_actions: list[str] | None = None,
    granted_views: list[str] | None = None,
    granted_data_resources: list[str] | None = None,
) -> AppInstanceLink:
    link = AppInstanceLink(
        id=uuid.uuid4(),
        parent_install_id=parent_install.id,
        child_install_id=child_install.id,
        alias=alias,
        granted_actions=granted_actions or [],
        granted_views=granted_views or [],
        granted_data_resources=granted_data_resources or [],
    )
    db.add(link)
    await db.flush()
    return link


# ---------------------------------------------------------------------------
# Dispatcher stub — replaces action_dispatcher.dispatch_app_action.
# ---------------------------------------------------------------------------


class _DispatchRecorder:
    """Captures (instance_id, action_name, input, run_id) per dispatch."""

    def __init__(self, output: dict[str, Any] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.output = output if output is not None else {"hello": "world"}

    async def __call__(
        self,
        db: AsyncSession,
        *,
        app_instance_id: UUID,
        action_name: str,
        input: dict[str, Any],
        run_id: UUID | None = None,
        invocation_subject_id: UUID | None = None,
    ) -> ActionDispatchResult:
        self.calls.append(
            {
                "app_instance_id": app_instance_id,
                "action_name": action_name,
                "input": input,
                "run_id": run_id,
            }
        )
        return ActionDispatchResult(
            output=self.output,
            artifacts=[],
            spend_usd=0,  # type: ignore[arg-type]
            duration_seconds=0.0,
            error=None,
        )


# ---------------------------------------------------------------------------
# dispatch_via_link tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_via_link_succeeds_when_action_in_grants(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _seed_user(db, "alice")
    _, _, parent = await _seed_app_install(
        db, creator_user_id=user.id, app_slug="dashboard"
    )
    _, _, child = await _seed_app_install(
        db,
        creator_user_id=user.id,
        app_slug="crm",
        actions=[{"name": "list_accounts"}, {"name": "delete_account"}],
    )
    await _seed_link(
        db,
        parent_install=parent,
        child_install=child,
        alias="crm",
        granted_actions=["list_accounts"],
    )

    recorder = _DispatchRecorder(output={"accounts": [{"id": "1"}]})
    monkeypatch.setattr(
        composition.action_dispatcher, "dispatch_app_action", recorder
    )

    result = await composition.dispatch_via_link(
        db,
        parent_install_id=parent.id,
        alias="crm",
        action_name="list_accounts",
        input={"team_id": "abc"},
        parent_run_id=None,
    )

    assert len(recorder.calls) == 1
    call = recorder.calls[0]
    assert call["app_instance_id"] == child.id
    assert call["action_name"] == "list_accounts"
    assert call["input"] == {"team_id": "abc"}
    assert result.output == {"accounts": [{"id": "1"}]}


@pytest.mark.asyncio
async def test_dispatch_via_link_rejects_action_not_in_grants(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _seed_user(db, "alice")
    _, _, parent = await _seed_app_install(
        db, creator_user_id=user.id, app_slug="dashboard"
    )
    _, _, child = await _seed_app_install(
        db,
        creator_user_id=user.id,
        app_slug="crm",
        actions=[{"name": "list_accounts"}, {"name": "delete_account"}],
    )
    await _seed_link(
        db,
        parent_install=parent,
        child_install=child,
        alias="crm",
        granted_actions=["list_accounts"],  # delete_account NOT included
    )

    recorder = _DispatchRecorder()
    monkeypatch.setattr(
        composition.action_dispatcher, "dispatch_app_action", recorder
    )

    with pytest.raises(composition.ActionNotInGrants):
        await composition.dispatch_via_link(
            db,
            parent_install_id=parent.id,
            alias="crm",
            action_name="delete_account",
            input={},
        )

    # The dispatcher must NOT have been called — the gate fires first.
    assert recorder.calls == []


@pytest.mark.asyncio
async def test_dispatch_via_link_unknown_alias_raises_alias_not_found(
    db: AsyncSession,
) -> None:
    user = await _seed_user(db, "alice")
    _, _, parent = await _seed_app_install(
        db, creator_user_id=user.id, app_slug="dashboard"
    )

    with pytest.raises(composition.AliasNotFound):
        await composition.dispatch_via_link(
            db,
            parent_install_id=parent.id,
            alias="nonexistent",
            action_name="anything",
            input={},
        )


@pytest.mark.asyncio
async def test_dispatch_via_link_ignores_revoked_links(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A revoked link is invisible to the runtime."""
    user = await _seed_user(db, "alice")
    _, _, parent = await _seed_app_install(
        db, creator_user_id=user.id, app_slug="dashboard"
    )
    _, _, child = await _seed_app_install(
        db,
        creator_user_id=user.id,
        app_slug="crm",
        actions=[{"name": "list_accounts"}],
    )
    link = await _seed_link(
        db,
        parent_install=parent,
        child_install=child,
        alias="crm",
        granted_actions=["list_accounts"],
    )
    composition.revoke_link(link)
    await db.flush()

    with pytest.raises(composition.AliasNotFound):
        await composition.dispatch_via_link(
            db,
            parent_install_id=parent.id,
            alias="crm",
            action_name="list_accounts",
            input={},
        )


# ---------------------------------------------------------------------------
# Embed token tests
# ---------------------------------------------------------------------------


def test_embed_token_round_trip() -> None:
    parent_id = uuid.uuid4()
    child_id = uuid.uuid4()
    token = sign_embed_token(
        parent_install_id=parent_id,
        child_install_id=child_id,
        view_name="account_card",
        input={"account_id": "1234"},
        ttl_seconds=300,
        scopes_granted=["account_card"],
    )
    claims = verify_embed_token(token)
    assert claims["sub"] == str(child_id)
    assert claims["parent_install_id"] == str(parent_id)
    assert claims["view_name"] == "account_card"
    assert claims["input"] == {"account_id": "1234"}
    assert "account_card" in claims["scopes_granted"]


def test_embed_token_expired_raises() -> None:
    """Sign a token whose ``exp`` is already in the past, then verify.

    Going through the public ``sign_embed_token`` API would forbid a
    negative ttl, so we directly call jwt.encode with a backdated ``exp``.
    This sidesteps wall-clock race conditions entirely.
    """
    from jose import jwt

    from app.services.apps.embed_token import _signing_secret

    parent_id = uuid.uuid4()
    child_id = uuid.uuid4()
    now = int(time.time())
    backdated_claims = {
        "iss": "opensail-runtime",
        "sub": str(child_id),
        "aud": str(child_id),
        "iat": now - 600,
        "exp": now - 60,  # Already expired by 60s — no race possible.
        "parent_install_id": str(parent_id),
        "view_name": "account_card",
        "input": {},
        "scopes_granted": [],
    }
    token = jwt.encode(backdated_claims, _signing_secret(), algorithm="HS256")

    with pytest.raises(EmbedTokenInvalid):
        verify_embed_token(token)


def test_embed_token_tampered_raises() -> None:
    parent_id = uuid.uuid4()
    child_id = uuid.uuid4()
    token = sign_embed_token(
        parent_install_id=parent_id,
        child_install_id=child_id,
        view_name="account_card",
        input={},
        ttl_seconds=300,
    )
    # Flip a character in the signature segment (the third dot-separated part).
    parts = token.split(".")
    assert len(parts) == 3
    sig = list(parts[2])
    sig[0] = "A" if sig[0] != "A" else "B"
    tampered = ".".join(parts[:2] + ["".join(sig)])

    with pytest.raises(EmbedTokenInvalid):
        verify_embed_token(tampered)


@pytest.mark.asyncio
async def test_mint_embed_token_rejects_view_not_in_grants(
    db: AsyncSession,
) -> None:
    user = await _seed_user(db, "alice")
    _, _, parent = await _seed_app_install(
        db, creator_user_id=user.id, app_slug="dashboard"
    )
    _, _, child = await _seed_app_install(
        db, creator_user_id=user.id, app_slug="crm"
    )
    await _seed_link(
        db,
        parent_install=parent,
        child_install=child,
        alias="crm",
        granted_views=["account_card"],
    )

    with pytest.raises(composition.ViewNotInGrants):
        await composition.mint_embed_token(
            db,
            parent_install_id=parent.id,
            alias="crm",
            view_name="pipeline_chart",  # not granted
            input={},
            ttl_seconds=60,
        )


@pytest.mark.asyncio
async def test_mint_embed_token_succeeds_for_granted_view(
    db: AsyncSession,
) -> None:
    user = await _seed_user(db, "alice")
    _, _, parent = await _seed_app_install(
        db, creator_user_id=user.id, app_slug="dashboard"
    )
    _, _, child = await _seed_app_install(
        db, creator_user_id=user.id, app_slug="crm"
    )
    await _seed_link(
        db,
        parent_install=parent,
        child_install=child,
        alias="crm",
        granted_views=["account_card"],
    )

    token = await composition.mint_embed_token(
        db,
        parent_install_id=parent.id,
        alias="crm",
        view_name="account_card",
        input={"account_id": "1234"},
        ttl_seconds=120,
    )
    claims = verify_embed_token(token)
    assert claims["view_name"] == "account_card"
    assert claims["sub"] == str(child.id)
    assert claims["parent_install_id"] == str(parent.id)
    assert claims["input"] == {"account_id": "1234"}


# ---------------------------------------------------------------------------
# Data resource cache tests
# ---------------------------------------------------------------------------


class _MemoryCacheRedis:
    """Minimal in-memory stand-in for the Redis client.

    Provides ``get`` and ``set(..., ex=...)`` — the only two methods
    composition._cache_get / _cache_set use. TTL is intentionally NOT
    enforced here because the test paths are short-lived; correctness
    of TTL eviction is Redis's problem, not ours.
    """

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.set_calls: list[tuple[str, str, int]] = []
        self.get_calls: list[str] = []

    async def get(self, key: str) -> str | None:
        self.get_calls.append(key)
        return self.store.get(key)

    async def set(self, key: str, value: str, *, ex: int | None = None) -> None:
        self.set_calls.append((key, value, ex or 0))
        self.store[key] = value


@pytest.mark.asyncio
async def test_query_data_resource_caches_on_second_call(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _seed_user(db, "alice")
    _, _, parent = await _seed_app_install(
        db, creator_user_id=user.id, app_slug="dashboard"
    )
    _, _, child = await _seed_app_install(
        db,
        creator_user_id=user.id,
        app_slug="crm",
        actions=[{"name": "list_accounts"}],
        data_resources=[
            {
                "name": "accounts",
                "backed_by_action": "list_accounts",
                "cache_ttl_seconds": 60,
            }
        ],
    )
    await _seed_link(
        db,
        parent_install=parent,
        child_install=child,
        alias="crm",
        granted_data_resources=["accounts"],
    )

    recorder = _DispatchRecorder(output={"accounts": [{"id": "a1"}]})
    monkeypatch.setattr(
        composition.action_dispatcher, "dispatch_app_action", recorder
    )

    fake_redis = _MemoryCacheRedis()

    async def _fake_get_redis():
        return fake_redis

    monkeypatch.setattr(
        "app.services.cache_service.get_redis_client", _fake_get_redis
    )

    # 1st call — dispatcher hit + cache write.
    out1 = await composition.query_data_resource(
        db,
        parent_install_id=parent.id,
        alias="crm",
        resource_name="accounts",
        input={"team_id": "abc"},
    )
    assert out1 == {"accounts": [{"id": "a1"}]}
    assert len(recorder.calls) == 1
    assert len(fake_redis.set_calls) == 1

    # 2nd call (same input) — must hit cache, NOT dispatcher.
    out2 = await composition.query_data_resource(
        db,
        parent_install_id=parent.id,
        alias="crm",
        resource_name="accounts",
        input={"team_id": "abc"},
    )
    assert out2 == {"accounts": [{"id": "a1"}]}
    assert len(recorder.calls) == 1, (
        "second call should have hit the cache, not the dispatcher"
    )


@pytest.mark.asyncio
async def test_query_data_resource_force_refresh_bypasses_cache(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _seed_user(db, "alice")
    _, _, parent = await _seed_app_install(
        db, creator_user_id=user.id, app_slug="dashboard"
    )
    _, _, child = await _seed_app_install(
        db,
        creator_user_id=user.id,
        app_slug="crm",
        actions=[{"name": "list_accounts"}],
        data_resources=[
            {
                "name": "accounts",
                "backed_by_action": "list_accounts",
                "cache_ttl_seconds": 60,
            }
        ],
    )
    await _seed_link(
        db,
        parent_install=parent,
        child_install=child,
        alias="crm",
        granted_data_resources=["accounts"],
    )

    recorder = _DispatchRecorder(output={"v": 1})
    monkeypatch.setattr(
        composition.action_dispatcher, "dispatch_app_action", recorder
    )

    fake_redis = _MemoryCacheRedis()

    async def _fake_get_redis():
        return fake_redis

    monkeypatch.setattr(
        "app.services.cache_service.get_redis_client", _fake_get_redis
    )

    # Prime the cache.
    await composition.query_data_resource(
        db,
        parent_install_id=parent.id,
        alias="crm",
        resource_name="accounts",
        input={},
    )
    assert len(recorder.calls) == 1

    # force_refresh=True must bypass the cache.
    await composition.query_data_resource(
        db,
        parent_install_id=parent.id,
        alias="crm",
        resource_name="accounts",
        input={},
        force_refresh=True,
    )
    assert len(recorder.calls) == 2


@pytest.mark.asyncio
async def test_query_data_resource_rejects_resource_not_in_grants(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _seed_user(db, "alice")
    _, _, parent = await _seed_app_install(
        db, creator_user_id=user.id, app_slug="dashboard"
    )
    _, _, child = await _seed_app_install(
        db,
        creator_user_id=user.id,
        app_slug="crm",
        actions=[{"name": "list_accounts"}],
        data_resources=[
            {
                "name": "accounts",
                "backed_by_action": "list_accounts",
                "cache_ttl_seconds": 0,
            }
        ],
    )
    # Empty granted_data_resources — composition should reject.
    await _seed_link(
        db,
        parent_install=parent,
        child_install=child,
        alias="crm",
        granted_data_resources=[],
    )

    recorder = _DispatchRecorder()
    monkeypatch.setattr(
        composition.action_dispatcher, "dispatch_app_action", recorder
    )

    with pytest.raises(composition.DataResourceNotInGrants):
        await composition.query_data_resource(
            db,
            parent_install_id=parent.id,
            alias="crm",
            resource_name="accounts",
            input={},
        )
    assert recorder.calls == []


# ---------------------------------------------------------------------------
# wire_install_links tests
# ---------------------------------------------------------------------------


def _minimal_2026_05_manifest_with_dep(
    *,
    parent_slug: str,
    child_slug: str,
    alias: str,
    needs_actions: list[str],
    needs_views: list[str],
    needs_data_resources: list[str],
    required: bool = True,
) -> AppManifest2026_05:
    return AppManifest2026_05(
        manifest_schema_version="2026-05",
        app={
            "id": f"com.example.{parent_slug}",
            "name": parent_slug,
            "slug": parent_slug,
            "version": "1.0.0",
        },
        runtime={"tenancy_model": "per_install", "state_model": "stateless"},
        billing={
            "ai_compute": {"payer_default": "installer"},
            "general_compute": {"payer_default": "installer"},
            "platform_fee": {"model": "free", "rate_percent": 0, "price_usd": 0},
        },
        dependencies=[
            DependencySpec(
                alias=alias,
                app_id=child_slug,
                required=required,
                needs=DependencyNeedsSpec(
                    actions=needs_actions,
                    views=needs_views,
                    data_resources=needs_data_resources,
                ),
            )
        ],
    )


@pytest.mark.asyncio
async def test_wire_install_links_writes_positive_grants(
    db: AsyncSession,
) -> None:
    user = await _seed_user(db, "alice")
    _, _, parent = await _seed_app_install(
        db, creator_user_id=user.id, app_slug="dashboard"
    )
    child_app, _, child = await _seed_app_install(
        db, creator_user_id=user.id, app_slug="crm"
    )
    parent_manifest = _minimal_2026_05_manifest_with_dep(
        parent_slug="dashboard",
        child_slug=child_app.slug,
        alias="crm",
        needs_actions=["list_accounts", "summarize_pipeline"],
        needs_views=["account_card"],
        needs_data_resources=["accounts"],
    )

    written = await composition.wire_install_links(
        db,
        parent_install=parent,
        parent_manifest=parent_manifest,
        child_installs_by_app_id={child_app.slug: child.id},
    )

    assert len(written) == 1
    link = written[0]
    assert link.parent_install_id == parent.id
    assert link.child_install_id == child.id
    assert link.alias == "crm"
    assert sorted(link.granted_actions) == sorted(
        ["list_accounts", "summarize_pipeline"]
    )
    assert link.granted_views == ["account_card"]
    assert link.granted_data_resources == ["accounts"]


@pytest.mark.asyncio
async def test_wire_install_links_raises_for_required_missing_dep(
    db: AsyncSession,
) -> None:
    user = await _seed_user(db, "alice")
    _, _, parent = await _seed_app_install(
        db, creator_user_id=user.id, app_slug="dashboard"
    )
    child_app, _, _ = await _seed_app_install(
        db, creator_user_id=user.id, app_slug="crm"
    )
    parent_manifest = _minimal_2026_05_manifest_with_dep(
        parent_slug="dashboard",
        child_slug=child_app.slug,
        alias="crm",
        needs_actions=["list_accounts"],
        needs_views=[],
        needs_data_resources=[],
        required=True,
    )

    # Resolver returns empty — no install for child_app.slug.
    with pytest.raises(composition.MissingDependencyError):
        await composition.wire_install_links(
            db,
            parent_install=parent,
            parent_manifest=parent_manifest,
            child_installs_by_app_id={},
        )


@pytest.mark.asyncio
async def test_wire_install_links_skips_optional_missing_dep(
    db: AsyncSession,
) -> None:
    user = await _seed_user(db, "alice")
    _, _, parent = await _seed_app_install(
        db, creator_user_id=user.id, app_slug="dashboard"
    )
    child_app, _, _ = await _seed_app_install(
        db, creator_user_id=user.id, app_slug="support"
    )
    parent_manifest = _minimal_2026_05_manifest_with_dep(
        parent_slug="dashboard",
        child_slug=child_app.slug,
        alias="support",
        needs_actions=["summarize_tickets"],
        needs_views=[],
        needs_data_resources=[],
        required=False,
    )

    written = await composition.wire_install_links(
        db,
        parent_install=parent,
        parent_manifest=parent_manifest,
        child_installs_by_app_id={},
    )

    # Optional + missing → silently skipped, no row.
    assert written == []
    rows = (
        await db.execute(
            select(AppInstanceLink).where(
                AppInstanceLink.parent_install_id == parent.id
            )
        )
    ).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_wire_install_links_is_idempotent_on_repeat(
    db: AsyncSession,
) -> None:
    """Second call with new grants UPDATES the row instead of duplicating."""
    user = await _seed_user(db, "alice")
    _, _, parent = await _seed_app_install(
        db, creator_user_id=user.id, app_slug="dashboard"
    )
    child_app, _, child = await _seed_app_install(
        db, creator_user_id=user.id, app_slug="crm"
    )
    manifest_v1 = _minimal_2026_05_manifest_with_dep(
        parent_slug="dashboard",
        child_slug=child_app.slug,
        alias="crm",
        needs_actions=["list_accounts"],
        needs_views=[],
        needs_data_resources=[],
    )
    await composition.wire_install_links(
        db,
        parent_install=parent,
        parent_manifest=manifest_v1,
        child_installs_by_app_id={child_app.slug: child.id},
    )

    manifest_v2 = _minimal_2026_05_manifest_with_dep(
        parent_slug="dashboard",
        child_slug=child_app.slug,
        alias="crm",
        needs_actions=["list_accounts", "summarize_pipeline"],
        needs_views=["account_card"],
        needs_data_resources=[],
    )
    await composition.wire_install_links(
        db,
        parent_install=parent,
        parent_manifest=manifest_v2,
        child_installs_by_app_id={child_app.slug: child.id},
    )

    rows = (
        await db.execute(
            select(AppInstanceLink).where(
                AppInstanceLink.parent_install_id == parent.id
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    refreshed = rows[0]
    assert sorted(refreshed.granted_actions) == sorted(
        ["list_accounts", "summarize_pipeline"]
    )
    assert refreshed.granted_views == ["account_card"]
