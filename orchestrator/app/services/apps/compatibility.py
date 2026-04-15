"""Pure compatibility check for an AppVersion against the current Studio.

No DB access. No I/O. Wraps `app.config_features` with a typed result object
that publisher + installer + the external API can share.
"""

from __future__ import annotations

from dataclasses import dataclass

from ... import config_features

__all__ = ["CompatReport", "check"]


@dataclass(frozen=True)
class CompatReport:
    compatible: bool
    missing_features: list[str]
    unsupported_manifest_schema: bool
    upgrade_required: bool  # reserved for Wave 3 "planned" feature state
    server_manifest_schemas: list[str]
    server_feature_set_hash: str


def check(
    *,
    required_features: list[str],
    manifest_schema: str,
) -> CompatReport:
    """Compare a manifest's declared needs against this deployment."""
    missing = config_features.diff(list(required_features))
    schemas = config_features.manifest_schema_supported()
    unsupported = manifest_schema not in schemas
    return CompatReport(
        compatible=not missing and not unsupported,
        missing_features=missing,
        unsupported_manifest_schema=unsupported,
        upgrade_required=False,
        server_manifest_schemas=schemas,
        server_feature_set_hash=config_features.feature_set_hash(),
    )
