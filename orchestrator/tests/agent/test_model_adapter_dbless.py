"""
Tests for DB-less ``create_model_adapter`` / ``get_llm_client`` paths.

These tests verify that the agent's model adapter factory can be called
without a live database session, resolving provider API keys from
environment variables. This is used by standalone CLI tools and benchmark
harnesses that run the agent outside the orchestrator pod.

The tests exercise the dispatch + env-var plumbing only — no network
requests are issued because ``AsyncOpenAI`` construction is lazy (it does
not contact the provider until a request is made).
"""

from unittest.mock import patch

import pytest

from app.services.model_adapters import (
    BYOK_PROVIDER_ENV_VARS,
    LITELLM_API_BASE_ENV_VAR,
    LITELLM_API_KEY_ENV_VAR,
    MissingApiKeyError,
    OpenAIAdapter,
    create_model_adapter,
    get_llm_client,
)


def _clear_all_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every BYOK env var + LiteLLM env vars so tests start clean."""
    for env_var in BYOK_PROVIDER_ENV_VARS.values():
        monkeypatch.delenv(env_var, raising=False)
    monkeypatch.delenv(LITELLM_API_KEY_ENV_VAR, raising=False)
    monkeypatch.delenv(LITELLM_API_BASE_ENV_VAR, raising=False)


@pytest.mark.unit
class TestCreateModelAdapterDbLess:
    """DB-less path: ``db=None`` reads API keys from environment variables."""

    @pytest.mark.asyncio
    async def test_openai_prefix_with_env_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """openai/ prefix with OPENAI_API_KEY set → returns adapter."""
        _clear_all_provider_env(monkeypatch)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai-key")

        adapter = await create_model_adapter("openai/gpt-4o-mini", user_id=None, db=None)

        assert isinstance(adapter, OpenAIAdapter)
        # create_model_adapter strips the "openai/" routing prefix for BYOK
        assert adapter.model_name == "gpt-4o-mini"
        assert adapter.client.api_key == "sk-test-openai-key"
        assert str(adapter.client.base_url).rstrip("/") == "https://api.openai.com/v1"

    @pytest.mark.asyncio
    async def test_openai_prefix_missing_env_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """openai/ prefix without OPENAI_API_KEY → ValueError mentioning the env var."""
        _clear_all_provider_env(monkeypatch)

        with pytest.raises(ValueError) as exc_info:
            await create_model_adapter("openai/gpt-4o-mini", user_id=None, db=None)

        assert "OPENAI_API_KEY" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_anthropic_prefix_with_env_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """anthropic/ prefix with ANTHROPIC_API_KEY set → returns adapter.

        Anthropic's native ``api_type`` is not the OpenAI chat.completions
        adapter, so callers that want the OpenAI-compatible endpoint must
        force ``provider="openai"``. The DB-less env-var lookup still keys
        off ``ANTHROPIC_API_KEY`` because the routing prefix is
        ``anthropic/``.
        """
        _clear_all_provider_env(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")

        adapter = await create_model_adapter(
            "anthropic/claude-3-5-sonnet", db=None, provider="openai"
        )

        assert isinstance(adapter, OpenAIAdapter)
        assert adapter.model_name == "claude-3-5-sonnet"
        assert adapter.client.api_key == "sk-ant-test-key"

    @pytest.mark.asyncio
    async def test_openrouter_prefix_with_env_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """openrouter/ prefix with OPENROUTER_API_KEY set → returns adapter."""
        _clear_all_provider_env(monkeypatch)
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")

        adapter = await create_model_adapter("openrouter/anthropic/claude-3.5-sonnet", db=None)

        assert isinstance(adapter, OpenAIAdapter)
        # Only the leading "openrouter/" segment is stripped; the rest is the
        # API-level model name passed to the provider.
        assert adapter.model_name == "anthropic/claude-3.5-sonnet"
        assert adapter.client.api_key == "sk-or-test-key"
        assert "openrouter.ai" in str(adapter.client.base_url)

    @pytest.mark.asyncio
    async def test_groq_prefix_with_env_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """groq/ prefix with GROQ_API_KEY set → returns adapter."""
        _clear_all_provider_env(monkeypatch)
        monkeypatch.setenv("GROQ_API_KEY", "gsk-test-key")

        adapter = await create_model_adapter("groq/llama-3.1-70b", db=None)

        assert isinstance(adapter, OpenAIAdapter)
        assert adapter.model_name == "llama-3.1-70b"
        assert adapter.client.api_key == "gsk-test-key"
        assert "groq.com" in str(adapter.client.base_url)

    @pytest.mark.asyncio
    async def test_together_prefix_with_env_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """together/ prefix with TOGETHER_API_KEY set → returns adapter."""
        _clear_all_provider_env(monkeypatch)
        monkeypatch.setenv("TOGETHER_API_KEY", "together-test-key")

        adapter = await create_model_adapter("together/mistralai/Mixtral-8x7B", db=None)

        assert isinstance(adapter, OpenAIAdapter)
        assert adapter.model_name == "mistralai/Mixtral-8x7B"
        assert adapter.client.api_key == "together-test-key"

    @pytest.mark.asyncio
    async def test_deepseek_prefix_with_env_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """deepseek/ prefix with DEEPSEEK_API_KEY set → returns adapter."""
        _clear_all_provider_env(monkeypatch)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-test-key")

        adapter = await create_model_adapter("deepseek/deepseek-chat", db=None)

        assert isinstance(adapter, OpenAIAdapter)
        assert adapter.model_name == "deepseek-chat"
        assert adapter.client.api_key == "ds-test-key"

    @pytest.mark.asyncio
    async def test_fireworks_prefix_with_env_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """fireworks/ prefix with FIREWORKS_API_KEY set → returns adapter."""
        _clear_all_provider_env(monkeypatch)
        monkeypatch.setenv("FIREWORKS_API_KEY", "fw-test-key")

        adapter = await create_model_adapter(
            "fireworks/accounts/fireworks/models/llama-v3p1-70b", db=None
        )

        assert isinstance(adapter, OpenAIAdapter)
        assert adapter.client.api_key == "fw-test-key"

    @pytest.mark.asyncio
    async def test_builtin_prefix_uses_litellm_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """builtin/ prefix reads LITELLM_MASTER_KEY + LITELLM_API_BASE from env."""
        _clear_all_provider_env(monkeypatch)
        monkeypatch.setenv(LITELLM_API_KEY_ENV_VAR, "litellm-master-123")
        monkeypatch.setenv(LITELLM_API_BASE_ENV_VAR, "http://litellm.test:4000/v1")

        adapter = await create_model_adapter("builtin/claude-opus-4.6", db=None)

        assert isinstance(adapter, OpenAIAdapter)
        assert adapter.model_name == "claude-opus-4.6"
        assert adapter.client.api_key == "litellm-master-123"
        assert "litellm.test" in str(adapter.client.base_url)

    @pytest.mark.asyncio
    async def test_no_prefix_uses_litellm_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A bare model name with no prefix also routes to LiteLLM."""
        _clear_all_provider_env(monkeypatch)
        monkeypatch.setenv(LITELLM_API_KEY_ENV_VAR, "litellm-bare-key")
        monkeypatch.setenv(LITELLM_API_BASE_ENV_VAR, "http://litellm.test:4000/v1")

        adapter = await create_model_adapter("claude-sonnet-4.6", db=None)

        assert isinstance(adapter, OpenAIAdapter)
        assert adapter.model_name == "claude-sonnet-4.6"
        assert adapter.client.api_key == "litellm-bare-key"

    @pytest.mark.asyncio
    async def test_litellm_missing_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """builtin/ path with no LITELLM_MASTER_KEY → ValueError names the env var."""
        _clear_all_provider_env(monkeypatch)
        # Clear any settings-level fallback too so the error path is reached.
        from app.config import get_settings

        get_settings.cache_clear()
        settings = get_settings()
        monkeypatch.setattr(settings, "litellm_master_key", "", raising=False)
        monkeypatch.setattr(settings, "litellm_api_base", "", raising=False)

        with pytest.raises(ValueError) as exc_info:
            await create_model_adapter("builtin/claude-opus-4.6", db=None)

        assert LITELLM_API_KEY_ENV_VAR in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_unknown_provider_prefix_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An unknown prefix cannot fall back to UserCustomModel without a DB."""
        _clear_all_provider_env(monkeypatch)

        with pytest.raises(ValueError) as exc_info:
            await create_model_adapter("mystery-inc/some-model", db=None)

        assert "Unknown provider" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_custom_prefix_rejected_without_db(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """custom/ prefix needs a DB to resolve UserProvider → error is explicit."""
        _clear_all_provider_env(monkeypatch)

        with pytest.raises(ValueError) as exc_info:
            await create_model_adapter("custom/my-ollama/neural-7b", db=None)

        msg = str(exc_info.value)
        assert "Custom provider" in msg
        assert "database session" in msg

    @pytest.mark.asyncio
    async def test_get_llm_client_dbless_direct(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_llm_client is also callable directly with db=None."""
        _clear_all_provider_env(monkeypatch)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-direct-test")

        client = await get_llm_client(user_id=None, model_name="openai/gpt-4o", db=None)

        assert client.api_key == "sk-direct-test"

    @pytest.mark.asyncio
    async def test_dbless_respects_custom_adapter_kwargs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Extra kwargs (temperature, max_tokens) flow through to the adapter."""
        _clear_all_provider_env(monkeypatch)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-kwargs-test")

        adapter = await create_model_adapter(
            "openai/gpt-4o-mini",
            db=None,
            temperature=0.1,
            max_tokens=4096,
        )

        assert adapter.temperature == 0.1
        assert adapter.max_tokens == 4096


@pytest.mark.unit
class TestCreateModelAdapterDbBackedRegression:
    """Regression: the existing DB-backed path is untouched."""

    @pytest.mark.asyncio
    async def test_db_backed_path_still_uses_get_llm_client(self) -> None:
        """DB-backed calls still route through the mocked get_llm_client."""
        from unittest.mock import AsyncMock
        from uuid import uuid4

        with patch("app.services.model_adapters.get_llm_client") as mock_get_client:
            mock_get_client.return_value = AsyncMock()
            user_id = uuid4()
            mock_db = AsyncMock()

            adapter = await create_model_adapter("gpt-4o", user_id=user_id, db=mock_db)

            assert isinstance(adapter, OpenAIAdapter)
            assert adapter.model_name == "gpt-4o"
            mock_get_client.assert_called_once_with(user_id, "gpt-4o", mock_db)


@pytest.mark.unit
class TestBareNameRouting:
    """
    Bare-name routing: a model name with no routing prefix should infer
    the provider in standalone mode. This is the path benchmark harnesses
    use when they pass raw model ids like ``gpt-4o`` or
    ``claude-3-5-sonnet-20241022``.
    """

    @pytest.mark.asyncio
    async def test_bare_gpt_routes_to_openai(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Bare ``gpt-4o`` routes to OpenAI when OPENAI_API_KEY is set."""
        _clear_all_provider_env(monkeypatch)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-bare-openai")

        adapter = await create_model_adapter("gpt-4o", db=None)

        assert isinstance(adapter, OpenAIAdapter)
        assert adapter.model_name == "gpt-4o"
        assert adapter.client.api_key == "sk-bare-openai"
        assert "api.openai.com" in str(adapter.client.base_url)

    @pytest.mark.asyncio
    async def test_bare_o3_routes_to_openai(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Bare ``o3-mini`` routes to OpenAI (reasoning-model family)."""
        _clear_all_provider_env(monkeypatch)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-o3-openai")

        adapter = await create_model_adapter("o3-mini", db=None)

        assert isinstance(adapter, OpenAIAdapter)
        assert adapter.model_name == "o3-mini"
        assert adapter.client.api_key == "sk-o3-openai"
        assert "api.openai.com" in str(adapter.client.base_url)

    @pytest.mark.asyncio
    async def test_bare_o1_routes_to_openai(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Bare ``o1-preview`` routes to OpenAI."""
        _clear_all_provider_env(monkeypatch)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-o1-openai")

        adapter = await create_model_adapter("o1-preview", db=None)

        assert adapter.client.api_key == "sk-o1-openai"
        assert "api.openai.com" in str(adapter.client.base_url)

    @pytest.mark.asyncio
    async def test_bare_gpt_missing_key_raises_missing_api_key_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Bare ``gpt-4o`` without ``OPENAI_API_KEY`` raises
        :class:`MissingApiKeyError` — not a silent LiteLLM fall-through.
        """
        _clear_all_provider_env(monkeypatch)

        with pytest.raises(MissingApiKeyError) as exc_info:
            await create_model_adapter("gpt-4o", db=None)

        assert exc_info.value.env_var == "OPENAI_API_KEY"
        assert "OPENAI_API_KEY" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_bare_claude_prefers_anthropic_when_key_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Bare ``claude-3-5-sonnet-20241022`` with ``ANTHROPIC_API_KEY`` set
        routes to the Anthropic direct endpoint.
        """
        _clear_all_provider_env(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-bare")

        adapter = await create_model_adapter("claude-3-5-sonnet-20241022", db=None)

        assert isinstance(adapter, OpenAIAdapter)
        assert adapter.model_name == "claude-3-5-sonnet-20241022"
        assert adapter.client.api_key == "sk-ant-bare"
        assert "api.anthropic.com" in str(adapter.client.base_url)

    @pytest.mark.asyncio
    async def test_bare_claude_falls_back_to_openrouter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Bare ``claude-3-5-sonnet-20241022`` with only ``OPENROUTER_API_KEY``
        set falls back to OpenRouter deterministically.
        """
        _clear_all_provider_env(monkeypatch)
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-bare")

        adapter = await create_model_adapter("claude-3-5-sonnet-20241022", db=None)

        assert isinstance(adapter, OpenAIAdapter)
        assert adapter.client.api_key == "sk-or-bare"
        assert "openrouter.ai" in str(adapter.client.base_url)

    @pytest.mark.asyncio
    async def test_bare_claude_anthropic_preferred_over_openrouter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        When both ANTHROPIC_API_KEY and OPENROUTER_API_KEY are set, the
        bare ``claude-*`` fallback MUST pick Anthropic — deterministic
        regardless of env-var insertion order.
        """
        _clear_all_provider_env(monkeypatch)
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-loser")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-winner")

        adapter = await create_model_adapter("claude-3-5-sonnet-20241022", db=None)

        assert adapter.client.api_key == "sk-ant-winner"
        assert "api.anthropic.com" in str(adapter.client.base_url)

    @pytest.mark.asyncio
    async def test_bare_claude_falls_through_to_litellm_when_no_keys(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Bare ``claude-*`` with neither Anthropic nor OpenRouter keys set
        falls through to the LiteLLM proxy (preserves existing behavior
        for users running inside the orchestrator pod).
        """
        _clear_all_provider_env(monkeypatch)
        monkeypatch.setenv(LITELLM_API_KEY_ENV_VAR, "litellm-fallback")
        monkeypatch.setenv(LITELLM_API_BASE_ENV_VAR, "http://litellm.test:4000/v1")

        adapter = await create_model_adapter("claude-3-5-sonnet-20241022", db=None)

        assert adapter.client.api_key == "litellm-fallback"
        assert "litellm.test" in str(adapter.client.base_url)

    @pytest.mark.asyncio
    async def test_anthropic_prefix_without_explicit_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        ``anthropic/claude-3-5-sonnet`` in standalone mode should work
        WITHOUT the caller having to pass ``provider="openai"`` (that
        dance was a DB-backed wart the standalone path should not
        inherit).
        """
        _clear_all_provider_env(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-auto")

        adapter = await create_model_adapter("anthropic/claude-3-5-sonnet-20241022", db=None)

        assert isinstance(adapter, OpenAIAdapter)
        assert adapter.model_name == "claude-3-5-sonnet-20241022"
        assert adapter.client.api_key == "sk-ant-auto"
        assert "api.anthropic.com" in str(adapter.client.base_url)


@pytest.mark.unit
class TestMissingApiKeyErrorType:
    """
    ``MissingApiKeyError`` is a ValueError subclass with an ``env_var``
    attribute so callers can programmatically prompt the user for the
    specific key to export.
    """

    def test_is_value_error_subclass(self) -> None:
        """Backward-compat: existing ``except ValueError`` still catches."""
        err = MissingApiKeyError("FOO_KEY", "missing")
        assert isinstance(err, ValueError)
        assert err.env_var == "FOO_KEY"
        assert str(err) == "missing"

    @pytest.mark.asyncio
    async def test_provider_prefix_missing_key_sets_env_var_attr(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Provider-prefix path raises MissingApiKeyError with env_var set."""
        _clear_all_provider_env(monkeypatch)

        with pytest.raises(MissingApiKeyError) as exc_info:
            await create_model_adapter("groq/llama-3.1-70b", db=None)

        assert exc_info.value.env_var == "GROQ_API_KEY"

    @pytest.mark.asyncio
    async def test_litellm_missing_base_sets_env_var_attr(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LiteLLM path with key but missing base URL names the base var."""
        _clear_all_provider_env(monkeypatch)
        monkeypatch.setenv(LITELLM_API_KEY_ENV_VAR, "litellm-key")
        from app.config import get_settings

        get_settings.cache_clear()
        settings = get_settings()
        monkeypatch.setattr(settings, "litellm_api_base", "", raising=False)

        with pytest.raises(MissingApiKeyError) as exc_info:
            await create_model_adapter("builtin/claude-opus-4.6", db=None)

        assert exc_info.value.env_var == LITELLM_API_BASE_ENV_VAR


@pytest.mark.unit
class TestReasoningEffortFlowThrough:
    """
    ``thinking_effort`` (the orchestrator's name for reasoning effort)
    must flow through kwargs to the underlying :class:`OpenAIAdapter`
    in the standalone path too, so benchmark harnesses can exercise
    high-effort reasoning modes without a database.
    """

    @pytest.mark.asyncio
    async def test_thinking_effort_kwarg_threads_through_standalone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_all_provider_env(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-thinking")

        adapter = await create_model_adapter(
            "anthropic/claude-opus-4-6",
            db=None,
            thinking_effort="high",
            temperature=0.0,
            max_tokens=2048,
        )

        assert adapter.thinking_effort == "high"
        assert adapter.temperature == 0.0
        assert adapter.max_tokens == 2048
