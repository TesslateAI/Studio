"""
Unit tests for Model Adapters.

Tests OpenAI adapter, model adapter interface, and client creation.
"""

import pytest
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from app.agent.models import (
    ModelAdapter,
    OpenAIAdapter,
    AnthropicAdapter,
    create_model_adapter,
    ANTHROPIC_AVAILABLE
)


@pytest.mark.unit
class TestModelAdapter:
    """Test suite for ModelAdapter abstract base class."""

    def test_model_adapter_is_abstract(self):
        """Test that ModelAdapter cannot be instantiated directly."""
        with pytest.raises(TypeError) as exc_info:
            ModelAdapter()

        assert "Can't instantiate abstract class" in str(exc_info.value)

    def test_concrete_adapter_must_implement_chat(self):
        """Test that concrete adapters must implement chat method."""
        class IncompleteAdapter(ModelAdapter):
            def get_model_name(self):
                return "test"

        with pytest.raises(TypeError) as exc_info:
            IncompleteAdapter()

        assert "Can't instantiate abstract class" in str(exc_info.value)

    def test_concrete_adapter_can_be_instantiated(self):
        """Test that fully implemented adapter can be instantiated."""
        class CompleteAdapter(ModelAdapter):
            async def chat(self, messages, **kwargs):
                yield "test"

            def get_model_name(self):
                return "test-model"

        adapter = CompleteAdapter()
        assert adapter.get_model_name() == "test-model"


