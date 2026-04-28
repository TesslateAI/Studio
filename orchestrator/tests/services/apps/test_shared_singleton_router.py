"""Unit tests for the shared-singleton ``X-OpenSail-User`` header signer.

Targets ``services.apps.shared_singleton_router``:

* Sign + verify roundtrip with the same secret material.
* Expired token (``exp`` in the past) → InvalidSignature.
* Mismatched ``app_instance_id`` between signer and verifier → InvalidSignature
  (cross-app replay defense).

The signer normally pulls ``settings.secret_key`` for its derivation;
tests pass an explicit ``secret_override`` so we don't depend on the
process-wide settings cache being primed.
"""

from __future__ import annotations

import time
import uuid

import pytest

from app.services.apps.shared_singleton_router import (
    CLOCK_SKEW_TOLERANCE_SECONDS,
    InvalidSignature,
    sign_user_header,
    verify_user_header,
)


_TEST_SECRET = "test-shared-singleton-router-secret"


@pytest.mark.asyncio
async def test_sign_and_verify_user_header_roundtrip() -> None:
    """A header signed for (user, instance) verifies back to the same user."""
    user_id = uuid.uuid4()
    instance_id = uuid.uuid4()

    header = await sign_user_header(
        user_id,
        instance_id,
        ttl_seconds=60,
        secret_override=_TEST_SECRET,
    )
    resolved = await verify_user_header(
        header,
        instance_id,
        secret_override=_TEST_SECRET,
    )
    assert resolved == user_id


@pytest.mark.asyncio
async def test_verify_expired_signature_raises() -> None:
    """A header whose ``exp`` is well past the clock-skew window must fail."""
    user_id = uuid.uuid4()
    instance_id = uuid.uuid4()

    # Sign with a 1-second TTL, then verify with ``now`` advanced past the
    # clock-skew tolerance — the assertion is independent of wall time.
    header = await sign_user_header(
        user_id,
        instance_id,
        ttl_seconds=1,
        secret_override=_TEST_SECRET,
    )
    far_future = int(time.time()) + CLOCK_SKEW_TOLERANCE_SECONDS + 120

    with pytest.raises(InvalidSignature):
        await verify_user_header(
            header,
            instance_id,
            secret_override=_TEST_SECRET,
            now_seconds=far_future,
        )


@pytest.mark.asyncio
async def test_verify_wrong_instance_id_raises() -> None:
    """A header signed for instance A must NOT verify against instance B."""
    user_id = uuid.uuid4()
    id_a = uuid.uuid4()
    id_b = uuid.uuid4()

    header = await sign_user_header(
        user_id,
        id_a,
        ttl_seconds=60,
        secret_override=_TEST_SECRET,
    )
    with pytest.raises(InvalidSignature):
        await verify_user_header(
            header,
            id_b,
            secret_override=_TEST_SECRET,
        )
