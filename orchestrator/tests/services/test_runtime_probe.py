"""Unit tests for RuntimeProbe."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.services.runtime_probe import RuntimeProbe, get_runtime_probe


class _FakeProc:
    def __init__(self, returncode: int, stdout: bytes = b"", raise_timeout: bool = False):
        self.returncode = returncode
        self._stdout = stdout
        self._raise_timeout = raise_timeout
        self.killed = False

    async def communicate(self):
        if self._raise_timeout:
            # Simulate a hang that asyncio.wait_for will trip.
            await asyncio.sleep(5)
        return self._stdout, b""

    def kill(self):
        self.killed = True

    async def wait(self):
        return self.returncode


@pytest.mark.asyncio
async def test_local_always_ok():
    probe = RuntimeProbe()
    result = await probe.local_available()
    assert result.ok is True
    assert result.reason is None


@pytest.mark.asyncio
async def test_docker_present():
    probe = RuntimeProbe()
    fake = _FakeProc(returncode=0, stdout=b'{"ServerVersion": "24.0.0"}')
    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake)):
        result = await probe.docker_available()
    assert result.ok is True
    assert result.reason is None


@pytest.mark.asyncio
async def test_docker_missing_binary():
    probe = RuntimeProbe()
    with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError()):
        result = await probe.docker_available()
    assert result.ok is False
    assert "unreachable" in (result.reason or "").lower()


@pytest.mark.asyncio
async def test_docker_non_zero_exit():
    probe = RuntimeProbe()
    fake = _FakeProc(returncode=1, stdout=b"")
    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake)):
        result = await probe.docker_available()
    assert result.ok is False


@pytest.mark.asyncio
async def test_docker_timeout():
    probe = RuntimeProbe()
    fake = _FakeProc(returncode=0, raise_timeout=True)
    with (
        patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake)),
        patch("app.services.runtime_probe._DOCKER_PROBE_TIMEOUT_SECONDS", 0.01),
    ):
        result = await probe.docker_available()
    assert result.ok is False
    assert fake.killed is True


@pytest.mark.asyncio
async def test_docker_server_errors_treated_as_unreachable():
    probe = RuntimeProbe()
    fake = _FakeProc(returncode=0, stdout=b'{"ServerErrors": ["cannot connect"]}')
    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake)):
        result = await probe.docker_available()
    assert result.ok is False


@pytest.mark.asyncio
async def test_docker_cache_ttl_respected():
    probe = RuntimeProbe()
    fake = _FakeProc(returncode=0, stdout=b'{"ServerVersion": "24.0.0"}')
    spawn = AsyncMock(return_value=fake)
    with patch("asyncio.create_subprocess_exec", new=spawn):
        first = await probe.docker_available()
        second = await probe.docker_available()
    assert first.ok and second.ok
    assert spawn.await_count == 1  # second call hit the cache


@pytest.mark.asyncio
async def test_docker_cache_expires(monkeypatch):
    probe = RuntimeProbe()
    fake = _FakeProc(returncode=0, stdout=b'{"ServerVersion": "24.0.0"}')
    spawn = AsyncMock(return_value=fake)
    monkeypatch.setattr("asyncio.create_subprocess_exec", spawn)

    clock = {"now": 0.0}
    import app.services.runtime_probe as rp_mod

    monkeypatch.setattr(rp_mod.time, "monotonic", lambda: clock["now"])
    await probe.docker_available()
    clock["now"] = 100.0  # beyond 30s TTL
    await probe.docker_available()
    assert spawn.await_count == 2


@pytest.mark.asyncio
async def test_docker_never_raises_on_unexpected_exception():
    probe = RuntimeProbe()
    with patch("asyncio.create_subprocess_exec", side_effect=RuntimeError("boom")):
        result = await probe.docker_available()
    assert result.ok is False
    assert result.reason


@pytest.mark.asyncio
async def test_k8s_remote_stub():
    probe = RuntimeProbe()
    result = await probe.k8s_remote_available()
    assert result.ok is False
    assert "pairing" in (result.reason or "").lower()


def test_singleton_accessor():
    assert get_runtime_probe() is get_runtime_probe()
