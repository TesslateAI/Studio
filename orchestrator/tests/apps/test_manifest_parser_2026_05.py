"""Tests for the 2026-05 App Runtime Contract manifest mirror.

Covers:
  * Valid 2026-05 manifest end-to-end (required blocks present, optional
    blocks omitted) parses successfully.
  * Missing required top-level block (``runtime``) is rejected with an
    error that names the field explicitly.
  * ``connectors[].kind=oauth`` + ``exposure=env`` is rejected.
  * ``runtime.state_model=per_install_volume`` + ``max_replicas>1`` is
    rejected (per-replica safety constraint).
  * ``runtime.state_model=service_pvc`` + ``max_replicas>1`` is rejected
    (same constraint applies to service PVCs).
  * ``data_resources[].backed_by_action`` referencing a non-existent
    action is rejected.
  * Optional blocks default to empty lists.
  * Each connector entry must declare ``exposure``.
  * 2025-01 manifests still parse (back-compat sanity check).
"""

from __future__ import annotations

from copy import deepcopy

import pytest

from app.services.apps.app_manifest import AppManifest2026_05
from app.services.apps.manifest_parser import ManifestValidationError, parse


def _minimal_2026_05() -> dict:
    """A minimal manifest with only the four required top-level blocks."""
    return {
        "manifest_schema_version": "2026-05",
        "app": {
            "id": "com.acme.sales-dashboard",
            "name": "Sales Dashboard",
            "version": "1.0.0",
        },
        "runtime": {
            "tenancy_model": "per_install",
            "state_model": "stateless",
        },
        "billing": {
            "ai_compute": {"payer_default": "installer"},
            "general_compute": {"payer_default": "creator"},
            "platform_fee": {"rate_percent": 10},
        },
    }


def _full_2026_05() -> dict:
    """Comprehensive manifest exercising every optional block."""
    return {
        "manifest_schema_version": "2026-05",
        "app": {
            "id": "com.acme.sales-dashboard",
            "name": "Sales Dashboard",
            "version": "1.0.0",
            "category": "dashboard",
            "forkable": False,
        },
        "runtime": {
            "tenancy_model": "per_install",
            "state_model": "per_install_volume",
            "scaling": {
                "min_replicas": 0,
                "max_replicas": 1,
                "target_concurrency": 25,
                "idle_timeout_seconds": 600,
            },
            "storage": {"write_scope": ["/app/data"]},
        },
        "billing": {
            "ai_compute": {"payer_default": "installer"},
            "general_compute": {"payer_default": "creator"},
            "platform_fee": {"rate_percent": 10},
        },
        "surfaces": [
            {"kind": "ui", "name": "dashboard", "entrypoint": "/", "container": "web"},
            {"kind": "chat", "name": "ask", "entrypoint": "/chat"},
            {"kind": "card", "name": "account_summary", "entrypoint": "/embed/account"},
        ],
        "actions": [
            {
                "name": "summarize_pipeline",
                "handler": {
                    "kind": "http_post",
                    "container": "api",
                    "path": "/actions/summarize-pipeline",
                },
                "input_schema": {
                    "type": "object",
                    "properties": {"team_id": {"type": "string"}},
                    "required": ["team_id"],
                },
                "output_schema": {
                    "type": "object",
                    "required": ["summary"],
                    "properties": {"summary": {"type": "string"}},
                },
                "timeout_seconds": 60,
                "idempotency": {"kind": "input_hash", "ttl_seconds": 3600},
                "billing": {
                    "ai_compute": {
                        "dimension": "ai_compute",
                        "payer_default": "installer",
                    },
                    "general_compute": {
                        "dimension": "general_compute",
                        "payer_default": "creator",
                    },
                },
                "required_connectors": ["salesforce"],
                "required_grants": [
                    {
                        "capability": "read",
                        "resource": {"kind": "oauth_connection", "id": "salesforce"},
                    }
                ],
                "result_template": "Summary: {{ output.summary }}",
                "artifacts": [
                    {
                        "name": "pipeline_summary.md",
                        "kind": "markdown",
                        "from": "output.summary",
                    }
                ],
            },
            {
                "name": "list_accounts",
                "handler": {
                    "kind": "http_post",
                    "container": "api",
                    "path": "/actions/list-accounts",
                },
            },
        ],
        "views": [
            {
                "name": "account_card",
                "kind": "card",
                "entrypoint": "/embed/account-card",
                "input_schema": {"type": "object", "required": ["account_id"]},
                "cache_ttl_seconds": 60,
            }
        ],
        "data_resources": [
            {
                "name": "accounts",
                "backed_by_action": "list_accounts",
                "schema": {
                    "type": "array",
                    "items": {"type": "object", "required": ["id", "name"]},
                },
                "cache_ttl_seconds": 60,
            }
        ],
        "dependencies": [
            {
                "alias": "crm",
                "app_id": "com.opensail.crm",
                "required": True,
                "needs": {
                    "actions": ["list_accounts"],
                    "views": ["account_card"],
                    "data_resources": ["accounts"],
                },
            }
        ],
        "connectors": [
            {
                "id": "salesforce",
                "kind": "oauth",
                "exposure": "proxy",
                "scopes": ["accounts.read", "opportunities.read"],
            },
            {"id": "internal_api", "kind": "api_key", "exposure": "env"},
        ],
        "automation_templates": [
            {
                "name": "weekly_pipeline_digest",
                "description": "Post a pipeline digest to Slack every Monday 9am",
                "trigger": {"kind": "cron", "expression": "0 9 * * 1"},
                "action": {
                    "kind": "app.invoke",
                    "action": "summarize_pipeline",
                    "input": {"team_id": "${installer.team_id}"},
                },
                "delivery": {"kind": "prompt_user_at_install"},
                "contract_template": {
                    "max_spend_per_run_usd": 0.10,
                    "allowed_apps_self": True,
                },
                "is_default_enabled": True,
            }
        ],
    }


