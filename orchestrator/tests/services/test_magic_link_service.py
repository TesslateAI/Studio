"""
Unit tests for app.services.magic_link_service.

Covers the security-critical paths:
  - Code generation length/numeric
  - Code is bcrypt-hashed at rest (plaintext never stored)
  - verify_code success marks row used (replay prevented)
  - verify_code wrong code increments attempts; invalidates at max_attempts
  - verify_code fails on expired, used, and missing rows
  - create_magic_link invalidates previous unused row for same user+purpose
  - consume_link_token success → user_id and marks row used
  - consume_link_token fails on: bad signature, expired, already used, wrong purpose
  - Rate limit: counts rows created within the window
  - Link token serializer uses a salt distinct from 2FA (no cross-purpose replay)
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth import get_password_hash
from app.config import get_settings
from app.models import EmailVerificationCode, User
from app.services import magic_link_service as mls

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Per-test isolated engine.
#
# pytest-asyncio (auto mode) creates a fresh event loop per test. The
# module-level engine in app.database has a connection pool whose asyncpg
# connections are bound to whichever loop made them first — reusing across
# loops raises "Future attached to a different loop". So each test gets a
# fresh NullPool engine; connections open on the test's loop and close at
# session end.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session():
    """Fresh AsyncSession on a NullPool engine bound to THIS test's loop."""
    settings = get_settings()
    test_engine = create_async_engine(settings.database_url, poolclass=NullPool)
    test_sessionmaker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with test_sessionmaker() as session:
        yield session
    await test_engine.dispose()


@pytest_asyncio.fixture
async def user(db_session):
    """Create a fresh user, committed so other sessions (in the service) see it."""
    u = User(
        id=uuid4(),
        email=f"magic-{uuid4().hex}@example.com",
        hashed_password=get_password_hash("irrelevant"),
        is_active=True,
        is_verified=True,
        name="Magic Test",
        username=f"magic-{uuid4().hex[:8]}",
        slug=f"magic-{uuid4().hex[:8]}",
    )
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    yield u


# ---------------------------------------------------------------------------
# Code generation
# ---------------------------------------------------------------------------


def test_generate_code_is_numeric_and_correct_length():
    settings = get_settings()
    for _ in range(50):
        code = mls.generate_code()
        assert code.isdigit()
        assert len(code) == settings.magic_link_code_length


def test_generate_code_distribution_not_constant():
    # Weak randomness smoke check — 50 codes should never all be identical.
    codes = {mls.generate_code() for _ in range(50)}
    assert len(codes) > 1


# ---------------------------------------------------------------------------
# create_magic_link
# ---------------------------------------------------------------------------


async def test_create_magic_link_stores_hashed_code(db_session, user):
    code, token = await mls.create_magic_link(db_session, user.id)
    await db_session.commit()

    # Plaintext code is never stored; the row holds a bcrypt hash
    from sqlalchemy import select

    result = await db_session.execute(
        select(EmailVerificationCode).where(
            EmailVerificationCode.user_id == user.id,
            EmailVerificationCode.purpose == mls.PURPOSE,
            EmailVerificationCode.used == False,  # noqa: E712
        )
    )
    rows = result.scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.code_hash != code  # not plaintext
    assert row.code_hash != ""
    assert row.max_attempts == get_settings().magic_link_max_attempts
    assert row.expires_at > datetime.now(UTC)
    # Token is non-empty and does NOT contain the raw code
    assert token and len(token) > 10
    assert code not in token


async def test_create_magic_link_invalidates_previous_unused(db_session, user):
    _code1, _token1 = await mls.create_magic_link(db_session, user.id)
    _code2, _token2 = await mls.create_magic_link(db_session, user.id)
    await db_session.commit()

    from sqlalchemy import select

    result = await db_session.execute(
        select(EmailVerificationCode).where(
            EmailVerificationCode.user_id == user.id,
            EmailVerificationCode.purpose == mls.PURPOSE,
            EmailVerificationCode.used == False,  # noqa: E712
        )
    )
    rows = result.scalars().all()
    assert len(rows) == 1, "only one unused row should exist after a second request"


