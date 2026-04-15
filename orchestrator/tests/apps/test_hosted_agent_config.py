"""Tests for HostedAgentConfig dataclass serialization."""

from __future__ import annotations

from app.services.base_config_parser import HostedAgentConfig


def test_hosted_agent_config_roundtrip() -> None:
    original = HostedAgentConfig(
        id="agent-1",
        system_prompt_ref="prompts/primary.md",
        model_pref="claude-opus",
        tools_ref=("read", "write"),
        mcps_ref=("github",),
        temperature=0.2,
        max_tokens=2048,
        thinking_effort="medium",
        warm_pool_size=3,
    )
    roundtripped = HostedAgentConfig.from_dict(original.to_dict())
    assert roundtripped == original


def test_hosted_agent_config_optional_fields_omitted() -> None:
    cfg = HostedAgentConfig(id="a", system_prompt_ref="p.md")
    d = cfg.to_dict()
    # Only required fields present; Nones/empties elided.
    assert d == {"id": "a", "system_prompt_ref": "p.md"}
    # Round-trip preserves absence.
    assert HostedAgentConfig.from_dict(d) == cfg
    assert HostedAgentConfig.from_dict(d).tools_ref == ()
    assert HostedAgentConfig.from_dict(d).model_pref is None
