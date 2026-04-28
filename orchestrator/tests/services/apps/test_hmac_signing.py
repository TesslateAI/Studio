"""Unit tests for the Connector Proxy HMAC token sign/verify pair.

Targets ``services.apps.connector_proxy.auth``:

* ``generate_pod_token`` + ``parse_app_instance_token`` round-trip.
* ``verify_app_instance`` raises 401 on a tampered signature.
* Verification rejects a token claiming a different instance id than
  the one its signing key backs.
* ``hmac.compare_digest`` is the comparator (constant-time).

Sign + verify both go through the deterministic-derivation fallback
(K8s Secret unavailable), which is what desktop / dev / tests all use.
The same derivation is used in production K8s mode when the Secret
hasn't propagated yet, so this is the canonical happy path.
"""

from __future__ import annotations

import hmac
import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Importing models registers all tables on Base.metadata.
from app import models, models_automations  # noqa: F401
from app.database import Base
from app.models_automations import AppInstance
from app.services.apps.connector_proxy import auth as proxy_auth


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    """Per-test SQLite engine + session."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


@pytest.fixture(autouse=True)
def _flush_signing_key_cache() -> None:
    """The proxy memoizes signing keys for 60s by default — clear between tests."""
    proxy_auth.invalidate_signing_key_cache(None)
    yield
    proxy_auth.invalidate_signing_key_cache(None)


def _fake_request(headers: dict[str, str]) -> Any:
    """Build a minimal object exposing ``.headers.get(name)``.

    ``verify_app_instance`` reads exactly one attribute (``request.headers``)
    so a SimpleNamespace-shaped stub with a dict-backed ``.headers`` is
    sufficient — no FastAPI Request import needed.
    """
    req = MagicMock()
    req.headers = headers
    return req


async def _seed_install(db: AsyncSession, instance_id: uuid.UUID) -> AppInstance:
    """Insert a live AppInstance the verifier can resolve."""
    inst = AppInstance(
        id=instance_id,
        app_id=uuid.uuid4(),
        app_version_id=uuid.uuid4(),
        installer_user_id=uuid.uuid4(),
        state="installed",
    )
    db.add(inst)
    await db.flush()
    return inst


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_valid_token_returns_instance_id(db: AsyncSession) -> None:
    """Sign + verify roundtrip with the same deterministic derivation."""
    instance_id = uuid.uuid4()
    await _seed_install(db, instance_id)

    signing_key = proxy_auth.derive_signing_key(instance_id)
    token = proxy_auth.generate_pod_token(
        app_instance_id=instance_id, signing_key=signing_key
    )
    # Sanity: parse_app_instance_token unwraps cleanly.
    parsed_id, nonce, sig = proxy_auth.parse_app_instance_token(token)
    assert parsed_id == instance_id
    assert nonce
    assert sig

    request = _fake_request({proxy_auth.APP_INSTANCE_HEADER: token})
    instance = await proxy_auth.verify_app_instance(request, db)
    assert instance.id == instance_id


@pytest.mark.asyncio
async def test_verify_tampered_signature_raises_401(db: AsyncSession) -> None:
    """Flipping a single byte of the sig MUST raise AppInstanceAuthError(401)."""
    instance_id = uuid.uuid4()
    await _seed_install(db, instance_id)

    signing_key = proxy_auth.derive_signing_key(instance_id)
    token = proxy_auth.generate_pod_token(
        app_instance_id=instance_id, signing_key=signing_key
    )
    # Tamper: flip the last char of the signature segment.
    parsed_id, nonce, sig = proxy_auth.parse_app_instance_token(token)
    new_last = "0" if sig[-1] != "0" else "1"
    tampered_sig = sig[:-1] + new_last
    tampered = f"{parsed_id}.{nonce}.{tampered_sig}"

    request = _fake_request({proxy_auth.APP_INSTANCE_HEADER: tampered})
    with pytest.raises(proxy_auth.AppInstanceAuthError) as excinfo:
        await proxy_auth.verify_app_instance(request, db)
    assert excinfo.value.status_code == 401


@pytest.mark.asyncio
async def test_verify_wrong_instance_id_in_secret_raises(db: AsyncSession) -> None:
    """A token signed with key for B but presented under id A must fail.

    We mint a token using B's signing key, then rewrite the leading
    instance_id field to A. The verifier resolves A's signing key
    (different bytes) and the HMAC compare fails → 401.
    """
    id_a = uuid.uuid4()
    id_b = uuid.uuid4()
    await _seed_install(db, id_a)
    await _seed_install(db, id_b)

    # Build the token under B's key, then stamp A's id on the front.
    signing_key_b = proxy_auth.derive_signing_key(id_b)
    token_b = proxy_auth.generate_pod_token(
        app_instance_id=id_b, signing_key=signing_key_b
    )
    _, nonce, sig_b = proxy_auth.parse_app_instance_token(token_b)
    spoofed = f"{id_a}.{nonce}.{sig_b}"

    request = _fake_request({proxy_auth.APP_INSTANCE_HEADER: spoofed})
    with pytest.raises(proxy_auth.AppInstanceAuthError):
        await proxy_auth.verify_app_instance(request, db)


@pytest.mark.asyncio
async def test_constant_time_compare_used(db: AsyncSession) -> None:
    """Verify that hmac.compare_digest is the comparator on the verify path.

    Patches ``hmac.compare_digest`` to a sentinel-returning spy and asserts
    it was invoked. Belt-and-braces against an accidental ``==`` swap.
    """
    instance_id = uuid.uuid4()
    await _seed_install(db, instance_id)

    signing_key = proxy_auth.derive_signing_key(instance_id)
    token = proxy_auth.generate_pod_token(
        app_instance_id=instance_id, signing_key=signing_key
    )
    request = _fake_request({proxy_auth.APP_INSTANCE_HEADER: token})

    # Wrap (not replace) so the call still returns the right truth value.
    real_compare = hmac.compare_digest
    spy = MagicMock(side_effect=real_compare)
    with patch.object(proxy_auth.hmac, "compare_digest", spy):
        instance = await proxy_auth.verify_app_instance(request, db)
    assert instance.id == instance_id
    assert spy.call_count >= 1
