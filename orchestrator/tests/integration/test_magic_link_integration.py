"""
Integration tests for the magic-link login flow.

Covers the three endpoints end-to-end:
  POST /api/auth/magic-link/request
  POST /api/auth/magic-link/consume
  POST /api/auth/magic-link/verify

Security focus:
  - Feature-flag gating (404 when disabled — no accidental exposure)
  - Enumeration prevention (unknown/inactive emails → still 200)
  - Rate limit (5 per 10 min → still 200, but email not actually sent)
  - Link + code converge on one row (consuming either invalidates both)
  - Expired / tampered / already-used tokens are rejected
  - Code attempt exhaustion invalidates the row
  - Refresh cookie + access token are issued on successful consume
  - OAuth-only (passwordless) users can sign in via magic link
  - CSRF middleware exempts magic-link POSTs (regression 2026-04-17)

All tests are SYNC (they drive the FastAPI TestClient, which has its own
internal event loop). Any DB setup/teardown that needs the async SQLAlchemy
stack is done via the _run() helper below, which opens a fresh NullPool
engine per call so connections don't leak across event loops.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth import get_password_hash
from app.config import get_settings
from app.models import EmailVerificationCode, User
from app.services import magic_link_service as mls
from app.services.feature_flags import FeatureFlags, get_feature_flags

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Async → sync bridge for DB setup/teardown.
#
# Each call opens a brand-new engine with NullPool, runs the coroutine, and
# disposes. Uses asyncio.run() so connections are bound to a disposable loop,
# avoiding "Future attached to a different loop" errors when mixed with the
# FastAPI TestClient's internal loop.
# ---------------------------------------------------------------------------


def _run(coro_fn):
    """Run an async callable that takes (db: AsyncSession) -> Any, sync-style."""
    settings = get_settings()

    async def _main():
        engine = create_async_engine(settings.database_url, poolclass=NullPool)
        sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with sm() as db:
                return await coro_fn(db)
        finally:
            await engine.dispose()

    return asyncio.run(_main())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _enable_magic_link_flag():
    real_ff = get_feature_flags()
    flags = dict(real_ff.flags)
    flags["magic_link_login"] = True
    patched = FeatureFlags(flags, list(flags.keys()), real_ff.env)
    with patch("app.routers.magic_link.get_feature_flags", return_value=patched):
        yield


@pytest.fixture(autouse=True)
def _stub_email_service():
    """Replace send_magic_link with an AsyncMock we can inspect synchronously.

    The router calls `asyncio.create_task(email_service.send_magic_link(...))`.
    `send_magic_link(...)` is invoked synchronously to *build* the coroutine,
    at which point AsyncMock records the call, even if the task body never
    runs. Tests assert against .call_count / .call_args rather than a
    side-effect capture that would depend on task scheduling.
    """
    with patch("app.routers.magic_link.get_email_service") as fake:
        stub = MagicMock()
        stub.send_magic_link = AsyncMock()
        fake.return_value = stub
        yield stub


@pytest.fixture
def make_user():
    """Factory for a persisted User. Sync — safe inside TestClient-based tests."""

    def _create(
        *,
        email: str | None = None,
        active: bool = True,
        has_password: bool = True,
    ) -> SimpleNamespace:
        email = email or f"ml-{uuid4().hex}@example.com"
        user_id = uuid4()

        # hashed_password is NOT NULL in the DB schema. OAuth-registered users
        # get an unverifiable placeholder from fastapi-users — simulate that
        # with an empty string when the test asks for a "passwordless" user.
        # The magic-link flow never consults this column, so the test still
        # proves the right thing: a user who doesn't know a password can
        # sign in via the emailed link.
        placeholder = "" if not has_password else get_password_hash("pw")

        async def _insert(db: AsyncSession):
            u = User(
                id=user_id,
                email=email,
                hashed_password=placeholder,
                is_active=active,
                is_verified=True,
                name="ML Test",
                username=f"ml-{uuid4().hex[:8]}",
                slug=f"ml-{uuid4().hex[:8]}",
            )
            db.add(u)
            await db.commit()

        _run(_insert)
        # Return a plain namespace — avoids ORM session attachment across loops.
        return SimpleNamespace(id=user_id, email=email)

    return _create


def _create_magic_link(user_id: UUID) -> tuple[str, str]:
    """Create a magic-link record directly (bypasses /request so tests don't
    need to decrypt the AsyncMock call_args each time)."""

    async def _do(db: AsyncSession):
        result = await mls.create_magic_link(db, user_id)
        await db.commit()
        return result

    return _run(_do)


def _expire_rows_for(user_id: UUID) -> None:
    async def _do(db: AsyncSession):
        await db.execute(
            update(EmailVerificationCode)
            .where(EmailVerificationCode.user_id == user_id)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await db.commit()

    _run(_do)


def _deactivate_user(user_id: UUID) -> None:
    async def _do(db: AsyncSession):
        await db.execute(update(User).where(User.id == user_id).values(is_active=False))
        await db.commit()

    _run(_do)


def _count_unused_rows(user_id: UUID) -> int:
    async def _do(db: AsyncSession):
        result = await db.execute(
            select(EmailVerificationCode).where(
                EmailVerificationCode.user_id == user_id,
                EmailVerificationCode.purpose == mls.PURPOSE,
                EmailVerificationCode.used == False,  # noqa: E712
            )
        )
        return len(result.scalars().all())

    return _run(_do)


def _set_cookie_has(resp, name: str) -> bool:
    """True if the response emits a Set-Cookie header setting `name`.

    TestClient runs against http://test but cookies are issued with
    Secure=True (prod default). httpx's cookie jar silently drops Secure
    cookies on http, so resp.cookies looks empty. Parse the raw header
    to see what the server actually emitted.
    """
    raw = resp.headers.raw  # list[tuple[bytes, bytes]]
    key = b"set-cookie"
    prefix = name.encode() + b"="
    return any(k.lower() == key and v.startswith(prefix) for k, v in raw)


# ===========================================================================
# /request
# ===========================================================================


class TestRequest:
    def test_returns_200_for_known_user_and_emails(
        self, api_client, make_user, _stub_email_service
    ):
        user = make_user()
        resp = api_client.post("/api/auth/magic-link/request", json={"email": user.email})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

        assert _stub_email_service.send_magic_link.call_count == 1
        args, _kwargs = _stub_email_service.send_magic_link.call_args
        to_email, link_url, code = args
        assert to_email == user.email
        assert "/auth/magic?token=" in link_url
        assert code.isdigit() and len(code) == 6

    def test_unknown_email_returns_200_and_does_not_email(self, api_client, _stub_email_service):
        resp = api_client.post(
            "/api/auth/magic-link/request",
            json={"email": f"ghost-{uuid4().hex}@example.com"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert _stub_email_service.send_magic_link.call_count == 0

    def test_inactive_user_returns_200_and_does_not_email(
        self, api_client, make_user, _stub_email_service
    ):
        user = make_user(active=False)
        resp = api_client.post("/api/auth/magic-link/request", json={"email": user.email})
        assert resp.status_code == 200
        assert _stub_email_service.send_magic_link.call_count == 0

    def test_oauth_only_user_receives_magic_link(self, api_client, make_user, _stub_email_service):
        user = make_user(has_password=False)
        resp = api_client.post("/api/auth/magic-link/request", json={"email": user.email})
        assert resp.status_code == 200
        assert _stub_email_service.send_magic_link.call_count == 1

    def test_rate_limit_blocks_silently(self, api_client, make_user, _stub_email_service):
        settings = get_settings()
        user = make_user()
        limit = settings.magic_link_rate_limit_max_requests

        for _ in range(limit):
            resp = api_client.post("/api/auth/magic-link/request", json={"email": user.email})
            assert resp.status_code == 200

        assert _stub_email_service.send_magic_link.call_count == limit

        resp = api_client.post("/api/auth/magic-link/request", json={"email": user.email})
        assert resp.status_code == 200
        assert _stub_email_service.send_magic_link.call_count == limit

    def test_request_invalidates_prior_unused_code(
        self, api_client, make_user, _stub_email_service
    ):
        user = make_user()
        api_client.post("/api/auth/magic-link/request", json={"email": user.email})
        api_client.post("/api/auth/magic-link/request", json={"email": user.email})

        assert _count_unused_rows(user.id) == 1


# ===========================================================================
# Feature flag gating
# ===========================================================================


class TestFeatureFlagDisabled:
    def test_request_404_when_flag_disabled(self, api_client, make_user):
        user = make_user()
        real_ff = get_feature_flags()
        flags = dict(real_ff.flags)
        flags["magic_link_login"] = False
        disabled = FeatureFlags(flags, list(flags.keys()), real_ff.env)
        with patch("app.routers.magic_link.get_feature_flags", return_value=disabled):
            resp = api_client.post("/api/auth/magic-link/request", json={"email": user.email})
        assert resp.status_code == 404

    def test_consume_404_when_flag_disabled(self, api_client):
        real_ff = get_feature_flags()
        flags = dict(real_ff.flags)
        flags["magic_link_login"] = False
        disabled = FeatureFlags(flags, list(flags.keys()), real_ff.env)
        with patch("app.routers.magic_link.get_feature_flags", return_value=disabled):
            resp = api_client.post("/api/auth/magic-link/consume", json={"token": "irrelevant"})
        assert resp.status_code == 404

    def test_verify_404_when_flag_disabled(self, api_client):
        real_ff = get_feature_flags()
        flags = dict(real_ff.flags)
        flags["magic_link_login"] = False
        disabled = FeatureFlags(flags, list(flags.keys()), real_ff.env)
        with patch("app.routers.magic_link.get_feature_flags", return_value=disabled):
            resp = api_client.post(
                "/api/auth/magic-link/verify",
                json={"email": "x@example.com", "code": "123456"},
            )
        assert resp.status_code == 404


# ===========================================================================
# /consume (link click)
# ===========================================================================


class TestConsume:
    def test_consume_success_returns_token_and_sets_cookie(self, api_client, make_user):
        user = make_user()
        _code, token = _create_magic_link(user.id)

        resp = api_client.post("/api/auth/magic-link/consume", json={"token": token})
        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"]
        assert data["token_type"] == "bearer"
        assert _set_cookie_has(resp, "tesslate_refresh")

    def test_consume_fails_on_bad_signature(self, api_client):
        resp = api_client.post(
            "/api/auth/magic-link/consume",
            json={"token": "gibberish.fake.token"},
        )
        assert resp.status_code == 401

    def test_consume_fails_after_code_verified(self, api_client, make_user):
        user = make_user()
        code, token = _create_magic_link(user.id)

        vresp = api_client.post(
            "/api/auth/magic-link/verify",
            json={"email": user.email, "code": code},
        )
        assert vresp.status_code == 200

        cresp = api_client.post("/api/auth/magic-link/consume", json={"token": token})
        assert cresp.status_code == 401

    def test_consume_rejects_expired_row(self, api_client, make_user):
        user = make_user()
        _code, token = _create_magic_link(user.id)
        _expire_rows_for(user.id)

        resp = api_client.post("/api/auth/magic-link/consume", json={"token": token})
        assert resp.status_code == 401

    def test_consume_replay_fails(self, api_client, make_user):
        user = make_user()
        _code, token = _create_magic_link(user.id)

        r1 = api_client.post("/api/auth/magic-link/consume", json={"token": token})
        assert r1.status_code == 200

        r2 = api_client.post("/api/auth/magic-link/consume", json={"token": token})
        assert r2.status_code == 401

    def test_consume_rejects_inactive_user(self, api_client, make_user):
        user = make_user()
        _code, token = _create_magic_link(user.id)
        _deactivate_user(user.id)

        resp = api_client.post("/api/auth/magic-link/consume", json={"token": token})
        assert resp.status_code == 401


# ===========================================================================
# /verify (code path)
# ===========================================================================


class TestVerify:
    def test_verify_success_issues_token(self, api_client, make_user):
        user = make_user()
        code, _ = _create_magic_link(user.id)

        resp = api_client.post(
            "/api/auth/magic-link/verify",
            json={"email": user.email, "code": code},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"]
        assert _set_cookie_has(resp, "tesslate_refresh")

    def test_verify_wrong_code_returns_401_generic(self, api_client, make_user):
        user = make_user()
        _create_magic_link(user.id)

        resp = api_client.post(
            "/api/auth/magic-link/verify",
            json={"email": user.email, "code": "000000"},
        )
        assert resp.status_code == 401
        assert "invalid" in resp.json()["detail"].lower()

    def test_verify_unknown_email_returns_401_generic(self, api_client):
        resp = api_client.post(
            "/api/auth/magic-link/verify",
            json={"email": f"ghost-{uuid4().hex}@example.com", "code": "123456"},
        )
        assert resp.status_code == 401
        assert "invalid" in resp.json()["detail"].lower()

    def test_verify_inactive_user_fails_generic(self, api_client, make_user):
        user = make_user(active=False)
        resp = api_client.post(
            "/api/auth/magic-link/verify",
            json={"email": user.email, "code": "123456"},
        )
        assert resp.status_code == 401

    def test_verify_attempt_exhaustion_invalidates_row(self, api_client, make_user):
        settings = get_settings()
        user = make_user()
        real_code, _ = _create_magic_link(user.id)

        for _ in range(settings.magic_link_max_attempts):
            resp = api_client.post(
                "/api/auth/magic-link/verify",
                json={"email": user.email, "code": "000000"},
            )
            assert resp.status_code == 401

        resp = api_client.post(
            "/api/auth/magic-link/verify",
            json={"email": user.email, "code": real_code},
        )
        assert resp.status_code == 401

    def test_verify_then_link_is_invalidated(self, api_client, make_user):
        user = make_user()
        code, token = _create_magic_link(user.id)

        vresp = api_client.post(
            "/api/auth/magic-link/verify",
            json={"email": user.email, "code": code},
        )
        assert vresp.status_code == 200

        cresp = api_client.post("/api/auth/magic-link/consume", json={"token": token})
        assert cresp.status_code == 401

    def test_verify_rejects_shorter_code_with_422(self, api_client, make_user):
        user = make_user()
        resp = api_client.post(
            "/api/auth/magic-link/verify",
            json={"email": user.email, "code": "12345"},
        )
        assert resp.status_code == 422


# ===========================================================================
# CSRF middleware exemption (regression 2026-04-17)
# ===========================================================================


class TestCsrfExemption:
    """The CSRF middleware must exempt magic-link endpoints — the requester
    hasn't acquired a CSRF cookie yet (they're logging in). Without this
    exemption every anonymous POST is 403."""

    def test_request_without_csrf_token_is_not_403(self, api_client):
        api_client.cookies.clear()
        api_client.headers.pop("X-CSRF-Token", None)
        resp = api_client.post(
            "/api/auth/magic-link/request",
            json={"email": f"nobody-{uuid4().hex}@example.com"},
        )
        assert resp.status_code == 200, (
            f"CSRF middleware blocked magic-link request: {resp.status_code} {resp.text}"
        )

    def test_verify_without_csrf_token_is_not_403(self, api_client, make_user):
        user = make_user()
        api_client.cookies.clear()
        api_client.headers.pop("X-CSRF-Token", None)
        resp = api_client.post(
            "/api/auth/magic-link/verify",
            json={"email": user.email, "code": "000000"},
        )
        assert resp.status_code == 401, (
            f"CSRF middleware blocked magic-link verify: {resp.status_code} {resp.text}"
        )

    def test_consume_without_csrf_token_is_not_403(self, api_client):
        api_client.cookies.clear()
        api_client.headers.pop("X-CSRF-Token", None)
        resp = api_client.post("/api/auth/magic-link/consume", json={"token": "garbage"})
        assert resp.status_code == 401, (
            f"Unexpected status on /consume without CSRF: {resp.status_code} {resp.text}"
        )
