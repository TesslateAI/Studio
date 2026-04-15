"""Tests for the manifest parser + validator."""

from __future__ import annotations

from copy import deepcopy

import pytest

from app.services.apps.manifest_parser import ManifestValidationError, parse


def _minimal() -> dict:
    return {
        "manifest_schema_version": "2025-01",
        "app": {
            "id": "com.example.hello-app",
            "name": "Hello App",
            "slug": "hello-app",
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


def test_parse_minimal_manifest_roundtrip() -> None:
    parsed = parse(_minimal())
    assert parsed.manifest.manifest_schema_version == "2025-01"
    assert parsed.manifest.app.slug == "hello-app"
    assert parsed.manifest.state.model == "stateless"
    assert parsed.manifest.billing.platform_fee.model == "free"
    assert len(parsed.canonical_hash) == 64


def test_canonical_hash_is_stable_across_key_order() -> None:
    a = _minimal()
    b = {k: a[k] for k in reversed(list(a.keys()))}
    assert parse(a).canonical_hash == parse(b).canonical_hash


def test_parse_accepts_yaml_string() -> None:
    yaml_text = """
manifest_schema_version: "2025-01"
app:
  id: com.example.hello-app
  name: Hello App
  slug: hello-app
  version: 0.1.0
compatibility:
  studio: { min: "3.2.0" }
  manifest_schema: "2025-01"
  runtime_api: "^1.0"
  required_features: []
surfaces:
  - { kind: ui, entrypoint: index.html }
state: { model: stateless }
billing:
  ai_compute: { payer: installer }
  general_compute: { payer: installer }
  platform_fee: { model: free, price_usd: 0 }
listing: { visibility: public }
"""
    parsed = parse(yaml_text)
    assert parsed.manifest.app.slug == "hello-app"


def test_missing_required_top_level_field_rejected() -> None:
    raw = _minimal()
    del raw["surfaces"]
    with pytest.raises(ManifestValidationError) as exc:
        parse(raw)
    paths = [tuple(e["path"]) for e in exc.value.errors]
    assert () in paths or any("surfaces" in " ".join(str(p) for p in path) for path in paths)


def test_wrong_manifest_schema_version_rejected() -> None:
    raw = _minimal()
    raw["manifest_schema_version"] = "2025-12"
    with pytest.raises(ManifestValidationError):
        parse(raw)


def test_invalid_surface_kind_rejected() -> None:
    raw = _minimal()
    raw["surfaces"] = [{"kind": "smtp", "entrypoint": "index.html"}]
    with pytest.raises(ManifestValidationError):
        parse(raw)


def test_invalid_state_model_rejected() -> None:
    raw = _minimal()
    raw["state"] = {"model": "clustered"}
    with pytest.raises(ManifestValidationError):
        parse(raw)


def test_byok_payer_allowed_on_ai_compute() -> None:
    raw = _minimal()
    raw["billing"]["ai_compute"]["payer"] = "byok"
    parsed = parse(raw)
    assert parsed.manifest.billing.ai_compute.payer == "byok"


def test_semver_pattern_enforced_on_app_version() -> None:
    raw = _minimal()
    raw["app"]["version"] = "v1.0"
    with pytest.raises(ManifestValidationError):
        parse(raw)


def test_slug_pattern_enforced() -> None:
    raw = _minimal()
    raw["app"]["slug"] = "Hello App"
    with pytest.raises(ManifestValidationError):
        parse(raw)


def test_hosted_agent_block_roundtrips() -> None:
    raw = _minimal()
    raw["compute"] = {
        "tier": 1,
        "hosted_agents": [
            {
                "id": "primary",
                "system_prompt_ref": "prompts/primary.md",
                "model_pref": "claude-sonnet-4-6",
                "tools_ref": ["tools/redline"],
                "mcps_ref": ["gmail"],
            }
        ],
    }
    parsed = parse(raw)
    assert parsed.manifest.compute.hosted_agents[0].id == "primary"
    assert parsed.manifest.compute.hosted_agents[0].system_prompt_ref == "prompts/primary.md"


def test_mcp_tool_surface_accepts_tool_schema() -> None:
    raw = _minimal()
    raw["surfaces"].append(
        {
            "kind": "mcp-tool",
            "entrypoint": "tools/redline",
            "tool_schema": {"type": "object", "properties": {"x": {"type": "string"}}},
        }
    )
    parsed = parse(raw)
    assert any(s.kind == "mcp-tool" for s in parsed.manifest.surfaces)


def test_listing_visibility_team_uuid_accepted() -> None:
    raw = _minimal()
    raw["listing"]["visibility"] = "team:00000000-0000-0000-0000-000000000000"
    parsed = parse(raw)
    assert parsed.manifest.listing.visibility.startswith("team:")


def test_listing_visibility_invalid_rejected() -> None:
    raw = _minimal()
    raw["listing"]["visibility"] = "internal-only"
    with pytest.raises(ManifestValidationError):
        parse(raw)


def test_additional_top_level_property_rejected() -> None:
    raw = _minimal()
    raw["unexpected_top_level"] = {}
    with pytest.raises(ManifestValidationError):
        parse(raw)


def test_non_dict_root_rejected() -> None:
    with pytest.raises(ManifestValidationError):
        parse("- just a list")


def test_parse_accepts_bytes() -> None:
    import json as _json

    raw_bytes = _json.dumps(_minimal()).encode("utf-8")
    parsed = parse(raw_bytes)
    assert parsed.manifest.app.id == "com.example.hello-app"


def test_migration_alias_from_to_roundtrips() -> None:
    raw = _minimal()
    raw["migrations"] = [{"from": "0.1.0", "to": "0.2.0", "auto_safe": True}]
    parsed = parse(raw)
    assert parsed.manifest.migrations[0].from_ == "0.1.0"
    assert parsed.manifest.migrations[0].to == "0.2.0"


def test_deep_copy_safety() -> None:
    raw = _minimal()
    snapshot = deepcopy(raw)
    parse(raw)
    assert raw == snapshot, "parse must not mutate its input"
