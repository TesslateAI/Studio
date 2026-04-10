"""Unit tests for the desktop models router (chat completions, model listing, usage)."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

import app.models  # noqa: F401 — register all ORM models
from app.routers.public_models import (
    ChatCompletionRequest,
    _stream_response,
    chat_completions,
    get_usage,
    list_models,
)

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_user(default_team_id=None):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.is_active = True
    user.default_team_id = default_team_id
    user.daily_credits = 100
    user.bundled_credits = 500
    user.signup_bonus_credits = 0
    user.purchased_credits = 1000
    user.total_credits = 1600
    return user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_request(model="builtin/gpt-4o", stream=True, **kwargs):
    return ChatCompletionRequest(
        model=model,
        messages=[{"role": "user", "content": "Hello"}],
        stream=stream,
        **kwargs,
    )


# ===========================================================================
# TestChatCompletions
# ===========================================================================


@pytest.mark.unit
class TestChatCompletions:
    @pytest.mark.asyncio
    @patch("app.routers.public_models.resolve_model_name", return_value="gpt-4o")
    @patch("app.routers.public_models.get_llm_client")
    @patch("app.routers.public_models.check_credits", return_value=(True, ""))
    async def test_streaming_returns_streaming_response(
        self, mock_credits, mock_get_client, mock_resolve
    ):
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client
        mock_db = AsyncMock()

        from starlette.responses import StreamingResponse

        result = await chat_completions(
            request=_build_request(stream=True),
            user=_make_user(),
            db=mock_db,
        )
        assert isinstance(result, StreamingResponse)

    @pytest.mark.asyncio
    @patch("app.routers.public_models.resolve_model_name", return_value="gpt-4o")
    @patch("app.routers.public_models.get_llm_client")
    @patch("app.routers.public_models.check_credits", return_value=(True, ""))
    @patch("app.routers.public_models.deduct_credits", new_callable=AsyncMock)
    async def test_non_streaming_returns_dict(
        self, mock_deduct, mock_credits, mock_get_client, mock_resolve
    ):
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.usage = MagicMock(prompt_tokens=100, completion_tokens=50)
        mock_response.model_dump.return_value = {"choices": [{"message": {"content": "Hi"}}]}
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client
        mock_db = AsyncMock()

        result = await chat_completions(
            request=_build_request(stream=False),
            user=_make_user(),
            db=mock_db,
        )
        assert isinstance(result, dict)
        assert "choices" in result

    @pytest.mark.asyncio
    @patch("app.routers.public_models.check_credits", return_value=(False, "Insufficient credits"))
    async def test_credit_check_failure_402(self, mock_credits):
        mock_db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await chat_completions(
                request=_build_request(stream=False),
                user=_make_user(),
                db=mock_db,
            )
        assert exc_info.value.status_code == 402

    @pytest.mark.asyncio
    @patch("app.routers.public_models.resolve_model_name", return_value="bad-model")
    @patch(
        "app.routers.public_models.get_llm_client",
        side_effect=ValueError("Unknown model: bad-model"),
    )
    @patch("app.routers.public_models.check_credits", return_value=(True, ""))
    async def test_invalid_model_400(self, mock_credits, mock_get_client, mock_resolve):
        mock_db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await chat_completions(
                request=_build_request(model="bad-model", stream=False),
                user=_make_user(),
                db=mock_db,
            )
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    @patch("app.routers.public_models.resolve_model_name", return_value="claude-sonnet")
    @patch("app.routers.public_models.get_llm_client")
    @patch("app.routers.public_models.check_credits", return_value=(True, ""))
    @patch("app.routers.public_models.deduct_credits", new_callable=AsyncMock)
    async def test_byok_skips_credit_check(
        self, mock_deduct, mock_credits, mock_get_client, mock_resolve
    ):
        """BYOK model still calls check_credits but the function allows it through."""
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.usage = MagicMock(prompt_tokens=50, completion_tokens=25)
        mock_response.model_dump.return_value = {"choices": [{"message": {"content": "ok"}}]}
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client
        mock_db = AsyncMock()

        result = await chat_completions(
            request=_build_request(model="byok/my-key/claude-sonnet", stream=False),
            user=_make_user(),
            db=mock_db,
        )
        assert isinstance(result, dict)
        mock_credits.assert_awaited_once()


# ===========================================================================
# TestStreamResponse
# ===========================================================================


@pytest.mark.unit
class TestStreamResponse:
    @pytest.mark.asyncio
    async def test_stream_response_yields_sse_format(self):
        mock_client = AsyncMock()

        chunk = MagicMock()
        chunk.model_dump.return_value = {"id": "chatcmpl-1", "choices": []}
        chunk.usage = None

        class _FakeStream:
            async def __aiter__(self):
                yield chunk

        mock_client.chat.completions.create = AsyncMock(return_value=_FakeStream())
        params = {"model": "gpt-4o", "messages": [], "stream": True}

        chunks = []
        async for c in _stream_response(
            mock_client, params, _make_user(), "builtin/gpt-4o", AsyncMock()
        ):
            chunks.append(c)

        assert any(c.startswith("data: {") for c in chunks)
        assert chunks[-1] == "data: [DONE]\n\n"

    @pytest.mark.asyncio
    async def test_stream_response_ends_with_done(self):
        mock_client = AsyncMock()

        class _EmptyStream:
            async def __aiter__(self):
                return
                yield  # make it an async generator

        mock_client.chat.completions.create = AsyncMock(return_value=_EmptyStream())
        params = {"model": "gpt-4o", "messages": [], "stream": True}

        chunks = []
        async for c in _stream_response(
            mock_client, params, _make_user(), "builtin/gpt-4o", AsyncMock()
        ):
            chunks.append(c)

        assert chunks[-1] == "data: [DONE]\n\n"

    @pytest.mark.asyncio
    async def test_stream_response_deducts_credits(self):
        mock_client = AsyncMock()

        chunk = MagicMock()
        chunk.model_dump.return_value = {"id": "chatcmpl-1"}
        chunk.usage = MagicMock(prompt_tokens=200, completion_tokens=100)

        # _stream_response does: stream = await client.chat.completions.create(**params)
        # then: async for chunk in stream — so create() must return an async iterable.
        class _FakeStream:
            async def __aiter__(self):
                yield chunk

        mock_client.chat.completions.create = AsyncMock(return_value=_FakeStream())
        params = {"model": "gpt-4o", "messages": [], "stream": True}

        user = _make_user()

        # Build a mock async-context-manager session that AsyncSessionLocal() returns.
        mock_credit_db = AsyncMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_credit_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_deduct = AsyncMock()

        with (
            patch("app.database.AsyncSessionLocal", return_value=mock_session_ctx),
            patch("app.routers.public_models.deduct_credits", mock_deduct),
        ):
            chunks = []
            async for c in _stream_response(
                mock_client, params, user, "builtin/gpt-4o", AsyncMock()
            ):
                chunks.append(c)

        mock_deduct.assert_awaited_once()
        call_kwargs = mock_deduct.call_args
        assert call_kwargs.kwargs["tokens_in"] == 200
        assert call_kwargs.kwargs["tokens_out"] == 100


# ===========================================================================
# TestListModels
# ===========================================================================


@pytest.mark.unit
class TestListModels:
    @pytest.mark.asyncio
    @patch(
        "app.routers.public_models.BUILTIN_PROVIDERS",
        {
            "openai": {
                "name": "OpenAI",
                "description": "GPT models",
                "website": "https://openai.com",
            },
        },
    )
    async def test_list_models_basic(self):
        mock_db = AsyncMock()
        # Mock the UserAPIKey query to return no key
        key_result = MagicMock()
        key_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=key_result)

        response = MagicMock()
        response.headers = {}

        with patch("app.routers.public_models.LiteLLMService") as MockLiteLLM:
            svc = AsyncMock()
            svc.get_available_models = AsyncMock(
                return_value=[{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}]
            )
            svc.get_model_info = AsyncMock(return_value=[])
            MockLiteLLM.return_value = svc

            result = await list_models(
                response=response,
                user=_make_user(),
                db=mock_db,
            )

        assert result["object"] == "list"
        assert len(result["data"]) == 2
        assert result["data"][0]["id"] == "builtin/gpt-4o"
        assert result["data"][0]["is_byok"] is False
        assert len(result["providers"]) == 1
        assert result["providers"][0]["provider"] == "openai"

    @pytest.mark.asyncio
    @patch("app.routers.public_models.BUILTIN_PROVIDERS", {})
    async def test_list_models_litellm_failure(self):
        """Graceful degradation when LiteLLM is unreachable."""
        mock_db = AsyncMock()
        # Batch provider key query returns empty set
        key_result = MagicMock()
        key_result.all.return_value = []
        mock_db.execute = AsyncMock(return_value=key_result)

        response = MagicMock()
        response.headers = {}

        with patch("app.routers.public_models.LiteLLMService") as MockLiteLLM:
            svc = AsyncMock()
            svc.get_available_models = AsyncMock(side_effect=Exception("Connection refused"))
            MockLiteLLM.return_value = svc

            result = await list_models(
                response=response,
                user=_make_user(),
                db=mock_db,
            )

        assert result["object"] == "list"
        assert result["data"] == []
        # Providers still listed (just with has_key=False)
        assert isinstance(result["providers"], list)

    @pytest.mark.asyncio
    @patch(
        "app.routers.public_models.BUILTIN_PROVIDERS",
        {
            "openai": {"name": "OpenAI", "description": "GPT", "website": "https://openai.com"},
            "anthropic": {
                "name": "Anthropic",
                "description": "Claude",
                "website": "https://anthropic.com",
            },
        },
    )
    async def test_list_models_includes_providers(self):
        mock_db = AsyncMock()
        # Batch query returns both providers as having keys
        key_result = MagicMock()
        key_result.all.return_value = [("openai",), ("anthropic",)]
        mock_db.execute = AsyncMock(return_value=key_result)

        response = MagicMock()
        response.headers = {}

        with patch("app.routers.public_models.LiteLLMService") as MockLiteLLM:
            svc = AsyncMock()
            svc.get_available_models = AsyncMock(return_value=[])
            svc.get_model_info = AsyncMock(return_value=[])
            MockLiteLLM.return_value = svc

            result = await list_models(
                response=response,
                user=_make_user(),
                db=mock_db,
            )

        assert len(result["providers"]) == 2
        provider_slugs = {p["provider"] for p in result["providers"]}
        assert "openai" in provider_slugs
        assert "anthropic" in provider_slugs
        for p in result["providers"]:
            assert p["has_key"] is True


# ===========================================================================
# TestUsage
# ===========================================================================


@pytest.mark.unit
class TestUsage:
    @pytest.mark.asyncio
    async def test_usage_returns_credits(self):
        user = _make_user()
        mock_db = AsyncMock()

        # Call 1: total summary
        total_result = MagicMock()
        total_result.one.return_value = (5, 120, 5000, 2000)

        # Call 2: per-model breakdown
        by_model_result = MagicMock()
        by_model_result.all.return_value = [
            ("gpt-4o", 3, 80),
            ("claude-sonnet", 2, 40),
        ]

        mock_db.execute = AsyncMock(side_effect=[total_result, by_model_result])

        result = await get_usage(user=user, db=mock_db)

        assert result["credits"]["daily"] == 100
        assert result["credits"]["bundled"] == 500
        assert result["credits"]["bonus"] == 0
        assert result["credits"]["purchased"] == 1000
        assert result["credits"]["total"] == 1600

    @pytest.mark.asyncio
    async def test_usage_30d_summary(self):
        user = _make_user()
        mock_db = AsyncMock()

        total_result = MagicMock()
        total_result.one.return_value = (10, 250, 10000, 5000)

        by_model_result = MagicMock()
        by_model_result.all.return_value = [("gpt-4o", 10, 250)]

        mock_db.execute = AsyncMock(side_effect=[total_result, by_model_result])

        result = await get_usage(user=user, db=mock_db)

        assert result["usage_30d"]["total_requests"] == 10
        assert result["usage_30d"]["total_cost_cents"] == 250
        assert result["usage_30d"]["total_tokens_in"] == 10000
        assert result["usage_30d"]["total_tokens_out"] == 5000
        assert len(result["usage_30d"]["by_model"]) == 1
        assert result["usage_30d"]["by_model"][0]["model"] == "gpt-4o"

    @pytest.mark.asyncio
    async def test_usage_empty_history(self):
        user = _make_user()
        mock_db = AsyncMock()

        total_result = MagicMock()
        total_result.one.return_value = (0, 0, 0, 0)

        by_model_result = MagicMock()
        by_model_result.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[total_result, by_model_result])

        result = await get_usage(user=user, db=mock_db)

        assert result["usage_30d"]["total_requests"] == 0
        assert result["usage_30d"]["total_cost_cents"] == 0
        assert result["usage_30d"]["total_tokens_in"] == 0
        assert result["usage_30d"]["total_tokens_out"] == 0
        assert result["usage_30d"]["by_model"] == []
