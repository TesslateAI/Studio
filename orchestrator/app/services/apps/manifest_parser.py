"""Manifest loader + validator.

Two layers of validation:
  1. Structural (JSON Schema) — hash-pinned per dated schema file.
  2. Typed (Pydantic) — ergonomic access for code paths that read a manifest.

Keep these two in lockstep. Each schema file is authoritative; the Pydantic
models exist for editor support and typed access.

Supported schema versions:
  * 2025-01 — original frozen schema. Typed mirror: :class:`AppManifest`.
  * 2025-02 — wave 9 additions (primary container, connections, schedules).
              Validated structurally only — code paths that need new fields
              read from the raw dict.
  * 2026-05 — App Runtime Contract. Typed mirror: :class:`AppManifest2026_05`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel, ValidationError as PydanticValidationError

from .app_manifest import (
    MANIFEST_SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
    AppManifest,
    AppManifest2026_05,
)
from .template_render import RenderError, get_render_client

_SCHEMA_PATH = Path(__file__).parent / "app_manifest_2025_01.schema.json"
_SCHEMA_PATH_2025_02 = Path(__file__).parent / "app_manifest_2025_02.schema.json"
_SCHEMA_PATH_2026_05 = Path(__file__).parent / "app_manifest_2026_05.schema.json"

# Registry of supported schema files keyed by manifest_schema_version.
_SCHEMA_PATHS: dict[str, Path] = {
    "2025-01": _SCHEMA_PATH,
    "2025-02": _SCHEMA_PATH_2025_02,
    "2026-05": _SCHEMA_PATH_2026_05,
}


class ManifestValidationError(ValueError):
    """Raised when a manifest document fails structural or typed validation."""

    def __init__(self, message: str, errors: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.errors: list[dict[str, Any]] = errors or []


@dataclass(frozen=True)
class ParsedManifest:
    # Typed Pydantic model for the parsed manifest. Always populated for
    # supported versions: AppManifest for 2025-01, AppManifest2026_05 for
    # 2026-05. None for 2025-02 (still validated structurally — the legacy
    # mirror does not cover the new container/connection/schedule fields).
    manifest: AppManifest | AppManifest2026_05 | None
    raw: dict[str, Any]
    canonical_hash: str
    schema_version: str


def load_schema(version: str = "2025-01") -> dict[str, Any]:
    path = _SCHEMA_PATHS.get(version, _SCHEMA_PATH)
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def schema_hash(version: str = "2025-01") -> str:
    """SHA256 of a frozen schema file bytes. Used by the hash-pin tests."""
    path = _SCHEMA_PATHS.get(version, _SCHEMA_PATH)
    return hashlib.sha256(path.read_bytes()).hexdigest()


# All three schemas declare draft-2020-12 in their $schema field; use the
# matching validator for each.
_validator = Draft202012Validator(load_schema("2025-01"))
_validator_2025_02 = Draft202012Validator(load_schema("2025-02"))
_validator_2026_05 = Draft202012Validator(load_schema("2026-05"))

_VALIDATORS: dict[str, Any] = {
    "2025-01": _validator,
    "2025-02": _validator_2025_02,
    "2026-05": _validator_2026_05,
}

# Map of schema version -> typed Pydantic model. Versions absent from this
# map fall through to structural-only validation (raw dict is canonical).
_TYPED_MIRRORS: dict[str, type[BaseModel]] = {
    "2025-01": AppManifest,
    "2026-05": AppManifest2026_05,
}


def _canonical_bytes(raw: dict[str, Any]) -> bytes:
    return json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8")


def parse(source: str | bytes | dict[str, Any]) -> ParsedManifest:
    """Parse manifest yaml/json/dict → validated ParsedManifest.

    Raises ManifestValidationError with a structured error list on failure.
    """
    raw = _coerce_to_dict(source)

    declared = raw.get("manifest_schema_version")
    if declared not in _VALIDATORS:
        supported = ", ".join(SUPPORTED_SCHEMA_VERSIONS)
        raise ManifestValidationError(
            f"unsupported manifest_schema_version: {declared!r} "
            f"(supported: {supported})"
        )

    validator = _VALIDATORS[declared]
    schema_errors = sorted(validator.iter_errors(raw), key=lambda e: list(e.absolute_path))
    if schema_errors:
        raise ManifestValidationError(
            "manifest failed schema validation",
            errors=[_jsonschema_err_to_dict(e) for e in schema_errors],
        )

    # Typed Pydantic mirror is applied when one is registered for this version.
    # 2025-02 is still structural-only; consumers fall back to `raw`.
    manifest: AppManifest | AppManifest2026_05 | None = None
    typed_model = _TYPED_MIRRORS.get(declared)
    if typed_model is not None:
        try:
            manifest = typed_model.model_validate(raw)
        except PydanticValidationError as e:
            raise ManifestValidationError(
                "manifest failed typed validation", errors=e.errors()
            ) from e

    canonical_hash = hashlib.sha256(_canonical_bytes(raw)).hexdigest()
    return ParsedManifest(
        manifest=manifest,
        raw=raw,
        canonical_hash=canonical_hash,
        schema_version=declared,
    )


def _coerce_to_dict(source: str | bytes | dict[str, Any]) -> dict[str, Any]:
    if isinstance(source, dict):
        return source
    if isinstance(source, bytes):
        source = source.decode("utf-8")
    # YAML is a superset of JSON; yaml.safe_load handles both.
    data = yaml.safe_load(source)
    if not isinstance(data, dict):
        raise ManifestValidationError(
            f"manifest root must be an object, got {type(data).__name__}"
        )
    return data


def _jsonschema_err_to_dict(e: JsonSchemaValidationError) -> dict[str, Any]:
    return {
        "path": list(e.absolute_path),
        "message": e.message,
        "validator": e.validator,
        "validator_value": e.validator_value,
    }


# ---------------------------------------------------------------------------
# Install-time `result_template` dry-render validation.
#
# Plan §"result_template — sandboxed Jinja, subprocess-rendered, output
# capped" calls for rejecting manifests at publish/install time when any
# `actions[].result_template` has a syntax error, runaway sentinel, or
# exceeds the 4 KB body limit. We dry-render with empty `{input: {}, output:
# {}}` against the long-lived render worker — same code path the runtime
# delivery hop uses, so behavior is consistent.
# ---------------------------------------------------------------------------


# Strict timeout for install-time validation. The render worker itself caps
# at DEFAULT_RENDER_TIMEOUT_SECONDS, but the validator uses a tighter ceiling
# so a runaway template can't park the publish flow.
_DRY_RENDER_TIMEOUT_SECONDS = 2.0


def _iter_result_templates(raw: dict[str, Any]) -> list[tuple[str, str]]:
    """Yield ``(action_name, template)`` pairs from a parsed manifest.

    Returns an empty list for schemas that don't declare result templates
    (currently 2025-01 / 2025-02), so the validator is a no-op there.
    """
    out: list[tuple[str, str]] = []
    for action in raw.get("actions") or []:
        if not isinstance(action, dict):
            continue
        template = action.get("result_template")
        name = action.get("name") or "<unnamed>"
        if isinstance(template, str) and template.strip():
            out.append((str(name), template))
    return out


async def validate_result_templates(parsed: ParsedManifest) -> None:
    """Dry-render every ``actions[].result_template`` declared in the manifest.

    Raises :class:`ManifestValidationError` aggregating every template
    that fails to compile / render / fits-in-cap. Uses the long-lived
    render worker so install-time validation exercises the exact same
    sandbox the runtime uses.

    Empty / absent templates are skipped — they're a valid manifest
    pattern (``result_template`` is optional and defaults to
    ``{{ output | tojson }}`` at delivery time).
    """
    pairs = _iter_result_templates(parsed.raw)
    if not pairs:
        return

    client = get_render_client()
    errors: list[dict[str, Any]] = []
    for action_name, template in pairs:
        try:
            await client.render(
                template,
                {"input": {}, "output": {}},
                timeout=_DRY_RENDER_TIMEOUT_SECONDS,
            )
        except RenderError as exc:
            errors.append(
                {
                    "path": ["actions", action_name, "result_template"],
                    "message": str(exc),
                    "validator": "result_template_dry_render",
                    "validator_value": None,
                }
            )

    if errors:
        raise ManifestValidationError(
            "manifest result_template dry-render failed",
            errors=errors,
        )


# Re-export for back-compat — older code may import MANIFEST_SCHEMA_VERSION
# from manifest_parser.
__all__ = [
    "MANIFEST_SCHEMA_VERSION",
    "SUPPORTED_SCHEMA_VERSIONS",
    "ManifestValidationError",
    "ParsedManifest",
    "load_schema",
    "schema_hash",
    "parse",
    "validate_result_templates",
]
