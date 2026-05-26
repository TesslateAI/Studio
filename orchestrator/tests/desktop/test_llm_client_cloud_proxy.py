"""get_llm_client: desktop + cloud-paired routes system models through the
cloud companion proxy (never the internal LiteLLM)."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest


class _FakeResult:
    def __init__(self, obj: Any) -> None:
        self._obj = obj

    def scalar_one_or_none(self) -> Any:
        return self._obj


class _FakeUser:
    """Minimal stand-in: no per-user LiteLLM key provisioned (desktop case)."""

    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.litellm_api_key = None


class _FakeDB:
    """First ``execute`` resolves the User row; later ones (the BYOK
    fallback's UserAPIKey lookup) resolve to nothing — i.e. no BYOK keys."""

    def __init__(self, user: Any) -> None:
        self._user = user
        self._calls = 0

    async def execute(self, *_args: Any, **_kwargs: Any) -> _FakeResult:
        self._calls += 1
        return _FakeResult(self._user if self._calls == 1 else None)


@pytest.fixture
def desktop_paired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENSAIL_HOME", str(tmp_path))
    monkeypatch.setenv("DEPLOYMENT_MODE", "desktop")
    monkeypatch.setenv("TESSLATE_CLOUD_URL", "https://my-cloud.example.com")
    monkeypatch.setenv("TESSLATE_CLOUD_TOKEN", "tsk_desktop_test")
    monkeypatch.setenv("LITELLM_API_BASE", "")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "")
    (tmp_path / "cache").mkdir(parents=True, exist_ok=True)

    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_unprefixed_model_routes_to_cloud_proxy(desktop_paired) -> None:
    from app.services.model_adapters import get_llm_client

    user = _FakeUser()
    client = await get_llm_client(user.id, "claude-sonnet-4.6", _FakeDB(user))  # type: ignore[arg-type]

    # Points at the cloud companion's OpenAI-compatible proxy, not LiteLLM.
    assert str(client.base_url).rstrip("/") == "https://my-cloud.example.com/api/v1"
    assert client.api_key == "tsk_desktop_test"


@pytest.mark.asyncio
async def test_no_cloud_token_does_not_route_to_proxy(
    desktop_paired, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a paired token the proxy branch is skipped — and with no other
    credentials configured, get_llm_client raises rather than silently using
    the cloud."""
    monkeypatch.delenv("TESSLATE_CLOUD_TOKEN", raising=False)

    from app.services.model_adapters import get_llm_client

    user = _FakeUser()
    with pytest.raises(ValueError, match="No LLM access configured"):
        await get_llm_client(user.id, "claude-sonnet-4.6", _FakeDB(user))  # type: ignore[arg-type]
