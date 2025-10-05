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

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import logging
from openai import AsyncOpenAI

# Optional: Anthropic import (only needed if using Claude)
try:
    from anthropic import AsyncAnthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    AsyncAnthropic = None

logger = logging.getLogger(__name__)


class ModelAdapter(ABC):
    """
    Abstract base class for model adapters.

    All adapters must implement the chat() method which returns the model's text response.
    """

    @abstractmethod
    async def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """
        Send messages to the model and get a text response.

        Args:
            messages: List of message dicts with "role" and "content"
            **kwargs: Model-specific parameters (temperature, max_tokens, etc.)

        Returns:
            The model's response as a string
        """
        pass

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
        api_key: str,
        api_base: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ):
        """
        Initialize OpenAI adapter.

        Args:
            model_name: Model identifier (e.g., "gpt-4o", "cerebras/llama3.1-8b")
            api_key: API key
            api_base: Custom API base URL (for OpenAI-compatible APIs)
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum tokens in response
        """
        self.model_name = model_name
        self.temperature = temperature
        self.max_tokens = max_tokens

        client_kwargs = {"api_key": api_key}
        if api_base:
            client_kwargs["base_url"] = api_base

        self.client = AsyncOpenAI(**client_kwargs)
        logger.info(f"OpenAIAdapter initialized - model: {model_name}, base: {api_base or 'default'}")

    async def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """
        Send messages to OpenAI API and get response.

        Args:
            messages: List of message dicts
            **kwargs: Override temperature, max_tokens, etc.

        Returns:
            Model response text
        """
        temperature = kwargs.get("temperature", self.temperature)
        max_tokens = kwargs.get("max_tokens", self.max_tokens)

        request_params = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature
        }

        if max_tokens:
            request_params["max_tokens"] = max_tokens

        try:
            logger.debug(f"Sending request to {self.model_name} with {len(messages)} messages")

            response = await self.client.chat.completions.create(**request_params)

            content = response.choices[0].message.content or ""
            logger.debug(f"Received response: {len(content)} characters")

            return content

        except Exception as e:
            logger.error(f"OpenAI API error: {e}", exc_info=True)
            raise RuntimeError(f"Model API error: {str(e)}") from e

    def get_model_name(self) -> str:
        return self.model_name


class AnthropicAdapter(ModelAdapter):
    """
    Adapter for Anthropic's Claude models.
    """

    def __init__(
        self,
        model_name: str,
        api_key: str,
        temperature: float = 0.7,
        max_tokens: int = 4096
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

    async def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """
        Send messages to Anthropic API and get response.

        Note: Anthropic requires system message to be separate from messages list.

        Args:
            messages: List of message dicts
            **kwargs: Override temperature, max_tokens, etc.

        Returns:
            Model response text
        """
        temperature = kwargs.get("temperature", self.temperature)
        max_tokens = kwargs.get("max_tokens", self.max_tokens)

        # Anthropic requires system message to be separate
        system_message = None
        conversation_messages = []

        for msg in messages:
            if msg["role"] == "system":
                system_message = msg["content"]
            else:
                conversation_messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })

        try:
            logger.debug(f"Sending request to {self.model_name} with {len(conversation_messages)} messages")

            request_params = {
                "model": self.model_name,
                "messages": conversation_messages,
                "temperature": temperature,
                "max_tokens": max_tokens
            }

            if system_message:
                request_params["system"] = system_message

            response = await self.client.messages.create(**request_params)

            content = response.content[0].text if response.content else ""
            logger.debug(f"Received response: {len(content)} characters")

            return content

        except Exception as e:
            logger.error(f"Anthropic API error: {e}", exc_info=True)
            raise RuntimeError(f"Model API error: {str(e)}") from e

    def get_model_name(self) -> str:
        return self.model_name


def create_model_adapter(
    model_name: str,
    api_key: str,
    api_base: Optional[str] = None,
    provider: Optional[str] = None,
    **kwargs
) -> ModelAdapter:
    """
    Factory function to create the appropriate model adapter.

    Auto-detects provider from model name if not specified.

    Args:
        model_name: Model identifier
        api_key: API key
        api_base: Custom API base URL
        provider: Force specific provider ("openai", "anthropic", etc.)
        **kwargs: Additional adapter parameters

    Returns:
        ModelAdapter instance

    Examples:
        # OpenAI GPT-4
        adapter = create_model_adapter("gpt-4o", api_key="sk-...")

        # Cerebras via OpenAI-compatible API
        adapter = create_model_adapter(
            "cerebras/llama3.1-8b",
            api_key="csk-...",
            api_base="https://api.cerebras.ai/v1"
        )

        # Claude
        adapter = create_model_adapter(
            "claude-3-5-sonnet-20241022",
            api_key="sk-ant-...",
            provider="anthropic"
        )
    """
    model_lower = model_name.lower()

    # Auto-detect provider if not specified
    if not provider:
        if "claude" in model_lower or "anthropic" in model_lower:
            provider = "anthropic"
        else:
            # Default to OpenAI-compatible
            provider = "openai"

    if provider == "anthropic":
        return AnthropicAdapter(model_name, api_key, **kwargs)
    elif provider == "openai":
        return OpenAIAdapter(model_name, api_key, api_base, **kwargs)
    else:
        raise ValueError(f"Unsupported provider: {provider}")


def get_model_adapter_from_settings(settings) -> ModelAdapter:
    """
    Create a model adapter from application settings.

    Args:
        settings: Settings object with openai_model, openai_api_key, openai_api_base

    Returns:
        ModelAdapter instance
    """
    return create_model_adapter(
        model_name=settings.openai_model,
        api_key=settings.openai_api_key,
        api_base=settings.openai_api_base if settings.openai_api_base != "https://api.openai.com/v1" else None
    )
