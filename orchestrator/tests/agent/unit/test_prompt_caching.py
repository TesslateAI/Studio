"""
Unit tests for prompt caching — eligibility detection, breakpoint injection,
strip-and-reinject across iterations, and the LiteLLM startup refresh.
"""

import copy
from unittest.mock import AsyncMock, patch

import pytest

import app.agent.prompt_caching as pc
from app.agent.prompt_caching import (
    inject_cache_breakpoints,
    is_cache_eligible,
    refresh_eligible_models,
)

# ---- Helpers ----

BP = {"type": "ephemeral"}


def _has_bp(msg: dict) -> bool:
    """Return True if the message's content has a cache_control breakpoint."""
    content = msg.get("content")
    if isinstance(content, list):
        return any(isinstance(b, dict) and b.get("cache_control") == BP for b in content)
    return False


def _count_bps(messages: list[dict]) -> int:
    """Count total breakpoints across all messages."""
    return sum(1 for m in messages if _has_bp(m))


@pytest.fixture(autouse=True)
def _reset_eligible_cache():
    """Reset the module-level eligible set before each test."""
    original = pc._eligible_builtin_models
    # Default: simulate a populated cache with Claude models
    pc._eligible_builtin_models = {
        "claude-opus-4.6",
        "claude-sonnet-4.6",
        "claude-opus-4.5",
        "claude-sonnet-4.5",
        "claude-haiku-4.5",
    }
    yield
    pc._eligible_builtin_models = original


# =============================================================================
# is_cache_eligible — builtin / LiteLLM path
# =============================================================================


@pytest.mark.unit
class TestCacheEligibilityBuiltin:
    """Eligibility for builtin models is driven by the LiteLLM model_info set."""

    def test_eligible_builtin_model(self):
        assert is_cache_eligible("claude-opus-4.6") is True

    def test_eligible_builtin_with_prefix(self):
        assert is_cache_eligible("builtin/claude-sonnet-4.6") is True

    def test_ineligible_builtin_model(self):
        assert is_cache_eligible("deepseek-v3.2") is False

    def test_ineligible_builtin_with_prefix(self):
        assert is_cache_eligible("builtin/deepseek-v3.2") is False

    def test_all_non_claude_builtin_models_ineligible(self):
        for name in [
            "llama-4-maverick-17b",
            "mistral-large-3",
            "qwen3-32b",
            "gpt-oss-120b",
            "glm-4.7",
            "kimi-k2-thinking",
            "minimax-m2.1",
            "devstral-2-135b",
        ]:
            assert is_cache_eligible(name) is False, f"{name} should not be eligible"

    def test_not_populated_yet_returns_false(self):
        """Before startup refresh, builtin models are safely ineligible."""
        pc._eligible_builtin_models = None
        assert is_cache_eligible("claude-opus-4.6") is False

    def test_empty_set_returns_false(self):
        """If LiteLLM returned no models with the flag, nothing is eligible."""
        pc._eligible_builtin_models = set()
        assert is_cache_eligible("claude-opus-4.6") is False

    def test_dynamically_added_model_eligible(self):
        """New models added to the set (via refresh) are immediately eligible."""
        pc._eligible_builtin_models.add("some-new-model")
        assert is_cache_eligible("some-new-model") is True


# =============================================================================
# is_cache_eligible — BYOK path
# =============================================================================


@pytest.mark.unit
class TestCacheEligibilityBYOK:
    """Eligibility for BYOK models is driven by BUILTIN_PROVIDERS metadata."""

    def test_anthropic_direct_eligible(self):
        assert is_cache_eligible("anthropic/claude-3.5-sonnet") is True

    def test_openai_direct_not_eligible(self):
        """OpenAI has automatic caching, no explicit annotations needed."""
        assert is_cache_eligible("openai/gpt-4o") is False

    def test_deepseek_direct_not_eligible(self):
        assert is_cache_eligible("deepseek/deepseek-v3.2") is False

    def test_groq_not_eligible(self):
        assert is_cache_eligible("groq/gpt-oss-120b") is False

    def test_together_not_eligible(self):
        assert is_cache_eligible("together/llama-3.3-70b") is False

    def test_fireworks_not_eligible(self):
        assert is_cache_eligible("fireworks/llama-3.3-70b") is False

    def test_custom_provider_not_eligible(self):
        """Custom providers fall through to the builtin path, not BYOK."""
        assert is_cache_eligible("custom/my-provider/model-x") is False


# =============================================================================
# is_cache_eligible — edge cases
# =============================================================================


@pytest.mark.unit
class TestCacheEligibilityEdgeCases:
    def test_empty_string(self):
        assert is_cache_eligible("") is False

    def test_none(self):
        assert is_cache_eligible(None) is False

    def test_whitespace(self):
        assert is_cache_eligible("   ") is False

    def test_unknown_provider_prefix(self):
        assert is_cache_eligible("unknownprovider/some-model") is False


# =============================================================================
# refresh_eligible_models — startup fetch
# =============================================================================


