"""Unit tests for ``app.services.node_config_presets``.

Covers preset registry shape, uniqueness of field keys, and override merging
semantics for ``resolve_schema``.
"""
from __future__ import annotations

import pytest

from app.services.node_config_presets import (
    PRESETS,
    FieldSchema,
    FormSchema,
    Preset,
    resolve_schema,
)


# ---------------------------------------------------------------------------
# Preset registry
# ---------------------------------------------------------------------------


EXPECTED_PRESETS = ["supabase", "postgres", "stripe", "rest_api", "external_generic"]


@pytest.mark.parametrize("preset_key", EXPECTED_PRESETS)
def test_every_registered_preset_is_structurally_valid(preset_key: str) -> None:
    preset = PRESETS[preset_key]
    assert isinstance(preset, Preset)
    assert preset.key == preset_key
    assert preset.display_name
    assert preset.icon
    assert preset.deployment_mode in ("external", "container")
    assert isinstance(preset.fields, list)
    # Every field has required attributes
    for field in preset.fields:
        assert isinstance(field, FieldSchema)
        assert field.key
        assert field.label
        assert field.type in ("text", "url", "secret", "select", "number", "textarea")


@pytest.mark.parametrize("preset_key", EXPECTED_PRESETS)
def test_preset_field_keys_are_unique(preset_key: str) -> None:
    preset = PRESETS[preset_key]
    keys = [f.key for f in preset.fields]
    assert len(keys) == len(set(keys)), f"duplicate keys in preset {preset_key}: {keys}"


# ---------------------------------------------------------------------------
# resolve_schema
# ---------------------------------------------------------------------------


def test_resolve_supabase_without_overrides_matches_preset() -> None:
    schema = resolve_schema("supabase", None)
    assert isinstance(schema, FormSchema)
    assert schema.preset == "supabase"
    keys = [f.key for f in schema.fields]
    assert keys == ["SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_KEY"]
    # Secret classification preserved
    assert schema.secret_keys() == {"SUPABASE_ANON_KEY", "SUPABASE_SERVICE_KEY"}


def test_resolve_supabase_appends_new_override_field() -> None:
    schema = resolve_schema(
        "supabase",
        [{"key": "EXTRA", "label": "Extra", "type": "text"}],
    )
    keys = [f.key for f in schema.fields]
    assert keys == [
        "SUPABASE_URL",
        "SUPABASE_ANON_KEY",
        "SUPABASE_SERVICE_KEY",
        "EXTRA",
    ]
    extra = next(f for f in schema.fields if f.key == "EXTRA")
    assert extra.type == "text"
    assert extra.is_secret is False


def test_resolve_supabase_override_replaces_existing_field_in_place() -> None:
    schema = resolve_schema(
        "supabase",
        [
            {
                "key": "SUPABASE_URL",
                "label": "Custom URL",
                "type": "url",
                "required": False,
                "is_secret": False,
            }
        ],
    )
    keys = [f.key for f in schema.fields]
    # Order preserved (SUPABASE_URL stays at index 0)
    assert keys == ["SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_KEY"]
    url_field = schema.fields[0]
    assert url_field.label == "Custom URL"
    assert url_field.required is False
    assert url_field.is_secret is False


def test_resolve_schema_unknown_preset_raises_key_error() -> None:
    with pytest.raises(KeyError):
        resolve_schema("does_not_exist", None)


def test_external_generic_has_no_default_fields() -> None:
    preset = PRESETS["external_generic"]
    assert preset.fields == []

    schema = resolve_schema(
        "external_generic",
        [
            {"key": "API_URL", "label": "API URL", "type": "url", "required": True},
            {
                "key": "API_TOKEN",
                "label": "API Token",
                "type": "secret",
                "is_secret": True,
            },
        ],
    )
    keys = [f.key for f in schema.fields]
    assert keys == ["API_URL", "API_TOKEN"]
    assert schema.secret_keys() == {"API_TOKEN"}


def test_override_type_secret_auto_marks_is_secret() -> None:
    # Per _field_from_override: type=secret always implies is_secret
    schema = resolve_schema(
        "external_generic",
        [{"key": "FOO", "label": "Foo", "type": "secret"}],
    )
    assert schema.fields[0].is_secret is True


def test_override_missing_required_fields_raises_value_error() -> None:
    with pytest.raises(ValueError):
        resolve_schema("supabase", [{"key": "X"}])


def test_form_schema_to_dict_strips_none_and_keeps_shape() -> None:
    schema = resolve_schema("supabase")
    out = schema.to_dict()
    assert out["preset"] == "supabase"
    assert out["deployment_mode"] == "external"
    assert isinstance(out["fields"], list)
    first = out["fields"][0]
    # Compact JSON: no None-valued keys
    assert None not in first.values()
