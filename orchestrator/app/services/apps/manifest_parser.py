"""Manifest loader + validator.

Two layers of validation:
  1. Structural (JSON Schema) — hash-pinned, frozen at 2025-01.
  2. Typed (Pydantic) — ergonomic access for code paths that read a manifest.

Keep these two in lockstep. The schema file is authoritative; the Pydantic
model exists for editor support and typed access.
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
from pydantic import ValidationError as PydanticValidationError

from .app_manifest import MANIFEST_SCHEMA_VERSION, AppManifest

_SCHEMA_PATH = Path(__file__).parent / "app_manifest_2025_01.schema.json"
_SCHEMA_PATH_2025_02 = Path(__file__).parent / "app_manifest_2025_02.schema.json"

# Registry of supported schema files keyed by manifest_schema_version.
_SCHEMA_PATHS: dict[str, Path] = {
    "2025-01": _SCHEMA_PATH,
    "2025-02": _SCHEMA_PATH_2025_02,
}


class ManifestValidationError(ValueError):
    """Raised when a manifest document fails structural or typed validation."""

    def __init__(self, message: str, errors: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.errors: list[dict[str, Any]] = errors or []


@dataclass(frozen=True)
class ParsedManifest:
    # None when the manifest's declared schema_version is newer than the
    # Pydantic mirror (e.g. 2025-02). Consumers should fall back to `raw` for
    # fields not yet modeled in :class:`AppManifest`.
    manifest: AppManifest | None
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


_validator = Draft202012Validator(load_schema("2025-01"))
_validator_2025_02 = Draft202012Validator(load_schema("2025-02"))

_VALIDATORS: dict[str, Draft202012Validator] = {
    "2025-01": _validator,
    "2025-02": _validator_2025_02,
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
        raise ManifestValidationError(
            f"unsupported manifest_schema_version: {declared!r}"
        )

    validator = _VALIDATORS[declared]
    schema_errors = sorted(validator.iter_errors(raw), key=lambda e: list(e.absolute_path))
    if schema_errors:
        raise ManifestValidationError(
            "manifest failed schema validation",
            errors=[_jsonschema_err_to_dict(e) for e in schema_errors],
        )

    # Typed Pydantic mirror currently tracks 2025-01. Newer versions validate
    # structurally only until the mirror is bumped — raw dict remains canonical.
    manifest: AppManifest | None = None
    if declared == MANIFEST_SCHEMA_VERSION:
        try:
            manifest = AppManifest.model_validate(raw)
        except PydanticValidationError as e:
            raise ManifestValidationError(
                "manifest failed typed validation", errors=e.errors()
            ) from e

    canonical_hash = hashlib.sha256(_canonical_bytes(raw)).hexdigest()
    return ParsedManifest(
        manifest=manifest,  # type: ignore[arg-type]
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