@pytest.mark.unit
class TestOpenAIAdapter:
    """Test suite for OpenAIAdapter."""

    @pytest.fixture
    def mock_openai_client(self):
        """Create a mock AsyncOpenAI client."""
        client = AsyncMock()
        return client

    def test_openai_adapter_initialization(self, mock_openai_client):
        """Test OpenAI adapter initialization."""
        adapter = OpenAIAdapter(
            model_name="gpt-4o",
            client=mock_openai_client,
            temperature=0.8,
            max_tokens=2000
        )

        assert adapter.model_name == "gpt-4o"
        assert adapter.client is mock_openai_client
        assert adapter.temperature == 0.8
        assert adapter.max_tokens == 2000
        assert adapter.is_openrouter is False

    def test_openai_adapter_detects_openrouter_models(self, mock_openai_client):
        """Test that adapter detects OpenRouter models."""
        adapter = OpenAIAdapter(
            model_name="openrouter/anthropic/claude-3.5-sonnet",
            client=mock_openai_client
        )

        assert adapter.is_openrouter is True

    def test_openai_adapter_get_model_name(self, mock_openai_client):
        """Test getting model name from adapter."""
        adapter = OpenAIAdapter(
            model_name="gpt-4o-mini",
            client=mock_openai_client
        )

        assert adapter.get_model_name() == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_openai_adapter_chat_streaming(self, mock_openai_client):
        """Test OpenAI adapter streaming chat."""
        mock_response = AsyncMock()
        mock_chunk1 = Mock()
        mock_chunk1.choices = [Mock(delta=Mock(content="Hello"))]
        mock_chunk2 = Mock()
        mock_chunk2.choices = [Mock(delta=Mock(content=" World"))]

        async def mock_stream():
            yield mock_chunk1
            yield mock_chunk2

        mock_response.__aiter__ = lambda self: mock_stream()
        mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_response)

        adapter = OpenAIAdapter(
            model_name="gpt-4o",
            client=mock_openai_client
        )

        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"}
        ]

        chunks = []
        async for chunk in adapter.chat(messages):
            chunks.append(chunk)

        assert chunks == ["Hello", " World"]
        mock_openai_client.chat.completions.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_openai_adapter_strips_openrouter_prefix(self, mock_openai_client):
        """Test that OpenRouter prefix is stripped from model name in API call."""
        mock_response = AsyncMock()
        mock_chunk = Mock()
        mock_chunk.choices = [Mock(delta=Mock(content="test"))]

        async def mock_stream():
            yield mock_chunk

        mock_response.__aiter__ = lambda self: mock_stream()
        mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_response)

        adapter = OpenAIAdapter(
            model_name="openrouter/anthropic/claude-3.5-sonnet",
            client=mock_openai_client
        )

        messages = [{"role": "user", "content": "test"}]

        async for _ in adapter.chat(messages):
            pass

        call_args = mock_openai_client.chat.completions.create.call_args
        assert call_args.kwargs["model"] == "anthropic/claude-3.5-sonnet"

    @pytest.mark.asyncio
    async def test_openai_adapter_adds_openrouter_headers(self, mock_openai_client):
        """Test that OpenRouter requests include extra headers."""
        mock_response = AsyncMock()
        mock_chunk = Mock()
        mock_chunk.choices = [Mock(delta=Mock(content="test"))]

        async def mock_stream():
            yield mock_chunk

        mock_response.__aiter__ = lambda self: mock_stream()
        mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_response)

        adapter = OpenAIAdapter(
            model_name="openrouter/openai/gpt-4",
            client=mock_openai_client
        )

        messages = [{"role": "user", "content": "test"}]

        async for _ in adapter.chat(messages):
            pass

        call_args = mock_openai_client.chat.completions.create.call_args
        assert "extra_headers" in call_args.kwargs
        assert "HTTP-Referer" in call_args.kwargs["extra_headers"]
        assert "X-Title" in call_args.kwargs["extra_headers"]

    @pytest.mark.asyncio
    async def test_openai_adapter_handles_empty_delta(self, mock_openai_client):
        """Test that adapter handles chunks with empty delta content."""
        mock_response = AsyncMock()
        mock_chunk1 = Mock()
        mock_chunk1.choices = [Mock(delta=Mock(content=None))]
        mock_chunk2 = Mock()
        mock_chunk2.choices = [Mock(delta=Mock(content="Hello"))]

        async def mock_stream():
            yield mock_chunk1
            yield mock_chunk2

        mock_response.__aiter__ = lambda self: mock_stream()
        mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_response)

        adapter = OpenAIAdapter(
            model_name="gpt-4o",
            client=mock_openai_client
        )

        chunks = []
        async for chunk in adapter.chat([{"role": "user", "content": "test"}]):
            chunks.append(chunk)

        assert chunks == ["Hello"]

    @pytest.mark.asyncio
    async def test_openai_adapter_error_handling(self, mock_openai_client):
        """Test that adapter handles API errors gracefully."""
        mock_openai_client.chat.completions.create = AsyncMock(
            side_effect=Exception("API Error")
        )

        adapter = OpenAIAdapter(
            model_name="gpt-4o",
            client=mock_openai_client
        )

        with pytest.raises(RuntimeError) as exc_info:
            async for _ in adapter.chat([{"role": "user", "content": "test"}]):
                pass

        assert "Model API error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_openai_adapter_custom_parameters(self, mock_openai_client):
        """Test that custom parameters are passed correctly."""
        mock_response = AsyncMock()
        mock_chunk = Mock()
        mock_chunk.choices = [Mock(delta=Mock(content="test"))]

        async def mock_stream():
            yield mock_chunk

        mock_response.__aiter__ = lambda self: mock_stream()
        mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_response)

        adapter = OpenAIAdapter(
            model_name="gpt-4o",
            client=mock_openai_client,
            temperature=0.5,
            max_tokens=1000
        )

        messages = [{"role": "user", "content": "test"}]

        async for _ in adapter.chat(messages, temperature=0.9, max_tokens=2000):
            pass

        call_args = mock_openai_client.chat.completions.create.call_args
        assert call_args.kwargs["max_tokens"] == 2000


