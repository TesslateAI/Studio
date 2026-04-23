"""Tests for /api/internal/* endpoints and the verify_internal_secret dependency.

Coverage:
  - Unit: verify_internal_secret — correct secret passes, wrong secret fails,
    missing secret fails, grace period allows, grace period expires, desktop bypass.
  - Integration: GET /known-volume-ids and POST /volume-events via FastAPI TestClient
    with mocked DB and settings, exercising all auth code paths.
"""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GOOD_SECRET = "test-secret-abc123"
_BAD_SECRET = "wrong-secret"

# Patch target for get_pubsub — imported locally inside the endpoint function,
# so we must patch at the source module, not at app.routers.internal.
_PUBSUB_PATCH = "app.services.pubsub.get_pubsub"


def _make_settings(
    *,
    secret: str = _GOOD_SECRET,
    grace: int = 60,
    desktop: bool = False,
) -> MagicMock:
    s = MagicMock()
    s.internal_api_secret = secret
    s.internal_secret_grace_seconds = grace
    s.is_desktop_mode = desktop
    return s


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reload_internal_module():
    """Re-import the internal router module before each test.

    This resets _startup_time (module-level monotonic timestamp) so tests
    start from a known state.  We then patch time.monotonic to control
    elapsed time precisely.
    """
    import app.routers.internal as mod

    importlib.reload(mod)
    yield mod


@pytest.fixture
def _app(_reload_internal_module):
    """Minimal FastAPI app wired with just the internal router."""
    from app.routers import internal as mod

    app = FastAPI()
    app.include_router(mod.router, prefix="/api")
    return app


@pytest.fixture
def _mock_db():
    """Async generator that yields a mock AsyncSession."""

    async def _db_gen():
        yield AsyncMock()

    return _db_gen


@pytest.fixture
def client(_app, _mock_db, _reload_internal_module):
    """TestClient with the DB dependency overridden."""
    from app.database import get_db

    _app.dependency_overrides[get_db] = _mock_db
    with TestClient(_app, raise_server_exceptions=True) as c:
        yield c
    _app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Unit: verify_internal_secret
# ---------------------------------------------------------------------------


class TestVerifyInternalSecret:
    """Direct unit tests for the verify_internal_secret coroutine."""

    @pytest.mark.asyncio
    async def test_correct_secret_passes(self, _reload_internal_module):
        mod = _reload_internal_module
        settings = _make_settings(secret=_GOOD_SECRET, grace=0)
        mod._startup_time = 0.0
        with patch.object(mod, "get_settings", return_value=settings):
            with patch(f"{mod.__name__}.time") as mock_time:
                mock_time.monotonic.return_value = 999.0
                request = MagicMock()
                request.headers.get.return_value = _GOOD_SECRET
                await mod.verify_internal_secret(request)

    @pytest.mark.asyncio
    async def test_wrong_secret_after_grace_raises_403(self, _reload_internal_module):
        from fastapi import HTTPException

        mod = _reload_internal_module
        mod._startup_time = 0.0  # reset so elapsed = now - 0 = now > grace(0)
        settings = _make_settings(secret=_GOOD_SECRET, grace=0)
        with patch.object(mod, "get_settings", return_value=settings):
            with patch(f"{mod.__name__}.time") as mock_time:
                mock_time.monotonic.return_value = 999.0
                request = MagicMock()
                request.headers.get.return_value = _BAD_SECRET
                with pytest.raises(HTTPException) as exc_info:
                    await mod.verify_internal_secret(request)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_missing_secret_after_grace_raises_403(self, _reload_internal_module):
        from fastapi import HTTPException

        mod = _reload_internal_module
        mod._startup_time = 0.0
        settings = _make_settings(secret=_GOOD_SECRET, grace=0)
        with patch.object(mod, "get_settings", return_value=settings):
            with patch(f"{mod.__name__}.time") as mock_time:
                mock_time.monotonic.return_value = 999.0
                request = MagicMock()
                request.headers.get.return_value = ""  # no header
                with pytest.raises(HTTPException) as exc_info:
                    await mod.verify_internal_secret(request)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_wrong_secret_within_grace_is_allowed(self, _reload_internal_module):
        mod = _reload_internal_module
        mod._startup_time = 0.0
        settings = _make_settings(secret=_GOOD_SECRET, grace=120)
        with patch.object(mod, "get_settings", return_value=settings):
            with patch(f"{mod.__name__}.time") as mock_time:
                # elapsed = 5.0 - 0.0 = 5.0 < grace(120) → allowed
                mock_time.monotonic.return_value = 5.0
                request = MagicMock()
                request.headers.get.return_value = _BAD_SECRET
                # Should NOT raise
                await mod.verify_internal_secret(request)

    @pytest.mark.asyncio
    async def test_desktop_mode_bypasses_enforcement(self, _reload_internal_module):
        mod = _reload_internal_module
        settings = _make_settings(secret=_GOOD_SECRET, grace=0, desktop=True)
        with patch.object(mod, "get_settings", return_value=settings):
            request = MagicMock()
            request.headers.get.return_value = ""
            # No exception even with empty secret and grace=0
            await mod.verify_internal_secret(request)

    @pytest.mark.asyncio
    async def test_empty_server_secret_after_grace_raises_403(self, _reload_internal_module):
        """When INTERNAL_API_SECRET is unset (empty) and grace has expired,
        requests without a correct header are rejected.

        Note: hmac.compare_digest("", "") would return True, but the `if expected`
        guard skips that branch when expected is falsy, so we fall through to the
        grace-period check.
        """
        from fastapi import HTTPException

        mod = _reload_internal_module
        mod._startup_time = 0.0
        settings = _make_settings(secret="", grace=0)
        with patch.object(mod, "get_settings", return_value=settings):
            with patch(f"{mod.__name__}.time") as mock_time:
                mock_time.monotonic.return_value = 999.0
                request = MagicMock()
                request.headers.get.return_value = ""
                with pytest.raises(HTTPException) as exc_info:
                    await mod.verify_internal_secret(request)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Integration: GET /api/internal/known-volume-ids
