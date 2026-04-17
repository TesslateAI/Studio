"""Wave 9 Track A3: merger emits 2025-02 manifest shape.

Verifies the canvas→manifest merger now produces ``manifest_schema_version =
"2025-02"`` with primary/kind/image on containers, explicit connector_type +
config on compute.connections, and trigger_kind/execution/editable/optional on
schedules. Validates the emitted dict against the frozen 2025-02 schema via
``manifest_parser.parse``.
"""

from __future__ import annotations

from copy import deepcopy

from app.services.apps.manifest_merger import (
    MANIFEST_SCHEMA_VERSION,
    merge_canvas_config,
)
from app.services.apps.manifest_parser import parse


def _user_overrides() -> dict:
    return {
        "app": {
            "id": "com.example.wave9-app",
            "name": "Wave 9 App",
            "slug": "wave9-app",
            "version": "0.1.0",
        },
        "billing": {
            "ai_compute": {"payer": "installer"},
            "general_compute": {"payer": "installer"},
            "platform_fee": {"model": "free", "price_usd": 0},
        },
        "listing": {"visibility": "public"},
    }


def _base_config() -> dict:
    # Two containers: a primary frontend (base) and a postgres service.
    # One connection (env_injection) and one schedule (webhook trigger).
    return {
        "containers": [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "name": "web",
                "image": "nginx:1.27",
                "role": "frontend",
                "entrypoint": "/",
                "is_primary": True,
                "container_type": "base",
            },
            {
                "id": "22222222-2222-2222-2222-222222222222",
                "name": "db",
                "image": "postgres:16",
                "role": "database",
                "is_primary": False,
                "container_type": "service",
            },
        ],
        "connections": [
            {
                "source_container_id": "11111111-1111-1111-1111-111111111111",
                "target_container_id": "22222222-2222-2222-2222-222222222222",
                "connector_type": "env_injection",
                "config": {"env_mapping": {"DATABASE_URL": "DATABASE_URL"}},
            }
        ],
        "agent_schedules": [
            {
                "name": "ingest",
                "trigger_kind": "webhook",
                "execution": "http-post",
                "entrypoint": "agents/ingest",
                "editable": True,
                "optional": False,
            }
        ],
        "hosted_agents": (),
    }


def test_merger_emits_2025_02_schema_version() -> None:
    result = merge_canvas_config(
        base_config=_base_config(),
        user_overrides=_user_overrides(),
        creator_user_id="33333333-3333-3333-3333-333333333333",
    )
    assert MANIFEST_SCHEMA_VERSION == "2025-02"
    assert result.manifest_dict["manifest_schema_version"] == "2025-02"
    assert result.manifest_dict["compatibility"]["manifest_schema"] == "2025-02"


def test_merger_emits_primary_kind_image_on_containers() -> None:
    result = merge_canvas_config(
        base_config=_base_config(),
        user_overrides=_user_overrides(),
        creator_user_id="33333333-3333-3333-3333-333333333333",
    )
    containers = result.manifest_dict["compute"]["containers"]
    by_name = {c["name"]: c for c in containers}

    web = by_name["web"]
    assert web["primary"] is True
    assert web["kind"] == "base"
    assert web["image"] == "nginx:1.27"

    db = by_name["db"]
    assert db["primary"] is False
    assert db["kind"] == "service"
    assert db["image"] == "postgres:16"


def test_merger_emits_explicit_connector_type_and_config() -> None:
    result = merge_canvas_config(
        base_config=_base_config(),
        user_overrides=_user_overrides(),
        creator_user_id="33333333-3333-3333-3333-333333333333",
    )
    conns = result.manifest_dict["compute"]["connections"]
    assert len(conns) == 1
    conn = conns[0]
    assert conn["source_container"] == "web"
    assert conn["target_container"] == "db"
    assert conn["connector_type"] == "env_injection"
    assert conn["config"] == {"env_mapping": {"DATABASE_URL": "DATABASE_URL"}}


def test_merger_emits_schedule_trigger_kind_and_defaults() -> None:
    result = merge_canvas_config(
        base_config=_base_config(),
        user_overrides=_user_overrides(),
        creator_user_id="33333333-3333-3333-3333-333333333333",
    )
    schedules = result.manifest_dict["schedules"]
    assert len(schedules) == 1
    sched = schedules[0]
    assert sched["name"] == "ingest"
    assert sched["trigger_kind"] == "webhook"
    assert sched["execution"] == "http-post"
    assert sched["editable"] is True
    assert sched["optional"] is False
    assert sched["entrypoint"] == "agents/ingest"


def test_merger_output_validates_against_2025_02_schema() -> None:
    result = merge_canvas_config(
        base_config=_base_config(),
        user_overrides=_user_overrides(),
        creator_user_id="33333333-3333-3333-3333-333333333333",
    )
    # parse() dispatches on manifest_schema_version → uses the 2025-02 validator.
    parsed = parse(deepcopy(result.manifest_dict))
    assert parsed.schema_version == "2025-02"
    # Pydantic mirror is still 2025-01-only; parsed.manifest is None for newer
    # versions and the raw dict remains canonical.
    assert parsed.manifest is None
    assert parsed.raw["app"]["slug"] == "wave9-app"


def test_parser_still_accepts_2025_01_for_back_compat() -> None:
    legacy = {
        "manifest_schema_version": "2025-01",
        "app": {
            "id": "com.example.legacy",
            "name": "Legacy",
            "slug": "legacy",
            "version": "0.1.0",
        },
        "compatibility": {
            "studio": {"min": "3.2.0"},
            "manifest_schema": "2025-01",
            "runtime_api": "^1.0",
        },
        "surfaces": [{"kind": "ui", "entrypoint": "index.html"}],
        "state": {"model": "stateless"},
        "billing": {
            "ai_compute": {"payer": "installer"},
            "general_compute": {"payer": "installer"},
            "platform_fee": {"model": "free", "price_usd": 0},
        },
        "listing": {"visibility": "public"},
    }
    parsed = parse(legacy)
    assert parsed.schema_version == "2025-01"
    # 2025-01 still hydrates the Pydantic mirror.
    assert parsed.manifest is not None
    assert parsed.manifest.app.slug == "legacy"