# ---------------------------------------------------------------------------
# verify_code
# ---------------------------------------------------------------------------


async def test_verify_code_success_marks_used(db_session, user):
    code, _ = await mls.create_magic_link(db_session, user.id)
    await db_session.commit()

    ok = await mls.verify_code(db_session, user.id, code)
    await db_session.commit()
    assert ok is True

    # Replay must fail: row is used
    ok2 = await mls.verify_code(db_session, user.id, code)
    await db_session.commit()
    assert ok2 is False


async def test_verify_code_wrong_code_increments_attempts(db_session, user):
    code, _ = await mls.create_magic_link(db_session, user.id)
    await db_session.commit()
    # Compute a definitely-wrong code (flip every digit)
    wrong = "".join(str((int(c) + 1) % 10) for c in code)

    ok = await mls.verify_code(db_session, user.id, wrong)
    await db_session.commit()
    assert ok is False

    from sqlalchemy import select

    result = await db_session.execute(
        select(EmailVerificationCode).where(
            EmailVerificationCode.user_id == user.id,
            EmailVerificationCode.used == False,  # noqa: E712
        )
    )
    row = result.scalars().first()
    assert row is not None
    assert row.attempts == 1


async def test_verify_code_exhausts_and_invalidates(db_session, user):
    code, _ = await mls.create_magic_link(db_session, user.id)
    await db_session.commit()
    wrong = "".join(str((int(c) + 1) % 10) for c in code)
    max_attempts = get_settings().magic_link_max_attempts

    for _ in range(max_attempts):
        await mls.verify_code(db_session, user.id, wrong)
    await db_session.commit()

    # Even the correct code now fails because the row was invalidated
    ok = await mls.verify_code(db_session, user.id, code)
    await db_session.commit()
    assert ok is False


async def test_verify_code_no_active_row_returns_false(db_session, user):
    ok = await mls.verify_code(db_session, user.id, "000000")
    assert ok is False