# ---------------------------------------------------------------------------


class TestKnownVolumeIds:
    def test_correct_secret_returns_volume_list(self, client, _reload_internal_module):
        mod = _reload_internal_module
        mod._startup_time = 0.0
        settings = _make_settings(secret=_GOOD_SECRET, grace=0)

        vol_ids = ["vol-abc", "vol-def"]
        mock_result = MagicMock()
        mock_result.all.return_value = [(v,) for v in vol_ids]

        async def _fake_db():
            db = AsyncMock()
            db.execute = AsyncMock(return_value=mock_result)
            yield db

        from app.database import get_db

        client.app.dependency_overrides[get_db] = _fake_db

        with (
            patch.object(mod, "get_settings", return_value=settings),
            patch(f"{mod.__name__}.time") as mock_time,
        ):
            mock_time.monotonic.return_value = 999.0
            resp = client.get(
                "/api/internal/known-volume-ids",
                headers={"X-Internal-Secret": _GOOD_SECRET},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert set(data["volume_ids"]) == set(vol_ids)

    def test_wrong_secret_after_grace_returns_403(self, client, _reload_internal_module):
        mod = _reload_internal_module
        mod._startup_time = 0.0
        settings = _make_settings(secret=_GOOD_SECRET, grace=0)

        with (
            patch.object(mod, "get_settings", return_value=settings),
            patch(f"{mod.__name__}.time") as mock_time,
        ):
            mock_time.monotonic.return_value = 999.0
            resp = client.get(
                "/api/internal/known-volume-ids",
                headers={"X-Internal-Secret": _BAD_SECRET},
            )

        assert resp.status_code == 403

    def test_no_secret_within_grace_returns_200(self, client, _reload_internal_module):
        mod = _reload_internal_module
        mod._startup_time = 0.0
        settings = _make_settings(secret=_GOOD_SECRET, grace=120)

        mock_result = MagicMock()
        mock_result.all.return_value = []

        async def _fake_db():
            db = AsyncMock()
            db.execute = AsyncMock(return_value=mock_result)
            yield db

        from app.database import get_db

        client.app.dependency_overrides[get_db] = _fake_db

        with (
            patch.object(mod, "get_settings", return_value=settings),
            patch(f"{mod.__name__}.time") as mock_time,
        ):
            # elapsed = 5.0 < grace(120) → allowed even with wrong secret
            mock_time.monotonic.return_value = 5.0
            resp = client.get(
                "/api/internal/known-volume-ids",
                headers={"X-Internal-Secret": _BAD_SECRET},
            )

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Integration: POST /api/internal/volume-events
# ---------------------------------------------------------------------------


class TestVolumeEvents:
    @staticmethod
    def _fake_db_with_project(project_id, owner_id):
        """Return a get_db override that returns a known project row."""

        async def _db():
            db = AsyncMock()
            result = MagicMock()
            result.first.return_value = (project_id, owner_id)
            db.execute = AsyncMock(return_value=result)
            yield db

        return _db

    @staticmethod
    def _fake_db_no_project():
        """Return a get_db override where no project owns the volume."""

        async def _db():
            db = AsyncMock()
            result = MagicMock()
            result.first.return_value = None
            db.execute = AsyncMock(return_value=result)
            yield db

        return _db

    def test_volume_ready_event_known_project(self, client, _reload_internal_module):
        mod = _reload_internal_module
        mod._startup_time = 0.0
        settings = _make_settings(secret=_GOOD_SECRET, grace=0)

        import uuid

        project_id = uuid.uuid4()
        owner_id = uuid.uuid4()

        from app.database import get_db

        client.app.dependency_overrides[get_db] = self._fake_db_with_project(project_id, owner_id)

        with (
            patch.object(mod, "get_settings", return_value=settings),
            patch(f"{mod.__name__}.time") as mock_time,
            patch(_PUBSUB_PATCH, return_value=None),
        ):
            mock_time.monotonic.return_value = 999.0
            resp = client.post(
                "/api/internal/volume-events",
                json={"volume_id": "vol-abc", "event": "ready"},
                headers={"X-Internal-Secret": _GOOD_SECRET},
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_volume_deleted_event_known_project(self, client, _reload_internal_module):
        mod = _reload_internal_module
        mod._startup_time = 0.0
        settings = _make_settings(secret=_GOOD_SECRET, grace=0)

        import uuid

        project_id = uuid.uuid4()
        owner_id = uuid.uuid4()

        from app.database import get_db

        client.app.dependency_overrides[get_db] = self._fake_db_with_project(project_id, owner_id)

        with (
            patch.object(mod, "get_settings", return_value=settings),
            patch(f"{mod.__name__}.time") as mock_time,
            patch(_PUBSUB_PATCH, return_value=None),
        ):
            mock_time.monotonic.return_value = 999.0
            resp = client.post(
                "/api/internal/volume-events",
                json={"volume_id": "vol-xyz", "event": "deleted"},
                headers={"X-Internal-Secret": _GOOD_SECRET},
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_volume_event_unknown_volume_returns_no_project(self, client, _reload_internal_module):
        mod = _reload_internal_module
        mod._startup_time = 0.0
        settings = _make_settings(secret=_GOOD_SECRET, grace=0)

        from app.database import get_db

        client.app.dependency_overrides[get_db] = self._fake_db_no_project()

        with (
            patch.object(mod, "get_settings", return_value=settings),
            patch(f"{mod.__name__}.time") as mock_time,
        ):
            mock_time.monotonic.return_value = 999.0
            resp = client.post(
                "/api/internal/volume-events",
                json={"volume_id": "vol-unknown", "event": "ready"},
                headers={"X-Internal-Secret": _GOOD_SECRET},
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "no_project"

    def test_invalid_event_type_returns_422(self, client, _reload_internal_module):
        mod = _reload_internal_module
        mod._startup_time = 0.0
        settings = _make_settings(secret=_GOOD_SECRET, grace=0)

        with (
            patch.object(mod, "get_settings", return_value=settings),
            patch(f"{mod.__name__}.time") as mock_time,
        ):
            mock_time.monotonic.return_value = 999.0
            resp = client.post(
                "/api/internal/volume-events",
                json={"volume_id": "vol-abc", "event": "invalid_event_type"},
                headers={"X-Internal-Secret": _GOOD_SECRET},
            )

        assert resp.status_code == 422

    def test_volume_event_missing_fields_returns_422(self, client, _reload_internal_module):
        mod = _reload_internal_module
        mod._startup_time = 0.0
        settings = _make_settings(secret=_GOOD_SECRET, grace=0)

        with (
            patch.object(mod, "get_settings", return_value=settings),
            patch(f"{mod.__name__}.time") as mock_time,
        ):
            mock_time.monotonic.return_value = 999.0
            resp = client.post(
                "/api/internal/volume-events",
                json={"event": "ready"},  # missing volume_id
                headers={"X-Internal-Secret": _GOOD_SECRET},
            )

        assert resp.status_code == 422

    def test_volume_event_wrong_secret_returns_403(self, client, _reload_internal_module):
        mod = _reload_internal_module
        mod._startup_time = 0.0
        settings = _make_settings(secret=_GOOD_SECRET, grace=0)

        with (
            patch.object(mod, "get_settings", return_value=settings),
            patch(f"{mod.__name__}.time") as mock_time,
        ):
            mock_time.monotonic.return_value = 999.0
            resp = client.post(
                "/api/internal/volume-events",
                json={"volume_id": "vol-abc", "event": "ready"},
                headers={"X-Internal-Secret": _BAD_SECRET},
            )

        assert resp.status_code == 403

    def test_pubsub_failure_does_not_crash_endpoint(self, client, _reload_internal_module):
        """Pubsub publish errors are caught and the endpoint still returns 200."""
        mod = _reload_internal_module
        mod._startup_time = 0.0
        settings = _make_settings(secret=_GOOD_SECRET, grace=0)

        import uuid

        project_id = uuid.uuid4()
        owner_id = uuid.uuid4()

        from app.database import get_db

        client.app.dependency_overrides[get_db] = self._fake_db_with_project(project_id, owner_id)

        # pubsub raises on publish
        mock_pubsub = AsyncMock()
        mock_pubsub.publish_status_update = AsyncMock(side_effect=RuntimeError("pubsub down"))

        with (
            patch.object(mod, "get_settings", return_value=settings),
            patch(f"{mod.__name__}.time") as mock_time,
            patch(_PUBSUB_PATCH, return_value=mock_pubsub),
        ):
            mock_time.monotonic.return_value = 999.0
            resp = client.post(
                "/api/internal/volume-events",
                json={"volume_id": "vol-abc", "event": "ready"},
                headers={"X-Internal-Secret": _GOOD_SECRET},
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