@pytest.mark.unit
class TestRefreshEligibleModels:
    @pytest.mark.asyncio
    async def test_populates_from_litellm_model_info(self):
        mock_data = [
            {
                "model_name": "claude-opus-4.6",
                "model_info": {"supports_prompt_caching": True, "max_tokens": 128000},
            },
            {
                "model_name": "claude-sonnet-4.6",
                "model_info": {"supports_prompt_caching": True},
            },
            {
                "model_name": "deepseek-v3.2",
                "model_info": {"max_tokens": 32768},
            },
            {
                "model_name": "llama-4-maverick-17b",
                "model_info": {"supports_prompt_caching": False},
            },
        ]

        with patch(
            "app.agent.prompt_caching.litellm_service",
            create=True,
        ) as mock_svc:
            mock_svc.get_model_info = AsyncMock(return_value=mock_data)

            # Need to patch the import inside the function
            with patch(
                "app.services.litellm_service.litellm_service",
                mock_svc,
            ):
                await refresh_eligible_models()

        assert pc._eligible_builtin_models == {"claude-opus-4.6", "claude-sonnet-4.6"}

    @pytest.mark.asyncio
    async def test_litellm_unreachable_sets_empty(self):
        with patch(
            "app.services.litellm_service.litellm_service",
        ) as mock_svc:
            mock_svc.get_model_info = AsyncMock(side_effect=Exception("connection refused"))
            await refresh_eligible_models()

        assert pc._eligible_builtin_models == set()

    @pytest.mark.asyncio
    async def test_skips_entries_without_model_name(self):
        mock_data = [
            {"model_info": {"supports_prompt_caching": True}},
            {"model_name": "", "model_info": {"supports_prompt_caching": True}},
            {"model_name": "valid-model", "model_info": {"supports_prompt_caching": True}},
        ]

        with patch(
            "app.services.litellm_service.litellm_service",
        ) as mock_svc:
            mock_svc.get_model_info = AsyncMock(return_value=mock_data)
            await refresh_eligible_models()

        assert pc._eligible_builtin_models == {"valid-model"}


# =============================================================================
# inject_cache_breakpoints — system message
# =============================================================================


@pytest.mark.unit
class TestInjectSystemMessage:
    def test_system_message_gets_breakpoint(self):
        msgs = [
            {"role": "system", "content": "You are an AI."},
            {"role": "user", "content": "Hello"},
        ]
        inject_cache_breakpoints(msgs, "claude-opus-4.6")

        assert _has_bp(msgs[0])
        assert isinstance(msgs[0]["content"], list)
        assert msgs[0]["content"][0]["text"] == "You are an AI."
        assert msgs[0]["content"][0]["cache_control"] == BP

    def test_no_system_message_skips(self):
        msgs = [
            {"role": "user", "content": "Hello"},
        ]
        inject_cache_breakpoints(msgs, "claude-opus-4.6")
        # Should not crash; user message shouldn't get system BP
        assert not _has_bp(msgs[0])

    def test_system_with_existing_blocks_preserved(self):
        msgs = [
            {
                "role": "system",
                "content": [
                    {"type": "text", "text": "Part 1"},
                    {"type": "text", "text": "Part 2"},
                ],
            },
            {"role": "user", "content": "Hello"},
        ]
        inject_cache_breakpoints(msgs, "claude-opus-4.6")

        # BP goes on the LAST block
        assert msgs[0]["content"][0].get("cache_control") is None
        assert msgs[0]["content"][1]["cache_control"] == BP


# =============================================================================
# inject_cache_breakpoints — trailing breakpoint
# =============================================================================


@pytest.mark.unit
class TestInjectTrailingBreakpoint:
    def test_two_messages_only_system_bp(self):
        """With just [system, user], only system gets a breakpoint (len < 3)."""
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
        ]
        inject_cache_breakpoints(msgs, "claude-opus-4.6")

        assert _has_bp(msgs[0])
        assert not _has_bp(msgs[1])
        assert _count_bps(msgs) == 1

    def test_agentic_loop_trailing_on_tool(self):
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "Write code."},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "tc1"}]},
            {"role": "tool", "tool_call_id": "tc1", "content": "file contents"},
            {"role": "tool", "tool_call_id": "tc2", "content": "more output"},
        ]
        inject_cache_breakpoints(msgs, "claude-opus-4.6")

        assert _has_bp(msgs[0])  # system
        assert _has_bp(msgs[3])  # second-to-last (tool)
        assert not _has_bp(msgs[4])  # last message — no BP
        assert _count_bps(msgs) == 2

    def test_skips_none_content_assistant(self):
        """Trailing BP skips assistant messages with content=None."""
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": None},
            {"role": "assistant", "content": None},
            {"role": "user", "content": "follow up"},
        ]
        inject_cache_breakpoints(msgs, "claude-opus-4.6")

        # Should skip both None assistants, land on msgs[1] (user)
        assert _has_bp(msgs[0])
        assert _has_bp(msgs[1])
        assert _count_bps(msgs) == 2

    def test_multi_turn_chat_history(self):
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "first turn"},
            {"role": "assistant", "content": "first response"},
            {"role": "user", "content": "second turn"},
            {"role": "assistant", "content": "second response"},
            {"role": "user", "content": "current turn"},
        ]
        inject_cache_breakpoints(msgs, "claude-opus-4.6")

        assert _has_bp(msgs[0])  # system
        assert _has_bp(msgs[4])  # second-to-last = "second response"
        assert not _has_bp(msgs[5])  # last message
        assert _count_bps(msgs) == 2


