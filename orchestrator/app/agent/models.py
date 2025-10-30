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
from uuid import UUID
import logging
import asyncio
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

# Optional: Anthropic import (only needed if using Claude)
try:
    from anthropic import AsyncAnthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    AsyncAnthropic = None

logger = logging.getLogger(__name__)


async def get_llm_client(
    user_id: UUID,
    model_name: str,
    db: AsyncSession
) -> AsyncOpenAI:
    """
    Get configured LLM client for a user and model.

    This is the centralized routing function that handles:
    - OpenRouter models: Routes to OpenRouter API with user's stored key
    - Ollama models: Routes to local Ollama server
    - LM Studio models: Routes to local LM Studio server
    - llama.cpp models: Routes to local llama.cpp server
    - Custom models: Routes to user-configured OpenAI-compatible endpoint
    - Other models: Routes to LiteLLM proxy with user's LiteLLM key

    Args:
        user_id: The user ID
        model_name: The model identifier (e.g., "gpt-5o", "openrouter/model", "ollama/llama2")
        db: Database session

    Returns:
        Configured AsyncOpenAI client ready to use

    Raises:
        ValueError: If user not found or provider configuration not found
    """
    from ..models import User, UserAPIKey
    from ..config import get_settings
    from ..routers.secrets import decode_key

    settings = get_settings()

    # Get user
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError(f"User {user_id} not found")

    # Helper function to get provider config
    async def get_provider_config(provider: str):
        result = await db.execute(
            select(UserAPIKey).where(
                UserAPIKey.user_id == user_id,
                UserAPIKey.provider == provider,
                UserAPIKey.is_active == True
            )
        )
        return result.scalar_one_or_none()

    # Check if this is an OpenRouter model
    if model_name.startswith("openrouter/"):
        logger.info(f"OpenRouter model detected: {model_name}")
        api_key_record = await get_provider_config("openrouter")

        if not api_key_record:
            raise ValueError(
                "OpenRouter model selected but no OpenRouter API key configured. "
                "Please add your OpenRouter API key in Library > API Keys."
            )

        openrouter_key = decode_key(api_key_record.encrypted_value)
        base_url = api_key_record.provider_metadata.get("base_url", "https://openrouter.ai/api/v1")

        logger.info(f"Using OpenRouter API at {base_url}")
        return AsyncOpenAI(api_key=openrouter_key, base_url=base_url)

    # Check if this is an Ollama model
    elif model_name.startswith("ollama/"):
        logger.info(f"Ollama model detected: {model_name}")
        api_key_record = await get_provider_config("ollama")

        if not api_key_record:
            raise ValueError(
                "Ollama model selected but Ollama is not configured. "
                "Please configure Ollama in Library > Model Management."
            )

        base_url = api_key_record.provider_metadata.get("base_url", "http://localhost:11434")
        logger.info(f"Using Ollama API at {base_url}")

        return AsyncOpenAI(
            api_key="ollama",  # Ollama doesn't require real API key
            base_url=f"{base_url}/v1"
        )

    # Check if this is an LM Studio model
    elif model_name.startswith("lmstudio/"):
        logger.info(f"LM Studio model detected: {model_name}")
        api_key_record = await get_provider_config("lmstudio")

        if not api_key_record:
            raise ValueError(
                "LM Studio model selected but LM Studio is not configured. "
                "Please configure LM Studio in Library > Model Management."
            )

        base_url = api_key_record.provider_metadata.get("base_url", "http://localhost:1234")
        logger.info(f"Using LM Studio API at {base_url}")

        return AsyncOpenAI(
            api_key="lmstudio",  # LM Studio doesn't require real API key
            base_url=base_url
        )

    # Check if this is a llama.cpp model
    elif model_name.startswith("llamacpp/"):
        logger.info(f"llama.cpp model detected: {model_name}")
        api_key_record = await get_provider_config("llamacpp")

        if not api_key_record:
            raise ValueError(
                "llama.cpp model selected but llama.cpp is not configured. "
                "Please configure llama.cpp in Library > Model Management."
            )

        base_url = api_key_record.provider_metadata.get("base_url", "http://localhost:8080")
        logger.info(f"Using llama.cpp API at {base_url}")

        return AsyncOpenAI(
            api_key="llamacpp",  # llama.cpp doesn't require real API key
            base_url=base_url
        )

    # Check if this is a custom endpoint model
    elif model_name.startswith("custom/"):
        logger.info(f"Custom endpoint model detected: {model_name}")
        api_key_record = await get_provider_config("custom")

        if not api_key_record:
            raise ValueError(
                "Custom endpoint model selected but custom endpoint is not configured. "
                "Please configure a custom endpoint in Library > Model Management."
            )

        base_url = api_key_record.provider_metadata.get("base_url")
        if not base_url:
            raise ValueError("Custom endpoint configured but no base URL found.")

        api_key = decode_key(api_key_record.encrypted_value)
        logger.info(f"Using custom endpoint at {base_url}")

        return AsyncOpenAI(api_key=api_key, base_url=base_url)

    else:
        # Use LiteLLM proxy for system models
        logger.info(f"Using LiteLLM proxy for model: {model_name}")

        if not user.litellm_api_key:
            raise ValueError("User does not have a LiteLLM API key. Please contact support.")

        return AsyncOpenAI(
            api_key=user.litellm_api_key,
            base_url=settings.litellm_api_base
        )


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
        client: AsyncOpenAI,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ):
        """
        Initialize OpenAI adapter with a pre-configured client.

        Args:
            model_name: Model identifier (e.g., "gpt-5o", "openrouter/anthropic/claude-3.5-sonnet")
            client: Pre-configured AsyncOpenAI client (from get_llm_client())
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum tokens in response
        """
        self.model_name = model_name
        self.client = client
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.is_openrouter = model_name.startswith("openrouter/")

        logger.info(f"OpenAIAdapter initialized - model: {model_name}")

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

        # Strip openrouter/ prefix if present (OpenRouter API expects just the model ID)
        model_id = self.model_name.removeprefix("openrouter/") if self.is_openrouter else self.model_name

        request_params = {
            "model": model_id,
            "messages": messages
        }

        if max_tokens:
            request_params["max_tokens"] = max_tokens

        # Add OpenRouter-specific parameters
        if self.is_openrouter:
            # Add extra_headers for OpenRouter rankings and referrals
            request_params["extra_headers"] = {
                "HTTP-Referer": "https://tesslate.com",  # Your app URL
                "X-Title": "Tesslate Studio"  # Your app name
            }

        try:
            logger.debug(f"Sending request to {self.model_name} with {len(messages)} messages")

            # Add 60 second timeout to prevent hanging
            response = await asyncio.wait_for(
                self.client.chat.completions.create(**request_params),
                timeout=60.0
            )

            content = response.choices[0].message.content or ""
            logger.debug(f"Received response: {len(content)} characters")

            return content

        except asyncio.TimeoutError:
            logger.error(f"Model API timeout after 60 seconds - model: {self.model_name}")
            raise RuntimeError(f"Model API timeout: {self.model_name} did not respond within 60 seconds. Please check your API endpoint configuration.")
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


