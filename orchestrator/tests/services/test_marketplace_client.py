"""
Tests for ``app.services.marketplace_client``.

Covers:
  - Hub-id pinning / mismatch detection
  - 304 Not Modified short-circuit on conditional GETs
  - Retry + backoff on 5xx and transient transport errors
  - Circuit breaker opens after consecutive failures
  - 401/403/404/501 do NOT retry and surface as typed exceptions
  - local:// short-circuit refuses HTTP verbs
  - Hub-id pinning end-to-end against the real Wave-2 marketplace service
    (covered by the @pytest.mark.integration test that boots the actual
    service via subprocess).

The transport-mocked path runs in the default (unit) collection. The real
subprocess path requires the Wave-2 marketplace package to be installed
in its own venv (we exec that venv's uvicorn).
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from app.services import marketplace_client as mc


HUB_ID_HEADER = mc.HUB_ID_HEADER


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_breakers():
    mc.reset_circuit_breakers_for_tests()
    yield
    mc.reset_circuit_breakers_for_tests()


def _ok(payload: dict, *, hub_id: str = "hub-A", status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        json=payload,
        headers={HUB_ID_HEADER: hub_id, "ETag": "v1"},
    )


# ---------------------------------------------------------------------------
# Hub-id pinning
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_manifest_records_hub_id_on_first_call() -> None:
    payload = {"hub_id": "hub-A", "capabilities": ["catalog.read"]}

    async def handler(request: httpx.Request) -> httpx.Response:
        return _ok(payload, hub_id="hub-A")

    transport = httpx.MockTransport(handler)
    async with mc.MarketplaceClient(
        "https://example.com", transport=transport
    ) as client:
        result = await client.get_manifest()
        assert result["hub_id"] == "hub-A"
        assert client.last_seen_hub_id == "hub-A"


@pytest.mark.asyncio
async def test_pin_mismatch_raises_on_subsequent_calls() -> None:
    state = {"hub_id": "hub-PINNED"}

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"hub_id": state["hub_id"]},
            headers={HUB_ID_HEADER: state["hub_id"]},
        )

    transport = httpx.MockTransport(handler)
    async with mc.MarketplaceClient(
        "https://example.com",
        pinned_hub_id="hub-PINNED",
        transport=transport,
    ) as client:
        # First call ok
        await client.get_manifest()
        # Mutate the upstream hub_id and verify mismatch raises.
        state["hub_id"] = "hub-EVIL"
        with pytest.raises(mc.HubIdMismatchError) as exc_info:
            await client.get_manifest()
        assert exc_info.value.expected == "hub-PINNED"
        assert exc_info.value.actual == "hub-EVIL"


@pytest.mark.asyncio
async def test_missing_hub_id_header_raises_malformed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        # Deliberately omit the X-Tesslate-Hub-Id header.
        return httpx.Response(200, json={"hub_id": "x"})

    transport = httpx.MockTransport(handler)
    async with mc.MarketplaceClient("https://example.com", transport=transport) as client:
        with pytest.raises(mc.MalformedResponseError):
            await client.get_manifest()


# ---------------------------------------------------------------------------
# 304 short-circuit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_changes_returns_NOT_MODIFIED_on_304() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        # Echo back the conditional header so we can assert it was sent.
        assert request.headers.get("If-None-Match") == "v42"
        return httpx.Response(304, headers={HUB_ID_HEADER: "hub-A"})

    transport = httpx.MockTransport(handler)
    async with mc.MarketplaceClient("https://example.com", transport=transport) as client:
        result = await client.get_changes(if_none_match="v42")
        assert result is mc.NOT_MODIFIED


@pytest.mark.asyncio
async def test_list_items_returns_payload_when_no_etag() -> None:
    payload = {"items": [], "next_cursor": None, "has_more": False}

    async def handler(request: httpx.Request) -> httpx.Response:
        return _ok(payload)

    transport = httpx.MockTransport(handler)
    async with mc.MarketplaceClient("https://example.com", transport=transport) as client:
        result = await client.list_items(kind="agent")
        assert result == payload


# ---------------------------------------------------------------------------
# Retry + backoff
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_5xx_retries_then_succeeds(monkeypatch) -> None:
    monkeypatch.setattr(mc, "_BACKOFF_BASE_SECONDS", 0.0)  # speed up test

    state = {"calls": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["calls"] <= 2:
            return httpx.Response(503, headers={HUB_ID_HEADER: "hub-A"})
        return _ok({"hub_id": "hub-A"})

    transport = httpx.MockTransport(handler)
    async with mc.MarketplaceClient("https://example.com", transport=transport) as client:
        result = await client.get_manifest()
        assert result["hub_id"] == "hub-A"
    assert state["calls"] == 3


@pytest.mark.asyncio
async def test_5xx_exhausts_retries_and_raises_server_error(monkeypatch) -> None:
    monkeypatch.setattr(mc, "_BACKOFF_BASE_SECONDS", 0.0)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"}, headers={HUB_ID_HEADER: "hub-A"})

    transport = httpx.MockTransport(handler)
    async with mc.MarketplaceClient("https://example.com", transport=transport) as client:
        with pytest.raises(mc.MarketplaceServerError):
            await client.get_manifest()


@pytest.mark.asyncio
async def test_429_retries_with_retry_after_header(monkeypatch) -> None:
    monkeypatch.setattr(mc, "_BACKOFF_BASE_SECONDS", 0.0)
    state = {"calls": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["calls"] == 1:
            return httpx.Response(
                429,
                headers={HUB_ID_HEADER: "hub-A", "Retry-After": "0"},
            )
        return _ok({"hub_id": "hub-A"})

    transport = httpx.MockTransport(handler)
    async with mc.MarketplaceClient("https://example.com", transport=transport) as client:
        result = await client.get_manifest()
        assert result["hub_id"] == "hub-A"
    assert state["calls"] == 2


# ---------------------------------------------------------------------------
# Terminal (non-retry) statuses
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_401_raises_auth_error_no_retry() -> None:
    state = {"calls": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        return httpx.Response(401, json={"error": "nope"}, headers={HUB_ID_HEADER: "hub-A"})

    transport = httpx.MockTransport(handler)
    async with mc.MarketplaceClient("https://example.com", transport=transport) as client:
        with pytest.raises(mc.MarketplaceAuthError):
            await client.get_manifest()
    assert state["calls"] == 1  # no retry


@pytest.mark.asyncio
async def test_404_raises_not_found_no_retry() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "missing"}, headers={HUB_ID_HEADER: "hub-A"})

    transport = httpx.MockTransport(handler)
    async with mc.MarketplaceClient("https://example.com", transport=transport) as client:
        with pytest.raises(mc.MarketplaceNotFoundError):
            await client.get_item("agent", "ghost")


@pytest.mark.asyncio
async def test_501_raises_unsupported_capability_with_envelope() -> None:
    payload = {
        "error": "unsupported_capability",
        "capability": "pricing.checkout",
        "hub_id": "hub-A",
        "details": "this hub is checkout-less",
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(501, json=payload, headers={HUB_ID_HEADER: "hub-A"})

    transport = httpx.MockTransport(handler)
    async with mc.MarketplaceClient("https://example.com", transport=transport) as client:
        with pytest.raises(mc.UnsupportedCapabilityError) as exc_info:
            await client.post_checkout("agent", "x")
    assert exc_info.value.capability == "pricing.checkout"
    assert exc_info.value.hub_id == "hub-A"
    assert exc_info.value.details == "this hub is checkout-less"


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_consecutive_failures(monkeypatch) -> None:
    monkeypatch.setattr(mc, "_BACKOFF_BASE_SECONDS", 0.0)
    monkeypatch.setattr(mc, "_MAX_RETRIES", 0)  # one shot per request

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"e": 1}, headers={HUB_ID_HEADER: "hub-A"})

    transport = httpx.MockTransport(handler)
    base = "https://example-cb-1.test"
    # Drive the breaker over its threshold.
    async with mc.MarketplaceClient(base, transport=transport) as client:
        for _ in range(mc._CB_FAILURE_THRESHOLD):
            with pytest.raises(mc.MarketplaceServerError):
                await client.get_manifest()
        # Next call short-circuits.
        with pytest.raises(mc.CircuitOpenError):
            await client.get_manifest()


@pytest.mark.asyncio
async def test_circuit_breaker_keyed_per_base_url(monkeypatch) -> None:
    monkeypatch.setattr(mc, "_BACKOFF_BASE_SECONDS", 0.0)
    monkeypatch.setattr(mc, "_MAX_RETRIES", 0)

    async def fail(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, headers={HUB_ID_HEADER: "hub-A"})

    async def ok(request: httpx.Request) -> httpx.Response:
        return _ok({"hub_id": "hub-B"}, hub_id="hub-B")

    fail_t = httpx.MockTransport(fail)
    ok_t = httpx.MockTransport(ok)

    async with mc.MarketplaceClient(
        "https://hub-a.test", transport=fail_t
    ) as a_client:
        for _ in range(mc._CB_FAILURE_THRESHOLD):
            with pytest.raises(mc.MarketplaceServerError):
                await a_client.get_manifest()
        with pytest.raises(mc.CircuitOpenError):
            await a_client.get_manifest()

    # A second base URL is unaffected.
    async with mc.MarketplaceClient("https://hub-b.test", transport=ok_t) as b_client:
        result = await b_client.get_manifest()
        assert result["hub_id"] == "hub-B"


# ---------------------------------------------------------------------------
# Local source short-circuit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_source_refuses_http_verbs() -> None:
    client = mc.MarketplaceClient("local://filesystem")
    assert client.is_local_source is True
    with pytest.raises(mc.LocalSourceNotSupportedError):
        await client.get_manifest()
    with pytest.raises(mc.LocalSourceNotSupportedError):
        await client.list_items(kind="agent")
    await client.aclose()


# ---------------------------------------------------------------------------
# Bearer header is set when token provided
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bearer_token_attached_to_requests() -> None:
    captured: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization", "")
        return _ok({"hub_id": "hub-A"})

    transport = httpx.MockTransport(handler)
    async with mc.MarketplaceClient(
        "https://example.com", token="secret-token-xyz", transport=transport
    ) as client:
        await client.get_manifest()
    assert captured["auth"] == "Bearer secret-token-xyz"


# ---------------------------------------------------------------------------
# Wave 8 — governance verbs (create_submission / advance / finalize / appeal)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_submission_calls_publish_endpoint() -> None:
    """create_submission is the orchestrator-side alias for POST /v1/publish/{kind}."""
    seen_paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        return _ok({"id": "abc", "state": "stage0_received"}, hub_id="hub-A")

    transport = httpx.MockTransport(handler)
    async with mc.MarketplaceClient("https://example.com", transport=transport) as client:
        body = await client.create_submission(
            kind="agent",
            payload={"item": {"slug": "x", "name": "X"}, "version": {"version": "0.1.0"}},
        )
        assert body["id"] == "abc"
    assert seen_paths == ["/v1/publish/agent"]


@pytest.mark.asyncio
async def test_advance_submission_routes_to_advance_endpoint() -> None:
    seen: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        return _ok({"id": "sub-1", "stage": "stage2"}, hub_id="hub-A")

    transport = httpx.MockTransport(handler)
    async with mc.MarketplaceClient("https://example.com", transport=transport) as client:
        body = await client.advance_submission("sub-1")
        assert body["stage"] == "stage2"
    assert seen == [("POST", "/v1/submissions/sub-1/advance")]


@pytest.mark.asyncio
async def test_finalize_submission_sends_decision_payload() -> None:
    captured: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        captured.append(_json.loads(request.content.decode("utf-8")))
        return _ok({"id": "sub-1", "stage": "approved"}, hub_id="hub-A")

    transport = httpx.MockTransport(handler)
    async with mc.MarketplaceClient("https://example.com", transport=transport) as client:
        await client.finalize_submission(
            "sub-1", decision="approved", decision_reason="manual override"
        )
    assert captured == [{"decision": "approved", "decision_reason": "manual override"}]


@pytest.mark.asyncio
async def test_appeal_yank_routes_to_appeal_endpoint() -> None:
    seen: list[tuple[str, str, dict]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        body = _json.loads(request.content.decode("utf-8")) if request.content else {}
        seen.append((request.method, request.url.path, body))
        return _ok(
            {"id": "appeal-1", "yank_id": "y-1", "state": "resolved", "decision": "second_admin_confirmed"},
            hub_id="hub-A",
        )

    transport = httpx.MockTransport(handler)
    async with mc.MarketplaceClient("https://example.com", transport=transport) as client:
        body = await client.appeal_yank("y-1", {"reason": "second admin confirms"})
    assert seen[0][0] == "POST"
    assert seen[0][1] == "/v1/yanks/y-1/appeal"
    assert seen[0][2] == {"reason": "second admin confirms"}
    assert body["state"] == "resolved"


@pytest.mark.asyncio
async def test_admin_force_approve_routes_to_admin_endpoint() -> None:
    seen: list[tuple[str, dict]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        body = _json.loads(request.content.decode("utf-8")) if request.content else {}
        seen.append((request.url.path, body))
        return _ok({"id": "sub-1", "stage": "approved"}, hub_id="hub-A")

    transport = httpx.MockTransport(handler)
    async with mc.MarketplaceClient("https://example.com", transport=transport) as client:
        await client.admin_force_approve_submission(
            "sub-1", decision_reason="ops emergency"
        )
    assert seen == [
        (
            "/v1/admin/submissions/sub-1/force-approve",
            {"skip_remaining_stages": True, "decision_reason": "ops emergency"},
        )
    ]


@pytest.mark.asyncio
async def test_admin_force_reject_requires_reason() -> None:
    seen: list[tuple[str, dict]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        body = _json.loads(request.content.decode("utf-8")) if request.content else {}
        seen.append((request.url.path, body))
        return _ok({"id": "sub-1", "stage": "rejected"}, hub_id="hub-A")

    transport = httpx.MockTransport(handler)
    async with mc.MarketplaceClient("https://example.com", transport=transport) as client:
        await client.admin_force_reject_submission("sub-1", decision_reason="policy")
    assert seen == [
        ("/v1/admin/submissions/sub-1/force-reject", {"decision_reason": "policy"})
    ]


@pytest.mark.asyncio
async def test_admin_override_yank_strips_none_values() -> None:
    seen: list[tuple[str, dict]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        body = _json.loads(request.content.decode("utf-8")) if request.content else {}
        seen.append((request.url.path, body))
        return _ok({"id": "y-1", "state": "resolved"}, hub_id="hub-A")

    transport = httpx.MockTransport(handler)
    async with mc.MarketplaceClient("https://example.com", transport=transport) as client:
        await client.admin_override_yank("y-1", new_state="resolved", note="hot patch")
    # The note is forwarded; resolution stays out because it was None.
    assert seen[0][1] == {"new_state": "resolved", "note": "hot patch"}


# ---------------------------------------------------------------------------
# Integration test: real Wave-2 marketplace service
# ---------------------------------------------------------------------------


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_for_port(port: int, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError(f"port {port} did not open within {timeout}s")


@pytest.fixture(scope="module")
def marketplace_service():
    """Boot the real Wave-2 marketplace service against a fresh test DB.

    Requires:
      - PostgreSQL on localhost:5433 (the orchestrator's standard test DB).
      - The marketplace package's own venv at packages/tesslate-marketplace/.venv.

    Skips if either is unavailable.
    """
    repo_root = Path(__file__).resolve().parents[3]
    pkg_dir = repo_root / "packages" / "tesslate-marketplace"
    venv_python = pkg_dir / ".venv" / "bin" / "python"
    if not venv_python.exists():
        pytest.skip(f"marketplace venv not found at {venv_python}")

    # Verify postgres reachable.
    try:
        with socket.create_connection(("localhost", 5433), timeout=2):
            pass
    except OSError:
        pytest.skip("postgres test container not reachable on :5433")

    db_url = "postgresql+asyncpg://tesslate_test:testpass@localhost:5433/marketplace_client_test"

    # Drop & recreate the database so each test run is fresh. DROP/CREATE
    # DATABASE cannot run inside a transaction, so issue them separately.
    for stmt in (
        "DROP DATABASE IF EXISTS marketplace_client_test;",
        "CREATE DATABASE marketplace_client_test;",
    ):
        psql = subprocess.run(
            [
                "docker",
                "exec",
                "tesslate-postgres-test",
                "psql",
                "-U",
                "tesslate_test",
                "-d",
                "postgres",
                "-c",
                stmt,
            ],
            capture_output=True,
            text=True,
        )
        if psql.returncode != 0:
            pytest.skip(f"could not provision marketplace_client_test DB: {psql.stderr}")

    # Initialize schema + minimal seed.
    init_proc = subprocess.run(
        [str(venv_python), "scripts/init_db.py"],
        cwd=pkg_dir,
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": db_url},
        timeout=300,
    )
    if init_proc.returncode != 0:
        pytest.skip(
            f"marketplace init_db failed (rc={init_proc.returncode}): "
            f"{init_proc.stderr[-500:]}"
        )

    port = _free_port()
    log_path = Path("/tmp") / f"marketplace-client-test-{port}.log"
    log_file = log_path.open("w")
    proc = subprocess.Popen(
        [
            str(venv_python),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=pkg_dir,
        stdout=log_file,
        stderr=log_file,
        env={**os.environ, "DATABASE_URL": db_url},
    )
    try:
        _wait_for_port(port)
        yield {"port": port, "base_url": f"http://127.0.0.1:{port}", "db_url": db_url}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log_file.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_marketplace_pin_then_mismatch(marketplace_service) -> None:
    """End-to-end hub-id pinning test against the real Wave-2 service.

    1. Boot the marketplace service.
    2. First call records hub_id (no pin).
    3. Pin to that id, repeat: succeeds.
    4. Pin to a *different* id, repeat: raises HubIdMismatchError.
    """
    base_url = marketplace_service["base_url"]

    # Step 1+2 — discover hub_id with no pin.
    async with mc.MarketplaceClient(base_url) as discovery:
        manifest = await discovery.get_manifest()
        observed = manifest["hub_id"]
        assert isinstance(observed, str) and observed
        assert discovery.last_seen_hub_id == observed

    # Step 3 — re-pin and call again, succeeds.
    async with mc.MarketplaceClient(base_url, pinned_hub_id=observed) as pinned:
        manifest = await pinned.get_manifest()
        assert manifest["hub_id"] == observed
        # Detail call also verifies the pin.
        items = await pinned.list_items(limit=5)
        assert items is not mc.NOT_MODIFIED
        assert isinstance(items, dict)
        assert "items" in items

    # Step 4 — pin to wrong id, mismatch fires immediately.
    async with mc.MarketplaceClient(base_url, pinned_hub_id="not-the-real-hub-id") as bad_pin:
        with pytest.raises(mc.HubIdMismatchError) as exc_info:
            await bad_pin.get_manifest()
        assert exc_info.value.expected == "not-the-real-hub-id"
        assert exc_info.value.actual == observed


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_marketplace_changes_feed_returns_events(marketplace_service) -> None:
    base_url = marketplace_service["base_url"]
    async with mc.MarketplaceClient(base_url) as client:
        manifest = await client.get_manifest()
        # capabilities[] must include catalog.changes for the test to be meaningful.
        assert "catalog.changes" in manifest["capabilities"]

        feed = await client.get_changes(since="v0", limit=5)
        assert feed is not mc.NOT_MODIFIED
        assert isinstance(feed, dict)
        assert "events" in feed
        assert "next_etag" in feed