@pytest.mark.unit
@pytest.mark.skipif(not ANTHROPIC_AVAILABLE, reason="Anthropic library not installed")
class TestAnthropicAdapter:
    """Test suite for AnthropicAdapter."""

    def test_anthropic_adapter_initialization(self):
        """Test Anthropic adapter initialization."""
        with patch('app.agent.models.AsyncAnthropic'):
            adapter = AnthropicAdapter(
                model_name="claude-3-5-sonnet-20241022",
                api_key="test-key",
                temperature=0.8,
                max_tokens=2000
            )

            assert adapter.model_name == "claude-3-5-sonnet-20241022"
            assert adapter.temperature == 0.8
            assert adapter.max_tokens == 2000

    def test_anthropic_adapter_get_model_name(self):
        """Test getting model name from Anthropic adapter."""
        with patch('app.agent.models.AsyncAnthropic'):
            adapter = AnthropicAdapter(
                model_name="claude-3-opus-20240229",
                api_key="test-key"
            )

            assert adapter.get_model_name() == "claude-3-opus-20240229"


@pytest.mark.unit
class TestCreateModelAdapter:
    """Test suite for create_model_adapter factory function."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        return AsyncMock()

    @pytest.fixture
    def mock_user_id(self):
        """Create mock user ID."""
        from uuid import uuid4
        return uuid4()

    @pytest.mark.asyncio
    async def test_create_adapter_for_openai_model(self, mock_user_id, mock_db):
        """Test creating adapter for OpenAI model."""
        with patch('app.agent.models.get_llm_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_get_client.return_value = mock_client

            adapter = await create_model_adapter(
                model_name="gpt-4o",
                user_id=mock_user_id,
                db=mock_db
            )

            assert isinstance(adapter, OpenAIAdapter)
            assert adapter.model_name == "gpt-4o"
            mock_get_client.assert_called_once_with(mock_user_id, "gpt-4o", mock_db)

    @pytest.mark.asyncio
    async def test_create_adapter_for_openrouter_model(self, mock_user_id, mock_db):
        """Test creating adapter for OpenRouter model."""
        with patch('app.agent.models.get_llm_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_get_client.return_value = mock_client

            adapter = await create_model_adapter(
                model_name="openrouter/anthropic/claude-3.5-sonnet",
                user_id=mock_user_id,
                db=mock_db
            )

            assert isinstance(adapter, OpenAIAdapter)
            assert adapter.model_name == "openrouter/anthropic/claude-3.5-sonnet"
            assert adapter.is_openrouter is True

    @pytest.mark.asyncio
    async def test_create_adapter_with_custom_params(self, mock_user_id, mock_db):
        """Test creating adapter with custom parameters."""
        with patch('app.agent.models.get_llm_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_get_client.return_value = mock_client

            adapter = await create_model_adapter(
                model_name="gpt-4o",
                user_id=mock_user_id,
                db=mock_db,
                temperature=0.9,
                max_tokens=3000
            )

            assert adapter.temperature == 0.9
            assert adapter.max_tokens == 3000

    @pytest.mark.asyncio
    async def test_create_adapter_anthropic_provider_not_implemented(self, mock_user_id, mock_db):
        """Test that native Anthropic provider raises NotImplementedError."""
        with pytest.raises(NotImplementedError) as exc_info:
            await create_model_adapter(
                model_name="claude-3-opus",
                user_id=mock_user_id,
                db=mock_db,
                provider="anthropic"
            )

        assert "Native Anthropic adapter not yet updated" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_create_adapter_unsupported_provider(self, mock_user_id, mock_db):
        """Test that unsupported provider raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            await create_model_adapter(
                model_name="some-model",
                user_id=mock_user_id,
                db=mock_db,
                provider="unsupported"
            )

        assert "Unsupported provider" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_create_adapter_auto_detects_provider(self, mock_user_id, mock_db):
        """Test that provider is auto-detected from model name."""
        with patch('app.agent.models.get_llm_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_get_client.return_value = mock_client

            # OpenAI model
            adapter1 = await create_model_adapter(
                model_name="gpt-4o",
                user_id=mock_user_id,
                db=mock_db
            )
            assert isinstance(adapter1, OpenAIAdapter)

            # OpenRouter Claude (should use OpenAI-compatible API)
            adapter2 = await create_model_adapter(
                model_name="openrouter/anthropic/claude-3.5-sonnet",
                user_id=mock_user_id,
                db=mock_db
            )
            assert isinstance(adapter2, OpenAIAdapter)