# =============================================================================
# inject_cache_breakpoints — strip and reinject
# =============================================================================


@pytest.mark.unit
class TestStripAndReinject:
    def test_old_breakpoints_stripped(self):
        """Breakpoints from a prior iteration are removed before fresh injection."""
        msgs = [
            {
                "role": "system",
                "content": [
                    {"type": "text", "text": "sys", "cache_control": BP},
                ],
            },
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": None},
            {
                "role": "tool",
                "tool_call_id": "tc1",
                "content": [
                    {"type": "text", "text": "old result", "cache_control": BP},
                ],
            },
            {"role": "tool", "tool_call_id": "tc2", "content": "new result"},
            {"role": "assistant", "content": None},
            {"role": "tool", "tool_call_id": "tc3", "content": "newest result"},
        ]
        inject_cache_breakpoints(msgs, "claude-opus-4.6")

        # Old BP on msgs[3] should be stripped and simplified back to string
        assert msgs[3]["content"] == "old result"
        # New trailing BP on msgs[5] (second-to-last with content)
        assert _has_bp(msgs[4])
        # System still has BP
        assert _has_bp(msgs[0])
        assert _count_bps(msgs) == 2

    def test_rolling_breakpoint_moves_forward(self):
        """Simulate two consecutive iterations — BP moves to the newer prefix."""
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": None},
            {"role": "tool", "tool_call_id": "tc1", "content": "result 1"},
        ]

        # First injection
        inject_cache_breakpoints(msgs, "claude-opus-4.6")
        assert _has_bp(msgs[1])  # trailing on user (second-to-last with content)

        # Simulate next iteration: append new tool results
        msgs.append({"role": "assistant", "content": None, "tool_calls": [{"id": "tc2"}]})
        msgs.append({"role": "tool", "tool_call_id": "tc2", "content": "result 2"})
        msgs.append({"role": "tool", "tool_call_id": "tc3", "content": "result 3"})

        # Second injection — BP should move forward
        inject_cache_breakpoints(msgs, "claude-opus-4.6")
        assert not _has_bp(msgs[1])  # old user BP stripped
        assert _has_bp(msgs[5])  # new trailing on "result 2" (second-to-last)
        assert not _has_bp(msgs[6])  # last message, no BP
        assert _count_bps(msgs) == 2


# =============================================================================
# inject_cache_breakpoints — no-op cases
# =============================================================================


@pytest.mark.unit
class TestInjectNoOp:
    def test_noop_for_ineligible_model(self):
        msgs = [{"role": "system", "content": "sys"}]
        original = copy.deepcopy(msgs)
        inject_cache_breakpoints(msgs, "gpt-4o")
        assert msgs == original

    def test_noop_for_empty_messages(self):
        msgs = []
        inject_cache_breakpoints(msgs, "claude-opus-4.6")
        assert msgs == []

    def test_noop_before_startup_refresh(self):
        pc._eligible_builtin_models = None
        msgs = [{"role": "system", "content": "sys"}]
        original = copy.deepcopy(msgs)
        inject_cache_breakpoints(msgs, "claude-opus-4.6")
        assert msgs == original


# =============================================================================
# extract_provider_slug (used by is_cache_eligible)
# =============================================================================


@pytest.mark.unit
class TestExtractProviderSlug:
    def test_known_providers(self):
        from app.agent.models import extract_provider_slug

        assert extract_provider_slug("anthropic/claude-3.5-sonnet") == "anthropic"
        assert extract_provider_slug("openai/gpt-4o") == "openai"
        assert extract_provider_slug("groq/gpt-oss-120b") == "groq"
        assert extract_provider_slug("deepseek/deepseek-v3.2") == "deepseek"

    def test_builtin_prefix_returns_none(self):
        from app.agent.models import extract_provider_slug

        assert extract_provider_slug("builtin/claude-opus-4.6") is None

    def test_custom_prefix_returns_none(self):
        from app.agent.models import extract_provider_slug

        assert extract_provider_slug("custom/my-provider/model-x") is None

    def test_no_slash_returns_none(self):
        from app.agent.models import extract_provider_slug

        assert extract_provider_slug("claude-opus-4.6") is None

    def test_unknown_slug_returns_none(self):
        from app.agent.models import extract_provider_slug

        assert extract_provider_slug("unknownprovider/some-model") is None

    def test_empty_returns_none(self):
        from app.agent.models import extract_provider_slug

        assert extract_provider_slug("") is None
        assert extract_provider_slug(None) is None
