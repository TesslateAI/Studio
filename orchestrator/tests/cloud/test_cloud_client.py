"""CloudClient: bearer injection, retry, no-retry on 4xx, circuit breaker."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
import respx


@pytest.fixture
def studio_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("TESSLATE_STUDIO_HOME", str(tmp_path))
    monkeypatch.delenv("TESSLATE_CLOUD_TOKEN", raising=False)
    (tmp_path / "cache").mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture
def fast_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip retry backoff in tests."""

    async def _no_sleep(_seconds: float) -> None:
        return None

    from app.services import cloud_client

    monkeypatch.setattr(cloud_client.CloudClient, "_sleep", staticmethod(_no_sleep))


@pytest.fixture
def paired(studio_home: Path):
    from app.services import token_store

    token_store.set_cloud_token("tsk_test")
    yield
    token_store.clear_cloud_token()


def _make_client(base_url: str = "https://cloud.test"):
    from app.services.cloud_client import CloudClient

    return CloudClient(base_url=base_url)


@pytest.mark.asyncio
async def test_not_paired_raises(studio_home: Path) -> None:
    from app.services.cloud_client import NotPairedError

    client = _make_client()
    try:
        with pytest.raises(NotPairedError):
            await client.get("/api/ping")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_bearer_injected(paired) -> None:
    client = _make_client()
    try:
        with respx.mock(base_url="https://cloud.test") as router:
            route = router.get("/api/ping").mock(
                return_value=httpx.Response(200, json={"ok": True})
            )
            resp = await client.get("/api/ping")
            assert resp.status_code == 200
            assert route.called
            assert route.calls.last.request.headers["authorization"] == "Bearer tsk_test"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_retry_on_5xx_then_succeeds(paired, fast_sleep) -> None:
    client = _make_client()
    try:
        with respx.mock(base_url="https://cloud.test") as router:
            route = router.get("/api/flaky").mock(
                side_effect=[
                    httpx.Response(503),
                    httpx.Response(503),
                    httpx.Response(200, json={"ok": True}),
                ]
            )
            resp = await client.get("/api/flaky")
            assert resp.status_code == 200
            assert route.call_count == 3
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_no_retry_on_4xx(paired, fast_sleep) -> None:
    client = _make_client()
    try:
        with respx.mock(base_url="https://cloud.test") as router:
            route = router.get("/api/forbidden").mock(
                return_value=httpx.Response(403, json={"detail": "nope"})
            )
            resp = await client.get("/api/forbidden")
            assert resp.status_code == 403
            assert route.call_count == 1
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_5xx_exhausts_retries_returns_response(paired, fast_sleep) -> None:
    client = _make_client()
    try:
        with respx.mock(base_url="https://cloud.test") as router:
            router.get("/api/down").mock(return_value=httpx.Response(500))
            resp = await client.get("/api/down")
            assert resp.status_code == 500
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_circuit_breaker_opens_then_half_open(paired, fast_sleep, monkeypatch) -> None:
    from app.services import cloud_client

    # Compress the open duration so we can exercise half-open quickly.
    monkeypatch.setattr(cloud_client, "_CB_OPEN_DURATION_S", 0.05)

    client = _make_client()
    try:
        with respx.mock(base_url="https://cloud.test") as router:
            router.get("/api/down").mock(return_value=httpx.Response(500))
            # Each .get() => 4 attempts (1 + 3 retries) => 4 failures.
            # Two such calls => 8 failures, well past threshold of 5.
            for _ in range(2):
                await client.get("/api/down")

            with pytest.raises(cloud_client.CircuitOpenError):
                await client.get("/api/down")

            # Wait past open duration → half-open allows the next call.
            await asyncio.sleep(0.06)

            router.get("/api/up").mock(return_value=httpx.Response(200))
            resp = await client.get("/api/up")
            assert resp.status_code == 200
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_success_resets_failure_counter(paired, fast_sleep) -> None:
    client = _make_client()
    try:
        with respx.mock(base_url="https://cloud.test") as router:
            # 4 failed attempts (1 call w/ retries), then a success → counter reset.
            router.get("/api/flap").mock(
                side_effect=[
                    httpx.Response(500),
                    httpx.Response(500),
                    httpx.Response(500),
                    httpx.Response(500),
                    httpx.Response(200),
                ]
            )
            await client.get("/api/flap")  # exhausts retries, returns 500
            router.get("/api/ok").mock(return_value=httpx.Response(200))
            resp = await client.get("/api/ok")
            assert resp.status_code == 200
            # Breaker should NOT be open now.
            from app.services.cloud_client import CircuitOpenError

            try:
                await client.get("/api/ok")
            except CircuitOpenError:
                pytest.fail("circuit should have been reset by success")
    finally:
        await client.aclose()
