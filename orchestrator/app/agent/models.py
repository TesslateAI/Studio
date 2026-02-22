"""
Model Adapters

Adapters for different LLM providers that normalize their APIs to a common interface.
This allows the agent to work with ANY model without changing the core logic.

Supported:
- OpenAI API (GPT-4, GPT-3.5)
- OpenAI-compatible APIs (Cerebras, Groq, etc.)
- Anthropic API (Claude)
- Future: Ollama, HuggingFace, etc.
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Optional: Anthropic import (only needed if using Claude)
try:
    from anthropic import AsyncAnthropic

    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    AsyncAnthropic = None

logger = logging.getLogger(__name__)


# =============================================================================
# Built-in Provider Configurations
# =============================================================================
# Add new providers here to make them available for BYOK
# Each provider needs: name, base_url, api_type, and optionally default_headers

BUILTIN_PROVIDERS: dict[str, dict[str, Any]] = {
    "openrouter": {
        "name": "OpenRouter",
        "description": "Access to 200+ AI models through a unified API",
        "base_url": "https://openrouter.ai/api/v1",
        "api_type": "openai",
        "default_headers": {"HTTP-Referer": "https://tesslate.com", "X-Title": "Tesslate Studio"},
        "website": "https://openrouter.ai",
        "requires_key": True,
        "default_models": [
            "openai/gpt-5.2",
            "openai/gpt-5.2-codex",
            "openai/gpt-oss-120b",
            "anthropic/claude-sonnet-4.6",
            "anthropic/claude-opus-4.6",
            "deepseek/deepseek-r1",
            "deepseek/deepseek-v3.2",
            "qwen/qwen3-coder",
            "z-ai/glm-5",
            "moonshotai/kimi-k2.5",
            "minimax/minimax-m2.5",
        ],
    },
    "nano-gpt": {
        "name": "NanoGPT",
        "description": "Pay-per-prompt access to 200+ AI models",
        "base_url": "https://nano-gpt.com/api/v1",
        "api_type": "openai",
        "default_headers": {},
        "website": "https://nano-gpt.com",
        "requires_key": True,
        "default_models": [
            "openai/gpt-5.2",
            "openai/gpt-5.2-codex",
            "openai/gpt-oss-120b",
            "anthropic/claude-sonnet-4.6",
            "anthropic/claude-opus-4.6",
            "deepseek-r1",
            "deepseek/deepseek-v3.2",
            "qwen/qwen3-coder",
            "zai-org/glm-5",
            "moonshotai/kimi-k2.5",
            "minimax/minimax-m2.5",
        ],
    },
    "openai": {
        "name": "OpenAI",
        "description": "GPT-4, GPT-4o, GPT-3.5, and other OpenAI models",
        "base_url": "https://api.openai.com/v1",
        "api_type": "openai",
        "default_headers": {},
        "website": "https://platform.openai.com",
        "requires_key": True,
        "default_models": [
            "gpt-5.2",
            "gpt-5.2-codex",
            "gpt-5-mini",
            "gpt-4.1",
            "o3",
            "o4-mini",
        ],
    },
    "anthropic": {
        "name": "Anthropic",
        "description": "Claude Opus 4.6, Sonnet 4.6, and other Anthropic models",
        "base_url": "https://api.anthropic.com/v1",
        "api_type": "anthropic",
        "default_headers": {},
        "website": "https://console.anthropic.com",
        "requires_key": True,
        "default_models": [
            "claude-opus-4-6",
            "claude-opus-4-5",
            "claude-sonnet-4-6",
            "claude-haiku-4-5",
            "claude-sonnet-4-5",
        ],
    },
    "groq": {
        "name": "Groq",
        "description": "Ultra-fast inference with Llama, GPT-OSS, and more",
        "base_url": "https://api.groq.com/openai/v1",
        "api_type": "openai",
        "default_headers": {},
        "website": "https://console.groq.com",
        "requires_key": True,
        "default_models": [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "openai/gpt-oss-120b",
            "meta-llama/llama-4-scout-17b-16e-instruct",
        ],
    },
    "together": {
        "name": "Together AI",
        "description": "Open-source models with fast inference",
        "base_url": "https://api.together.xyz/v1",
        "api_type": "openai",
        "default_headers": {},
        "website": "https://api.together.xyz",
        "requires_key": True,
        "default_models": [
            "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8",
            "deepseek-ai/DeepSeek-R1",
            "deepseek-ai/DeepSeek-V3.1",
            "Qwen/Qwen3-235B-A22B-Instruct-2507-tput",
        ],
    },
    "deepseek": {
        "name": "DeepSeek",
        "description": "DeepSeek-V3.2 and other DeepSeek models",
        "base_url": "https://api.deepseek.com/v1",
        "api_type": "openai",
        "default_headers": {},
        "website": "https://platform.deepseek.com",
        "requires_key": True,
        "default_models": [
            "deepseek-reasoner",
            "deepseek-chat",
        ],
    },
    "fireworks": {
        "name": "Fireworks AI",
        "description": "Fast inference for open-source models",
        "base_url": "https://api.fireworks.ai/inference/v1",
        "api_type": "openai",
        "default_headers": {},
        "website": "https://fireworks.ai",
        "requires_key": True,
        "default_models": [
            "accounts/fireworks/models/deepseek-r1",
            "accounts/fireworks/models/deepseek-v3p1",
            "accounts/fireworks/models/qwen3-coder-480b-a35b-instruct",
            "accounts/fireworks/models/llama-v3p3-70b-instruct",
        ],
    },
}


def get_builtin_provider_config(provider_slug: str) -> dict[str, Any] | None:
    """Get configuration for a built-in provider."""
    return BUILTIN_PROVIDERS.get(provider_slug)


async def get_user_api_key(
    user_id: UUID, provider_slug: str, db: AsyncSession
) -> dict[str, str | None]:
    """
    Get user's API key and optional base URL override for a specific provider.

    Args:
        user_id: The user ID
        provider_slug: Provider identifier (e.g., "openrouter", "groq")
        db: Database session

    Returns:
        Dict with "key" (decrypted API key) and "base_url" (optional override)

    Raises:
        ValueError: If no API key configured for the provider
    """
    from ..models import UserAPIKey
    from ..routers.secrets import decode_key

    result = await db.execute(
        select(UserAPIKey).where(
            UserAPIKey.user_id == user_id,
            UserAPIKey.provider == provider_slug,
            UserAPIKey.is_active.is_(True),
        )
    )
    api_key_record = result.scalar_one_or_none()

    if not api_key_record:
        provider_name = BUILTIN_PROVIDERS.get(provider_slug, {}).get("name", provider_slug)
        raise ValueError(
            f"{provider_name} model selected but no API key configured. "
            f"Please add your {provider_name} API key in Library → API Keys."
        )

    return {
        "key": decode_key(api_key_record.encrypted_value),
        "base_url": api_key_record.base_url,
    }


async def get_llm_client(user_id: UUID, model_name: str, db: AsyncSession) -> AsyncOpenAI:
    """
    Get configured LLM client for a user and model.

    Routing logic based on model prefix:
    - "provider/model-name" → User's API key for that provider
    - No prefix → LiteLLM proxy (system models)

    Supported provider prefixes: openrouter, openai, anthropic, groq, together, deepseek, fireworks

    Args:
        user_id: The user ID
        model_name: The model identifier (e.g., "gpt-4o", "openrouter/anthropic/claude-3.5-sonnet")
        db: Database session

    Returns:
        Configured AsyncOpenAI client ready to use

    Raises:
        ValueError: If user not found, provider not found, or API key not configured
    """
    from ..config import get_settings
    from ..models import User, UserProvider

    settings = get_settings()

    # Get user
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError(f"User {user_id} not found")

    # Check if model has a provider prefix (e.g., "openrouter/model-name")
    if "/" in model_name:
        provider_slug = model_name.split("/")[0]

        # Try built-in provider first
        provider_config = get_builtin_provider_config(provider_slug)

        # If not built-in, check user's custom providers
        if not provider_config:
            result = await db.execute(
                select(UserProvider).where(
                    UserProvider.user_id == user_id,
                    UserProvider.slug == provider_slug,
                    UserProvider.is_active.is_(True),
                )
            )
            custom_provider = result.scalar_one_or_none()

            if custom_provider:
                provider_config = {
                    "name": custom_provider.name,
                    "base_url": custom_provider.base_url,
                    "api_type": custom_provider.api_type,
                    "default_headers": custom_provider.default_headers or {},
                }
            else:
                raise ValueError(
                    f"Unknown provider '{provider_slug}'. "
                    f"Available providers: {', '.join(BUILTIN_PROVIDERS.keys())}"
                )

        logger.info(f"Using {provider_config['name']} API for model: {model_name}")

        # Get user's API key and optional base URL override for this provider
        user_key_data = await get_user_api_key(user_id, provider_slug, db)
        effective_base_url = user_key_data["base_url"] or provider_config["base_url"]

        # Return client configured for the provider
        return AsyncOpenAI(
            api_key=user_key_data["key"],
            base_url=effective_base_url,
            default_headers=provider_config.get("default_headers", {}),
        )
    else:
        # No prefix — use LiteLLM proxy for system models
        logger.info(f"Using LiteLLM proxy for model: {model_name}")

        if not user.litellm_api_key:
            raise ValueError("User does not have a LiteLLM API key. Please contact support.")

        return AsyncOpenAI(api_key=user.litellm_api_key, base_url=settings.litellm_api_base)


class ModelAdapter(ABC):
    """
    Abstract base class for model adapters.

    All adapters must implement the chat() method which streams the model's text response.
    """

    @abstractmethod
    async def chat(self, messages: list[dict[str, str]], **kwargs) -> AsyncGenerator[str, None]:
        """
        Send messages to the model and stream text response chunks.

        Args:
            messages: List of message dicts with "role" and "content"
            **kwargs: Model-specific parameters (temperature, max_tokens, etc.)

        Yields:
            Text chunks as they're generated by the model
        """
        pass

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        tool_choice: str = "auto",
    ) -> AsyncGenerator[dict, None]:
        """
        Stream chat completion with native function calling support.

        This method uses the OpenAI tools API for structured tool calling,
        unlike chat() which only streams text. Used by TesslateAgent for
        reliable tool call parsing.

        Args:
            messages: List of message dicts (supports role: system/user/assistant/tool)
            tools: List of tool definitions in OpenAI format
            tool_choice: "auto", "none", or {"type": "function", "function": {"name": "..."}}

        Yields:
            Dicts with types:
            - {"type": "text_delta", "content": "..."}     - Text being generated
            - {"type": "tool_calls_complete", "tool_calls": [...]} - Accumulated tool calls
            - {"type": "done", "finish_reason": "...", "usage": {...}} - Stream complete
        """
        # Default implementation raises NotImplementedError
        # Subclasses should override this
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support chat_with_tools(). "
            f"Use an adapter that supports native function calling (e.g., OpenAIAdapter)."
        )
        yield {}  # Make it a generator

    @abstractmethod
    def get_model_name(self) -> str:
        """Get the model name/identifier."""
        pass


class OpenAIAdapter(ModelAdapter):
    """
    Adapter for OpenAI models (GPT-4, GPT-3.5-turbo, etc.)
    Also works with OpenAI-compatible APIs like Cerebras, Groq, Together AI, etc.
    """

    def __init__(
        self,
        model_name: str,
        client: AsyncOpenAI,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ):
        """
        Initialize OpenAI adapter with a pre-configured client.

        Args:
            model_name: Model identifier (e.g., "gpt-4o", "openrouter/anthropic/claude-3.5-sonnet")
            client: Pre-configured AsyncOpenAI client (from get_llm_client())
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum tokens in response
        """
        self.model_name = model_name
        self.client = client
        self.temperature = temperature
        self.max_tokens = max_tokens

        logger.info(f"OpenAIAdapter initialized - model: {model_name}")

    async def chat(self, messages: list[dict[str, str]], **kwargs) -> AsyncGenerator[str, None]:
        """
        Send messages to OpenAI API and stream response chunks.

        Args:
            messages: List of message dicts
            **kwargs: Override temperature, max_tokens, etc.

        Yields:
            Text chunks as they're generated by the model
        """
        _ = kwargs.get("temperature", self.temperature)  # Reserved for future use
        max_tokens = kwargs.get("max_tokens", self.max_tokens)

        request_params = {
            "model": self.model_name,
            "messages": messages,
            "stream": True,  # Enable streaming
        }

        if max_tokens:
            request_params["max_tokens"] = max_tokens

        try:
            logger.debug(
                f"Sending streaming request to {self.model_name} with {len(messages)} messages"
            )

            # Create streaming completion
            stream = await self.client.chat.completions.create(**request_params)

            # Stream chunks as they arrive
            async for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        yield delta.content

            logger.debug(f"Streaming complete for {self.model_name}")

        except Exception as e:
            logger.error(f"OpenAI API streaming error: {e}", exc_info=True)
            raise RuntimeError(f"Model API error: {str(e)}") from e

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        tool_choice: str = "auto",
    ) -> AsyncGenerator[dict, None]:
        """
        Stream chat completion with native OpenAI function calling.

        Accumulates tool call deltas from the stream and yields structured events.
        Follows the exact message format required by the OpenAI API.
        """
        request_params = {
            "model": self.model_name,
            "messages": messages,
            "tools": tools,
            "tool_choice": tool_choice,
            "stream": True,
        }

        if self.max_tokens:
            request_params["max_tokens"] = self.max_tokens

        # Enable parallel tool calls if supported
        request_params["parallel_tool_calls"] = True

        try:
            logger.debug(
                f"chat_with_tools: {self.model_name}, {len(messages)} messages, {len(tools)} tools"
            )

            stream = await self.client.chat.completions.create(**request_params)

            # Accumulate tool calls indexed by position
            tool_calls_data: dict[int, dict] = {}
            content_text = ""
            finish_reason = None
            usage_data = None

            async for chunk in stream:
                if not chunk.choices:
                    # Check for usage in final chunk
                    if hasattr(chunk, "usage") and chunk.usage:
                        usage_data = {
                            "prompt_tokens": getattr(chunk.usage, "prompt_tokens", 0),
                            "completion_tokens": getattr(chunk.usage, "completion_tokens", 0),
                        }
                    continue

                choice = chunk.choices[0]
                delta = choice.delta

                # Track finish reason
                if choice.finish_reason:
                    finish_reason = choice.finish_reason

                # Accumulate text content
                if delta.content:
                    content_text += delta.content
                    yield {"type": "text_delta", "content": delta.content}

                # Accumulate tool calls
                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index

                        if idx not in tool_calls_data:
                            tool_calls_data[idx] = {
                                "id": "",
                                "function": {"name": "", "arguments": ""},
                            }

                        if tc_delta.id:
                            tool_calls_data[idx]["id"] = tc_delta.id

                        if tc_delta.function:
                            if tc_delta.function.name:
                                tool_calls_data[idx]["function"]["name"] = tc_delta.function.name
                            if tc_delta.function.arguments:
                                tool_calls_data[idx]["function"]["arguments"] += (
                                    tc_delta.function.arguments
                                )

            # Yield accumulated tool calls if any
            if tool_calls_data:
                # Sort by index and convert to list
                sorted_calls = [tool_calls_data[idx] for idx in sorted(tool_calls_data.keys())]
                yield {"type": "tool_calls_complete", "tool_calls": sorted_calls}

            # Yield done event
            yield {
                "type": "done",
                "finish_reason": finish_reason or ("tool_calls" if tool_calls_data else "stop"),
                "usage": usage_data,
            }

            logger.debug(
                f"chat_with_tools complete: "
                f"{len(content_text)} chars text, "
                f"{len(tool_calls_data)} tool calls"
            )

        except Exception as e:
            logger.error(f"chat_with_tools error: {e}", exc_info=True)
            raise RuntimeError(f"Model API error: {str(e)}") from e

    def get_model_name(self) -> str:
        return self.model_name


class AnthropicAdapter(ModelAdapter):
    """
    Adapter for Anthropic's Claude models.
    """

    def __init__(
        self, model_name: str, api_key: str, temperature: float = 0.7, max_tokens: int = 4096
    ):
        """
        Initialize Anthropic adapter.

        Args:
            model_name: Model identifier (e.g., "claude-3-5-sonnet-20241022")
            api_key: Anthropic API key
            temperature: Sampling temperature (0-1)
            max_tokens: Maximum tokens in response
        """
        if not ANTHROPIC_AVAILABLE:
            raise ImportError(
                "Anthropic library not installed. Install with: pip install anthropic"
            )

        self.model_name = model_name
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.client = AsyncAnthropic(api_key=api_key)

        logger.info(f"AnthropicAdapter initialized - model: {model_name}")

    async def chat(self, messages: list[dict[str, str]], **kwargs) -> AsyncGenerator[str, None]:
        """
        Send messages to Anthropic API and stream response chunks.

        Note: Anthropic requires system message to be separate from messages list.

        Args:
            messages: List of message dicts
            **kwargs: Override temperature, max_tokens, etc.

        Yields:
            Text chunks as they're generated by the model
        """
        _ = kwargs.get("temperature", self.temperature)  # Reserved for future use
        max_tokens = kwargs.get("max_tokens", self.max_tokens)

        # Anthropic requires system message to be separate
        system_message = None
        conversation_messages = []

        for msg in messages:
            if msg["role"] == "system":
                system_message = msg["content"]
            else:
                conversation_messages.append({"role": msg["role"], "content": msg["content"]})

        try:
            logger.debug(
                f"Sending streaming request to {self.model_name} with {len(conversation_messages)} messages"
            )

            request_params = {
                "model": self.model_name,
                "messages": conversation_messages,
                "temperature": self.temperature,
                "max_tokens": max_tokens,
                "stream": True,  # Enable streaming
            }

            if system_message:
                request_params["system"] = system_message

            # Stream response chunks
            async with self.client.messages.stream(**request_params) as stream:
                async for text in stream.text_stream:
                    yield text

            logger.debug(f"Streaming complete for {self.model_name}")

        except Exception as e:
            logger.error(f"Anthropic API streaming error: {e}", exc_info=True)
            raise RuntimeError(f"Model API error: {str(e)}") from e

    def get_model_name(self) -> str:
        return self.model_name


async def create_model_adapter(
    model_name: str, user_id: UUID, db: AsyncSession, provider: str | None = None, **kwargs
) -> ModelAdapter:
    """
    Factory function to create the appropriate model adapter.

    Uses get_llm_client() to handle model routing (OpenRouter vs LiteLLM).
    Auto-detects provider from model name if not specified.

    Args:
        model_name: Model identifier (e.g., "gpt-4o", "openrouter/anthropic/claude-3.5-sonnet")
        user_id: User ID for fetching API keys
        db: Database session
        provider: Force specific provider ("openai", "anthropic", etc.)
        **kwargs: Additional adapter parameters (temperature, max_tokens, etc.)

    Returns:
        ModelAdapter instance

    Examples:
        # OpenAI GPT-4 (via LiteLLM)
        adapter = await create_model_adapter("gpt-4o", user_id=1, db=db)

        # OpenRouter model (uses user's OpenRouter key)
        adapter = await create_model_adapter("openrouter/anthropic/claude-3.5-sonnet", user_id=1, db=db)

        # Cerebras via LiteLLM
        adapter = await create_model_adapter("cerebras/llama3.1-8b", user_id=1, db=db)
    """
    # Auto-detect provider if not specified
    # anthropic/ prefix → native Anthropic adapter (BYOK); all others → OpenAI-compatible API
    if not provider:
        provider = "anthropic" if model_name.startswith("anthropic/") else "openai"

    if provider == "anthropic":
        # Native Anthropic API (not implemented for async client fetching yet)
        # For now, this would require direct API key - not commonly used
        raise NotImplementedError(
            "Native Anthropic adapter not yet updated for centralized routing"
        )
    elif provider == "openai":
        # Get configured client using centralized routing
        client = await get_llm_client(user_id, model_name, db)

        # Strip provider slug prefix from model name before passing to adapter
        # e.g. "openai/gpt-5.2" → "gpt-5.2", "asdf/zai-org/glm-5" → "zai-org/glm-5"
        api_model_name = model_name
        if "/" in model_name:
            api_model_name = model_name.split("/", 1)[1]

        # Create adapter with the configured client
        return OpenAIAdapter(model_name=api_model_name, client=client, **kwargs)
    else:
        raise ValueError(f"Unsupported provider: {provider}")