# ---------------------------------------------------------------------------
# Happy paths.
# ---------------------------------------------------------------------------


def test_minimal_2026_05_manifest_parses() -> None:
    parsed = parse(_minimal_2026_05())
    assert parsed.schema_version == "2026-05"
    assert isinstance(parsed.manifest, AppManifest2026_05)
    assert parsed.manifest.runtime.state_model == "stateless"
    assert parsed.manifest.runtime.scaling.max_replicas == 1  # default
    # Optional blocks default to empty lists.
    assert parsed.manifest.surfaces == []
    assert parsed.manifest.actions == []
    assert parsed.manifest.views == []
    assert parsed.manifest.data_resources == []
    assert parsed.manifest.dependencies == []
    assert parsed.manifest.connectors == []
    assert parsed.manifest.automation_templates == []


def test_full_2026_05_manifest_parses_end_to_end() -> None:
    parsed = parse(_full_2026_05())
    m = parsed.manifest
    assert isinstance(m, AppManifest2026_05)
    assert m.app.id == "com.acme.sales-dashboard"
    assert m.runtime.tenancy_model == "per_install"
    assert m.runtime.state_model == "per_install_volume"
    assert m.runtime.storage is not None
    assert m.runtime.storage.write_scope == ["/app/data"]
    assert m.billing.platform_fee.rate_percent == 10
    assert len(m.actions) == 2
    assert m.actions[0].name == "summarize_pipeline"
    assert m.actions[0].artifacts[0].from_ == "output.summary"
    assert m.connectors[0].kind == "oauth"
    assert m.connectors[0].exposure == "proxy"
    assert m.connectors[1].exposure == "env"
    assert m.data_resources[0].backed_by_action == "list_accounts"
    assert m.data_resources[0].schema_["type"] == "array"
    assert m.dependencies[0].needs is not None
    assert m.dependencies[0].needs.actions == ["list_accounts"]
    assert m.automation_templates[0].trigger.kind == "cron"
    assert m.automation_templates[0].action.kind == "app.invoke"
    assert len(parsed.canonical_hash) == 64


def test_2026_05_yaml_string_parses() -> None:
    yaml_text = """
manifest_schema_version: "2026-05"
app:
  id: com.acme.simple
  name: Simple App
  version: 0.1.0
runtime:
  tenancy_model: per_install
  state_model: stateless
billing:
  ai_compute: { payer_default: installer }
  general_compute: { payer_default: creator }
  platform_fee: { rate_percent: 0 }
"""
    parsed = parse(yaml_text)
    assert parsed.schema_version == "2026-05"
    assert isinstance(parsed.manifest, AppManifest2026_05)


# ---------------------------------------------------------------------------
# Required-block enforcement.
# ---------------------------------------------------------------------------


def test_missing_runtime_block_rejected_and_names_field() -> None:
    raw = _minimal_2026_05()
    del raw["runtime"]
    with pytest.raises(ManifestValidationError) as exc_info:
        parse(raw)
    # The error list must mention runtime explicitly so creators can fix it.
    rendered = str(exc_info.value) + " " + str(exc_info.value.errors)
    assert "runtime" in rendered


