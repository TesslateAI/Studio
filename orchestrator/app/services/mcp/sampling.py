"""
MCP sampling handler — routes server-initiated LLM requests through LiteLLM.

When an MCP server calls ``sampling/createMessage``, this handler converts
the MCP message format to OpenAI-compatible format, calls LiteLLM via
the same proxy the agent uses, and returns the result.

Security controls:
- Per-server rate limiting (sliding 60-second window)
- Model whitelist (optional)
- Token cap enforcement
- Configurable timeout
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from ...config import get_settings
from .security import sanitize_error

logger = logging.getLogger(__name__)

# MCP SDK sampling types — imported conditionally for compatibility
try:
    from mcp.types import (  # noqa: F401
        CreateMessageRequestParams,
        CreateMessageResult,
        SamplingMessage,
        TextContent,
    )

    _SAMPLING_TYPES_AVAILABLE = True
except ImportError:
    _SAMPLING_TYPES_AVAILABLE = False

# MCP stop reason mapping (MCP uses different names than OpenAI)
_STOP_REASON_MAP = {
    "stop": "endTurn",
    "end_turn": "endTurn",
    "length": "maxTokens",
    "max_tokens": "maxTokens",
    "tool_calls": "toolUse",
}


class McpSamplingHandler:
    """Handles MCP server-initiated LLM completion requests.

    Each MCP server can have its own sampling configuration controlling
    rate limits, model selection, token caps, etc.

    This handler is passed as ``sampling_callback`` to :class:`ClientSession`.

    Parameters
    ----------
    server_name:
        Identifier for logging and rate-limit scoping.
    config:
        Per-server sampling config dict. Keys:
          - ``model``: Override model name (empty = use default)
          - ``max_tokens_cap``: Max tokens per request
          - ``timeout``: LLM call timeout in seconds
          - ``max_rpm``: Rate limit (requests per minute)
          - ``allowed_models``: Optional whitelist of model names
    litellm_api_key:
        User's LiteLLM API key for proxy auth.
    litellm_api_base:
        LiteLLM proxy base URL.
    """

    def __init__(
        self,
        server_name: str,
        config: dict[str, Any] | None = None,
        *,
        litellm_api_key: str = "",
        litellm_api_base: str = "",
    ):
        cfg = config or {}
        settings = get_settings()

        self.server_name = server_name
        self.model_override = cfg.get("model", "") or settings.mcp_sampling_default_model
        self.max_tokens_cap = cfg.get("max_tokens_cap", settings.mcp_sampling_max_tokens)
        self.timeout = cfg.get("timeout", settings.mcp_sampling_timeout)
        self.max_rpm = cfg.get("max_rpm", settings.mcp_sampling_max_rpm)
        self.allowed_models = cfg.get("allowed_models", [])

        self._litellm_api_key = litellm_api_key
        self._litellm_api_base = litellm_api_base or settings.litellm_api_base

        # Sliding-window rate limiter
        self._rate_timestamps: list[float] = []

        # Metrics
        self.metrics: dict[str, int] = {
            "requests": 0,
            "errors": 0,
            "tokens_used": 0,
        }

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _check_rate_limit(self) -> bool:
        """Check sliding 60-second window. Returns True if allowed."""
        now = time.monotonic()
        cutoff = now - 60.0
        self._rate_timestamps = [t for t in self._rate_timestamps if t > cutoff]
        if len(self._rate_timestamps) >= self.max_rpm:
            return False
        self._rate_timestamps.append(now)
        return True

    # ------------------------------------------------------------------
    # Model resolution
    # ------------------------------------------------------------------

    def _resolve_model(self, params: Any) -> str:
        """Resolve which model to use.

        Priority: config override > server hint > fallback.
        """
        if self.model_override:
            return self.model_override

        # Check server's model preferences/hints
        if hasattr(params, "modelPreferences"):
            prefs = params.modelPreferences
            if prefs and hasattr(prefs, "hints") and prefs.hints:
                for hint in prefs.hints:
                    name = getattr(hint, "name", None)
                    if name:
                        return name

        return self.model_override or "gpt-4o-mini"

    # ------------------------------------------------------------------
    # Message conversion (MCP → OpenAI format)
    # ------------------------------------------------------------------

    @staticmethod
    def _convert_messages(
        mcp_messages: list[Any],
        system_prompt: str | None = None,
    ) -> list[dict[str, Any]]:
        """Convert MCP SamplingMessages to OpenAI chat format."""
        messages: list[dict[str, Any]] = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        for msg in mcp_messages:
            role = getattr(msg, "role", "user")

            # Handle content that may be a single block or a list
            content_raw = getattr(msg, "content", None)
            if content_raw is None:
                continue

            # Single TextContent block
            if hasattr(content_raw, "text"):
                messages.append({"role": role, "content": content_raw.text})
                continue

            # List of content blocks
            if isinstance(content_raw, list):
                parts: list[str] = []
                for block in content_raw:
                    text = getattr(block, "text", None)
                    if text:
                        parts.append(text)
                    elif hasattr(block, "data") and hasattr(block, "mimeType"):
                        # Image block — include as data URL
                        parts.append(f"[image: {block.mimeType}]")
                if parts:
                    messages.append({"role": role, "content": "\n".join(parts)})
                continue

            # Fallback: try string coercion
            messages.append({"role": role, "content": str(content_raw)})

        return messages

    # ------------------------------------------------------------------
    # Main callback
    # ------------------------------------------------------------------

    async def __call__(self, params: Any) -> Any:
        """Handle a sampling/createMessage request from an MCP server.

        This is the ``sampling_callback`` passed to :class:`ClientSession`.
        """
        if not _SAMPLING_TYPES_AVAILABLE:
            logger.error("MCP sampling types not available — cannot handle sampling request")
            return None

        # Rate limit
        if not self._check_rate_limit():
            logger.warning(
                "MCP sampling rate limit exceeded for server '%s' (%d rpm)",
                self.server_name,
                self.max_rpm,
            )
            self.metrics["errors"] += 1
            return CreateMessageResult(
                role="assistant",
                content=TextContent(
                    type="text",
                    text="Rate limit exceeded. Please try again later.",
                ),
                model="rate-limited",
                stopReason="endTurn",
            )

        # Resolve model
        model = self._resolve_model(params)
        if self.allowed_models and model not in self.allowed_models:
            logger.warning(
                "MCP sampling: model '%s' not in whitelist for server '%s'",
                model,
                self.server_name,
            )
            self.metrics["errors"] += 1
            return CreateMessageResult(
                role="assistant",
                content=TextContent(
                    type="text",
                    text=f"Model '{model}' is not allowed for sampling.",
                ),
                model=model,
                stopReason="endTurn",
            )

        # Convert messages
        system_prompt = getattr(params, "systemPrompt", None)
        mcp_messages = getattr(params, "messages", [])
        openai_messages = self._convert_messages(mcp_messages, system_prompt)

        # Cap max tokens
        max_tokens = min(
            getattr(params, "maxTokens", self.max_tokens_cap),
            self.max_tokens_cap,
        )

        # Call LiteLLM via AsyncOpenAI
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(
                api_key=self._litellm_api_key,
                base_url=self._litellm_api_base,
                max_retries=1,
            )

            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=model,
                    messages=openai_messages,
                    max_tokens=max_tokens,
                ),
                timeout=self.timeout,
            )

            self.metrics["requests"] += 1

            # Extract response
            choice = response.choices[0] if response.choices else None
            if not choice:
                self.metrics["errors"] += 1
                return CreateMessageResult(
                    role="assistant",
                    content=TextContent(type="text", text="(empty response)"),
                    model=model,
                    stopReason="endTurn",
                )

            # Track token usage
            if response.usage:
                self.metrics["tokens_used"] += getattr(response.usage, "total_tokens", 0)

            response_text = getattr(choice.message, "content", "") or ""
            finish_reason = getattr(choice, "finish_reason", "stop") or "stop"
            stop_reason = _STOP_REASON_MAP.get(finish_reason, "endTurn")

            logger.debug(
                "MCP sampling completed: server=%s model=%s tokens=%s",
                self.server_name,
                model,
                getattr(response.usage, "total_tokens", "?") if response.usage else "?",
            )

            return CreateMessageResult(
                role="assistant",
                content=TextContent(type="text", text=response_text),
                model=model,
                stopReason=stop_reason,
            )

        except TimeoutError:
            logger.error(
                "MCP sampling timed out: server=%s timeout=%ds",
                self.server_name,
                self.timeout,
            )
            self.metrics["errors"] += 1
            return CreateMessageResult(
                role="assistant",
                content=TextContent(
                    type="text",
                    text=f"LLM request timed out after {self.timeout}s.",
                ),
                model=model,
                stopReason="endTurn",
            )

        except Exception as exc:
            logger.error(
                "MCP sampling failed: server=%s error=%s",
                self.server_name,
                exc,
                exc_info=True,
            )
            self.metrics["errors"] += 1
            return CreateMessageResult(
                role="assistant",
                content=TextContent(
                    type="text",
                    text=sanitize_error(f"LLM request failed: {exc}"),
                ),
                model=model,
                stopReason="endTurn",
            )

    def session_kwargs(self) -> dict[str, Any]:
        """Return kwargs to pass to :class:`ClientSession` constructor."""
        return {"sampling_callback": self}
