"""Unit tests for app.services.apps.env_resolver.resolve_env_for_pod."""

from __future__ import annotations

from app.services.apps.env_resolver import resolve_env_for_pod


def test_empty_and_none_returns_empty_list() -> None:
    assert resolve_env_for_pod({}) == []
    assert resolve_env_for_pod(None) == []


def test_plain_value_becomes_value_envvar() -> None:
    out = resolve_env_for_pod({"FOO": "bar"})
    assert len(out) == 1
    ev = out[0]
    assert ev.name == "FOO"
    assert ev.value == "bar"
    assert ev.value_from is None


def test_non_string_values_are_coerced() -> None:
    out = resolve_env_for_pod({"PORT": 3000})
    assert out[0].value == "3000"


def test_none_value_becomes_empty_string_not_error() -> None:
    out = resolve_env_for_pod({"MAYBE": None})
    assert out[0].value == ""
    assert out[0].value_from is None


def test_secret_ref_becomes_secret_key_ref() -> None:
    out = resolve_env_for_pod({"API_KEY": "${secret:llama-api-credentials/api_key}"})
    assert len(out) == 1
    ev = out[0]
    assert ev.name == "API_KEY"
    assert ev.value is None
    assert ev.value_from is not None
    assert ev.value_from.secret_key_ref.name == "llama-api-credentials"
    assert ev.value_from.secret_key_ref.key == "api_key"


def test_partial_secret_ref_is_literal() -> None:
    # Not the full-string shape — treat as literal.
    out = resolve_env_for_pod({"X": "prefix-${secret:a/b}"})
    assert out[0].value == "prefix-${secret:a/b}"
    assert out[0].value_from is None


def test_mixed_dict_preserves_both_shapes() -> None:
    out = resolve_env_for_pod(
        {
            "FOO": "bar",
            "KEY": "${secret:s/k}",
        }
    )
    assert len(out) == 2
    by_name = {e.name: e for e in out}
    assert by_name["FOO"].value == "bar"
    assert by_name["FOO"].value_from is None
    assert by_name["KEY"].value_from.secret_key_ref.name == "s"
    assert by_name["KEY"].value_from.secret_key_ref.key == "k"


def test_secret_ref_with_slashes_in_key_not_supported() -> None:
    # Intentional: regex disallows '/' inside the name, and the key runs
    # to the first '}'. Embedded slashes in the key are allowed.
    out = resolve_env_for_pod({"K": "${secret:ns/a/b}"})
    # regex: ([^/}]+)/([^}]+) → name='ns', key='a/b'
    ev = out[0]
    assert ev.value_from.secret_key_ref.name == "ns"
    assert ev.value_from.secret_key_ref.key == "a/b"