def test_missing_billing_block_rejected_and_names_field() -> None:
    raw = _minimal_2026_05()
    del raw["billing"]
    with pytest.raises(ManifestValidationError) as exc_info:
        parse(raw)
    rendered = str(exc_info.value) + " " + str(exc_info.value.errors)
    assert "billing" in rendered


def test_missing_app_block_rejected_and_names_field() -> None:
    raw = _minimal_2026_05()
    del raw["app"]
    with pytest.raises(ManifestValidationError) as exc_info:
        parse(raw)
    rendered = str(exc_info.value) + " " + str(exc_info.value.errors)
    assert "app" in rendered


# ---------------------------------------------------------------------------
# Connector exposure rules.
# ---------------------------------------------------------------------------


def test_connector_missing_exposure_rejected() -> None:
    raw = _minimal_2026_05()
    raw["connectors"] = [{"id": "gh", "kind": "api_key", "scopes": ["repo"]}]
    with pytest.raises(ManifestValidationError) as exc_info:
        parse(raw)
    rendered = str(exc_info.value) + " " + str(exc_info.value.errors)
    assert "exposure" in rendered


def test_connector_oauth_with_env_exposure_rejected() -> None:
    raw = _minimal_2026_05()
    raw["connectors"] = [
        {"id": "gh", "kind": "oauth", "exposure": "env", "scopes": ["repo"]}
    ]
    with pytest.raises(ManifestValidationError) as exc_info:
        parse(raw)
    rendered = str(exc_info.value) + " " + str(exc_info.value.errors)
    # Pydantic surfaces our custom message — ensure it explains why.
    assert "oauth" in rendered.lower() or "rotat" in rendered.lower()


def test_connector_oauth_with_proxy_exposure_accepted() -> None:
    raw = _minimal_2026_05()
    raw["connectors"] = [
        {"id": "gh", "kind": "oauth", "exposure": "proxy", "scopes": ["repo"]}
    ]
    parsed = parse(raw)
    assert isinstance(parsed.manifest, AppManifest2026_05)
    assert parsed.manifest.connectors[0].exposure == "proxy"


def test_connector_api_key_with_env_exposure_accepted() -> None:
    raw = _minimal_2026_05()
    raw["connectors"] = [{"id": "internal", "kind": "api_key", "exposure": "env"}]
    parsed = parse(raw)
    assert isinstance(parsed.manifest, AppManifest2026_05)
    assert parsed.manifest.connectors[0].exposure == "env"


# ---------------------------------------------------------------------------
# State-model / max-replicas constraint matrix.
# ---------------------------------------------------------------------------


def test_per_install_volume_with_max_replicas_above_one_rejected() -> None:
    raw = _minimal_2026_05()
    raw["runtime"] = {
        "tenancy_model": "per_install",
        "state_model": "per_install_volume",
        "scaling": {"max_replicas": 5},
        "storage": {"write_scope": ["/app/data"]},
    }
    with pytest.raises(ManifestValidationError) as exc_info:
        parse(raw)
    rendered = str(exc_info.value) + " " + str(exc_info.value.errors)
    assert "per_install_volume" in rendered
    assert "max_replicas" in rendered


def test_service_pvc_with_max_replicas_above_one_rejected() -> None:
    raw = _minimal_2026_05()
    raw["runtime"] = {
        "tenancy_model": "shared_singleton",
        "state_model": "service_pvc",
        "scaling": {"max_replicas": 3},
        "storage": {"write_scope": ["/app/data"]},
    }
    with pytest.raises(ManifestValidationError) as exc_info:
        parse(raw)
    rendered = str(exc_info.value) + " " + str(exc_info.value.errors)
    assert "service_pvc" in rendered
    assert "max_replicas" in rendered


def test_stateless_max_replicas_unbounded() -> None:
    raw = _minimal_2026_05()
    raw["runtime"] = {
        "tenancy_model": "shared_singleton",
        "state_model": "stateless",
        "scaling": {"max_replicas": 100},
    }
    parsed = parse(raw)
    assert isinstance(parsed.manifest, AppManifest2026_05)
    assert parsed.manifest.runtime.scaling.max_replicas == 100


def test_shared_volume_max_replicas_unbounded() -> None:
    raw = _minimal_2026_05()
    raw["runtime"] = {
        "tenancy_model": "shared_singleton",
        "state_model": "shared_volume",
        "scaling": {"max_replicas": 10},
        "storage": {"write_scope": ["/app/data"]},
    }
    parsed = parse(raw)
    assert isinstance(parsed.manifest, AppManifest2026_05)
    assert parsed.manifest.runtime.scaling.max_replicas == 10