async def create_model_adapter(
    model_name: str,
    user_id: UUID,
    db: AsyncSession,
    provider: Optional[str] = None,
    **kwargs
) -> ModelAdapter:
    """
    Factory function to create the appropriate model adapter.

    Uses get_llm_client() to handle model routing (OpenRouter vs LiteLLM).
    Auto-detects provider from model name if not specified.

    Args:
        model_name: Model identifier (e.g., "gpt-5o", "openrouter/anthropic/claude-3.5-sonnet")
        user_id: User ID for fetching API keys
        db: Database session
        provider: Force specific provider ("openai", "anthropic", etc.)
        **kwargs: Additional adapter parameters (temperature, max_tokens, etc.)

    Returns:
        ModelAdapter instance

    Examples:
        # OpenAI GPT-4 (via LiteLLM)
        adapter = await create_model_adapter("gpt-5o", user_id=1, db=db)

        # OpenRouter model (uses user's OpenRouter key)
        adapter = await create_model_adapter("openrouter/anthropic/claude-3.5-sonnet", user_id=1, db=db)

        # Cerebras via LiteLLM
        adapter = await create_model_adapter("cerebras/llama3.1-8b", user_id=1, db=db)
    """
    model_lower = model_name.lower()

    # Auto-detect provider if not specified
    if not provider:
        if "claude" in model_lower or "anthropic" in model_lower:
            # Only use native Anthropic adapter for non-OpenRouter Claude models
            if not model_name.startswith("openrouter/"):
                provider = "anthropic"
            else:
                provider = "openai"  # OpenRouter uses OpenAI-compatible API
        else:
            # Default to OpenAI-compatible
            provider = "openai"

    if provider == "anthropic":
        # Native Anthropic API (not implemented for async client fetching yet)
        # For now, this would require direct API key - not commonly used
        raise NotImplementedError("Native Anthropic adapter not yet updated for centralized routing")
    elif provider == "openai":
        # Get configured client using centralized routing
        client = await get_llm_client(user_id, model_name, db)

        # Create adapter with the configured client
        return OpenAIAdapter(
            model_name=model_name,
            client=client,
            **kwargs
        )
    else:
        raise ValueError(f"Unsupported provider: {provider}")