async def test_verify_code_expired_row_returns_false(db_session, user):
    code, _ = await mls.create_magic_link(db_session, user.id)
    # Move expiry into the past
    from sqlalchemy import update

    await db_session.execute(
        update(EmailVerificationCode)
        .where(EmailVerificationCode.user_id == user.id)
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await db_session.commit()

    ok = await mls.verify_code(db_session, user.id, code)
    await db_session.commit()
    assert ok is False


async def test_verify_code_wrong_purpose_does_not_match(db_session, user):
    # Inject a row with the correct code but for a different purpose (e.g. 2fa_login)
    plain = "123456"
    row = EmailVerificationCode(
        id=uuid4(),
        user_id=user.id,
        code_hash=get_password_hash(plain),
        purpose="2fa_login",
        attempts=0,
        max_attempts=5,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        used=False,
    )
    db_session.add(row)
    await db_session.commit()

    # magic-link verification must not accept the 2FA row
    ok = await mls.verify_code(db_session, user.id, plain)
    await db_session.commit()
    assert ok is False


# ---------------------------------------------------------------------------
# consume_link_token
# ---------------------------------------------------------------------------


async def test_consume_link_token_success(db_session, user):
    _code, token = await mls.create_magic_link(db_session, user.id)
    await db_session.commit()

    uid = await mls.consume_link_token(db_session, token)
    await db_session.commit()
    assert uid == user.id

    # Replay is prevented
    uid2 = await mls.consume_link_token(db_session, token)
    await db_session.commit()
    assert uid2 is None


async def test_consume_link_token_bad_signature(db_session, user):
    uid = await mls.consume_link_token(db_session, "not-a-valid-token")
    assert uid is None


async def test_consume_link_token_tampered(db_session, user):
    _code, token = await mls.create_magic_link(db_session, user.id)
    await db_session.commit()
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    uid = await mls.consume_link_token(db_session, tampered)
    assert uid is None


async def test_consume_link_token_after_code_used(db_session, user):
    code, token = await mls.create_magic_link(db_session, user.id)
    await db_session.commit()

    # Consume via code first
    ok = await mls.verify_code(db_session, user.id, code)
    await db_session.commit()
    assert ok is True

    # The link must now be dead
    uid = await mls.consume_link_token(db_session, token)
    await db_session.commit()
    assert uid is None


async def test_consume_link_token_expired_row(db_session, user):
    _code, token = await mls.create_magic_link(db_session, user.id)
    from sqlalchemy import update

    await db_session.execute(
        update(EmailVerificationCode)
        .where(EmailVerificationCode.user_id == user.id)
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await db_session.commit()

    uid = await mls.consume_link_token(db_session, token)
    await db_session.commit()
    assert uid is None


async def test_consume_link_token_distinct_salt_from_2fa(db_session):
    """A token signed with the 2FA salt must NOT validate as a magic-link token."""
    from app.services import two_fa_service

    fake_user_id = uuid4()
    # Build a payload using the 2FA serializer — the magic-link serializer
    # must reject it because the salts differ.
    twofa_token = two_fa_service._temp_token_serializer.dumps(str(fake_user_id))
    uid = await mls.consume_link_token(db_session, twofa_token)
    assert uid is None


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


async def test_check_rate_limit_allows_under_threshold(db_session, user):
    # Create N-1 requests
    settings = get_settings()
    for _ in range(settings.magic_link_rate_limit_max_requests - 1):
        await mls.create_magic_link(db_session, user.id)
    await db_session.commit()

    assert await mls.check_rate_limit(db_session, user.id) is True


async def test_check_rate_limit_blocks_at_threshold(db_session, user):
    settings = get_settings()
    for _ in range(settings.magic_link_rate_limit_max_requests):
        await mls.create_magic_link(db_session, user.id)
    await db_session.commit()

    assert await mls.check_rate_limit(db_session, user.id) is False


async def test_check_rate_limit_ignores_rows_outside_window(db_session, user):
    settings = get_settings()

    # Create max rows, then backdate them outside the window
    for _ in range(settings.magic_link_rate_limit_max_requests):
        await mls.create_magic_link(db_session, user.id)
    await db_session.commit()

    from sqlalchemy import update

    old = datetime.now(UTC) - timedelta(seconds=settings.magic_link_rate_limit_window_seconds + 60)
    await db_session.execute(
        update(EmailVerificationCode)
        .where(EmailVerificationCode.user_id == user.id)
        .values(created_at=old)
    )
    await db_session.commit()

    assert await mls.check_rate_limit(db_session, user.id) is True


# ---------------------------------------------------------------------------
# URL builder
# ---------------------------------------------------------------------------


def test_build_magic_link_url_embeds_token():
    token = "abc.def.ghi"
    url = mls.build_magic_link_url(token)
    assert url.endswith(f"/auth/magic?token={token}")
    assert url.startswith("http")  # either http or https, depending on env


# ---------------------------------------------------------------------------
# Timing / replay sanity
# ---------------------------------------------------------------------------


async def test_verify_code_success_is_single_use_across_calls(db_session, user):
    """Defense-in-depth: two rapid successful verifications should not both succeed."""
    code, _ = await mls.create_magic_link(db_session, user.id)
    await db_session.commit()

    r1 = await mls.verify_code(db_session, user.id, code)
    await db_session.commit()
    r2 = await mls.verify_code(db_session, user.id, code)
    await db_session.commit()

    assert (r1, r2) == (True, False)


def test_two_consecutive_codes_differ():
    # The code space is 1e6 — consecutive draws should almost always differ.
    c1 = mls.generate_code()
    # small delay so we're not just seeing memoization
    time.sleep(0.001)
    c2 = mls.generate_code()
    # If equal, try once more; a single collision in 1M is statistically fine
    if c1 == c2:
        c2 = mls.generate_code()
    assert c1 != c2
