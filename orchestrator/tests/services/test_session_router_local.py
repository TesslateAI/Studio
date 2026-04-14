"""Desktop-mode SessionRouter — in-process backend round-trip."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.session_router import SessionRouter, _reset_session_router_for_tests


@pytest.fixture(autouse=True)
def _reset():
    _reset_session_router_for_tests()
    yield
    _reset_session_router_for_tests()


@pytest.mark.asyncio
async def test_register_lookup_unregister_in_process():
    with patch("app.config.get_settings") as gs:
        gs.return_value.redis_url = ""
        router = SessionRouter()

        await router.register_session("sess-1")
        assert await router.get_session_owner("sess-1") == router.pod_id
        assert await router.is_local("sess-1") is True

        await router.unregister_session("sess-1")
        # After unregister, lookup falls through to pod_id (single-pod mode).
        assert await router.is_local("sess-1") is True


@pytest.mark.asyncio
async def test_renew_refreshes_entry_when_owned():
    with patch("app.config.get_settings") as gs:
        gs.return_value.redis_url = ""
        router = SessionRouter()
        await router.register_session("sess-2")
        # Renew does not raise and keeps ownership intact.
        await router.renew_session("sess-2")
        assert await router.is_local("sess-2") is True


@pytest.mark.asyncio
async def test_eviction_of_unknown_session_is_noop():
    with patch("app.config.get_settings") as gs:
        gs.return_value.redis_url = ""
        router = SessionRouter()
        # Unregistering something we never registered is a no-op.
        await router.unregister_session("never-registered")
        # get_session_owner for unknown returns pod_id in single-pod mode.
        owner = await router.get_session_owner("never-registered")
        assert owner == router.pod_id