def test_per_install_volume_with_max_replicas_one_accepted() -> None:
    raw = _minimal_2026_05()
    raw["runtime"] = {
        "tenancy_model": "per_install",
        "state_model": "per_install_volume",
        "scaling": {"max_replicas": 1},
        "storage": {"write_scope": ["/app/data"]},
    }
    parsed = parse(raw)
    assert isinstance(parsed.manifest, AppManifest2026_05)


# ---------------------------------------------------------------------------
# data_resources referential integrity.
# ---------------------------------------------------------------------------


def test_data_resource_referencing_unknown_action_rejected() -> None:
    raw = _minimal_2026_05()
    raw["data_resources"] = [
        {"name": "x", "backed_by_action": "nonexistent", "schema": {}}
    ]
    with pytest.raises(ManifestValidationError) as exc_info:
        parse(raw)
    rendered = str(exc_info.value) + " " + str(exc_info.value.errors)
    assert "backed_by_action" in rendered
    assert "nonexistent" in rendered


def test_data_resource_referencing_known_action_accepted() -> None:
    raw = _minimal_2026_05()
    raw["actions"] = [
        {
            "name": "list_things",
            "handler": {"kind": "http_post", "container": "api", "path": "/x"},
        }
    ]
    raw["data_resources"] = [
        {"name": "things", "backed_by_action": "list_things", "schema": {"type": "array"}}
    ]
    parsed = parse(raw)
    assert isinstance(parsed.manifest, AppManifest2026_05)
    assert parsed.manifest.data_resources[0].backed_by_action == "list_things"


# ---------------------------------------------------------------------------
# Surfaces.
# ---------------------------------------------------------------------------


def test_2026_05_rejects_legacy_surface_kind_scheduled() -> None:
    raw = _minimal_2026_05()
    raw["surfaces"] = [{"kind": "scheduled", "entrypoint": "/x"}]
    with pytest.raises(ManifestValidationError):
        parse(raw)


def test_2026_05_rejects_legacy_surface_kind_triggered() -> None:
    raw = _minimal_2026_05()
    raw["surfaces"] = [{"kind": "triggered", "entrypoint": "/x"}]
    with pytest.raises(ManifestValidationError):
        parse(raw)


def test_2026_05_accepts_full_page_card_drawer_mcp_tool_surfaces() -> None:
    raw = _minimal_2026_05()
    raw["surfaces"] = [
        {"kind": "ui", "entrypoint": "/"},
        {"kind": "chat", "entrypoint": "/chat"},
        {"kind": "full_page", "entrypoint": "/settings"},
        {"kind": "card", "entrypoint": "/embed/x"},
        {"kind": "drawer", "entrypoint": "/embed/y"},
        {"kind": "mcp_tool", "tool_schema": {"type": "object"}},
    ]
    parsed = parse(raw)
    assert isinstance(parsed.manifest, AppManifest2026_05)
    assert {s.kind for s in parsed.manifest.surfaces} == {
        "ui",
        "chat",
        "full_page",
        "card",
        "drawer",
        "mcp_tool",
    }


# ---------------------------------------------------------------------------
# Back-compat: older versions still parse.
# ---------------------------------------------------------------------------


def _minimal_2025_01() -> dict:
    return {
        "manifest_schema_version": "2025-01",
        "app": {
            "id": "com.example.legacy",
            "name": "Legacy App",
            "slug": "legacy",
            "version": "0.1.0",
        },
        "compatibility": {
            "studio": {"min": "3.2.0"},
            "manifest_schema": "2025-01",
            "runtime_api": "^1.0",
            "required_features": [],
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


def test_2025_01_manifest_still_parses_with_typed_mirror() -> None:
    parsed = parse(_minimal_2025_01())
    assert parsed.schema_version == "2025-01"
    # Legacy mirror is still applied for 2025-01 manifests.
    assert parsed.manifest is not None
    assert parsed.manifest.manifest_schema_version == "2025-01"


def test_unknown_schema_version_rejected() -> None:
    raw = _minimal_2026_05()
    raw["manifest_schema_version"] = "2099-01"
    with pytest.raises(ManifestValidationError) as exc_info:
        parse(raw)
    assert "unsupported manifest_schema_version" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Deep-copy safety.
# ---------------------------------------------------------------------------


def test_parse_does_not_mutate_input() -> None:
    raw = _full_2026_05()
    snapshot = deepcopy(raw)
    parse(raw)
    assert raw == snapshot
