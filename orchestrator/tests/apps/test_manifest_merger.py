"""Tests for the publish-time manifest merger."""

from __future__ import annotations

from copy import deepcopy

import pytest

from app.services.apps.manifest_merger import merge_canvas_config
from app.services.apps.manifest_parser import parse
from app.services.base_config_parser import HostedAgentConfig


def _user_overrides(**extras) -> dict:
    base = {
        "app": {
            "id": "com.example.my-app",
            "name": "My App",
            "slug": "my-app",
            "version": "0.1.0",
        },
        "billing": {
            "ai_compute": {"payer": "installer"},
            "general_compute": {"payer": "installer"},
            "platform_fee": {"model": "free", "price_usd": 0},
        },
        "listing": {"visibility": "public"},
    }
    base.update(extras)
    return base


def _base_config(**extras) -> dict:
    cfg = {"containers": [], "hosted_agents": ()}
    cfg.update(extras)
    return cfg


def test_merge_requires_billing() -> None:
    overrides = _user_overrides()
    overrides.pop("billing")
    with pytest.raises(ValueError, match="billing"):
        merge_canvas_config(
            base_config=_base_config(containers=[{"name": "web", "image": "nginx", "role": "frontend"}]),
            user_overrides=overrides,
            creator_user_id="11111111-1111-1111-1111-111111111111",
        )


def test_merge_infers_stateless_when_no_volumes() -> None:
    result = merge_canvas_config(
        base_config=_base_config(containers=[{"name": "web", "image": "nginx", "role": "frontend"}]),
        user_overrides=_user_overrides(),
        creator_user_id="11111111-1111-1111-1111-111111111111",
    )
    assert result.manifest_dict["state"] == {"model": "stateless"}
    assert result.inferred["state.model"] == "inferred:no-persistent-volumes"


def test_merge_infers_byo_database_when_db_container() -> None:
    result = merge_canvas_config(
        base_config=_base_config(
            containers=[
                {"name": "web", "image": "nginx", "role": "frontend"},
                {"name": "db", "image": "postgres:16", "role": "database", "db_schema": "public"},
            ],
        ),
        user_overrides=_user_overrides(),
        creator_user_id="11111111-1111-1111-1111-111111111111",
    )
    assert result.manifest_dict["state"]["model"] == "byo-database"
    assert result.manifest_dict["state"]["byo_database"]["schema"] == "public"
    assert result.inferred["state.model"].startswith("inferred:db-container=")


def test_merge_infers_ui_surface_from_frontend_container() -> None:
    result = merge_canvas_config(
        base_config=_base_config(
            containers=[{"name": "web", "image": "nginx", "role": "frontend", "entrypoint": "/"}],
        ),
        user_overrides=_user_overrides(),
        creator_user_id="11111111-1111-1111-1111-111111111111",
    )
    assert result.manifest_dict["surfaces"] == [{"kind": "ui", "entrypoint": "/"}]
    assert "surfaces[0].kind" in result.inferred


def test_merge_copies_hosted_agents() -> None:
    agents = (
        HostedAgentConfig(id="a1", system_prompt_ref="p1.md", tools_ref=("read",)),
        HostedAgentConfig(id="a2", system_prompt_ref="p2.md", model_pref="claude"),
    )
    result = merge_canvas_config(
        base_config=_base_config(
            containers=[{"name": "web", "image": "nginx", "role": "frontend"}],
            hosted_agents=agents,
        ),
        user_overrides=_user_overrides(),
        creator_user_id="11111111-1111-1111-1111-111111111111",
    )
    ha = result.manifest_dict["compute"]["hosted_agents"]
    assert len(ha) == 2
    assert ha[0]["id"] == "a1"
    assert ha[0]["tools_ref"] == ["read"]
    assert ha[1]["model_pref"] == "claude"


def test_merge_user_surfaces_override_inferred() -> None:
    user_surfaces = [{"kind": "chat", "entrypoint": "agents/primary"}]
    result = merge_canvas_config(
        base_config=_base_config(
            containers=[{"name": "web", "image": "nginx", "role": "frontend"}],
        ),
        user_overrides=_user_overrides(surfaces=user_surfaces),
        creator_user_id="11111111-1111-1111-1111-111111111111",
    )
    assert result.manifest_dict["surfaces"] == user_surfaces
    # No inferred surface markers when user supplied them.
    assert not any(k.startswith("surfaces[") for k in result.inferred)


def test_merge_produces_schema_valid_dict() -> None:
    result = merge_canvas_config(
        base_config=_base_config(
            containers=[{"name": "web", "image": "nginx:1.27", "role": "frontend", "entrypoint": "index.html"}],
            hosted_agents=(HostedAgentConfig(id="a1", system_prompt_ref="p1.md"),),
        ),
        user_overrides=_user_overrides(
            compatibility={"studio": {"min": "3.2.0"}, "runtime_api": "^1.0"},
        ),
        creator_user_id="11111111-1111-1111-1111-111111111111",
    )
    parsed = parse(deepcopy(result.manifest_dict))
    # Merger now emits 2025-02; the Pydantic mirror is still 2025-01-only, so
    # parsed.manifest is None and we assert against the validated raw dict.
    assert parsed.schema_version == "2025-02"
    assert parsed.raw["app"]["slug"] == "my-app"
    assert parsed.raw["compute"]["hosted_agents"][0]["id"] == "a1"
    assert parsed.raw["state"]["model"] == "stateless"
