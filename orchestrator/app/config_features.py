"""Feature flag registry for the Tesslate Apps primitive.

Single source of truth consumed by:
  - GET /api/version (advertises what this deployment supports)
  - Manifest publish-time compatibility check (rejects required_features
    that aren't present here)

All Apps-related flags default OFF. Flip by passing env vars of the form
`TSL_FEATURE_<FLAG>=true` at deployment time, or edit the _DEFAULTS map for
defaults that should bake into every deployment.

Flag naming: `apps.<area>.<action>` — dots are preserved in the manifest
`compatibility.required_features[]` list.

Non-Apps features (other subsystems) may land here later; for now the
registry is Apps-only and the "features" advertised at /api/version is the
union of enabled flags plus always-on platform capabilities listed in
_ALWAYS_ON.
"""

from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from typing import Literal

SchemaVersion = Literal["2025-01", "2025-02", "2026-05"]

# 2026-05 is the canonical post-Phase-1 manifest. Older versions stay
# accepted so old AppVersion rows don't suddenly fail compatibility
# (we don't republish historical bundles).
MANIFEST_SCHEMA_SUPPORTED: list[SchemaVersion] = ["2025-01", "2025-02", "2026-05"]
RUNTIME_API_SUPPORTED: list[str] = ["1.0"]


# Apps feature flags — default OFF. See docs/proposed/plans/tesslate-apps.md §10.
_DEFAULTS: dict[str, bool] = {
    "apps.manifest_schema_v1": False,
    "apps.publish": False,
    "apps.install": False,
    "apps.runtime.ui": False,
    "apps.runtime.chat": False,
    "apps.runtime.scheduled": False,
    "apps.runtime.triggered": False,
    "apps.runtime.mcp_tool": False,
    "apps.hosted_agent": False,
    "apps.source_view": False,
    "apps.fork": False,
    "apps.bundles": False,
    "apps.review.stage1": False,
    "apps.review.stage2": False,
    "apps.review.stage3": False,
    "apps.yank": False,
    "apps.yank.critical_two_admin": True,  # governance policy — keep ON
    "apps.billing.dispatcher": False,
    "apps.billing.revenue_split": False,
    "apps.triggers.webhook": False,
    "apps.triggers.mcp_event": False,
    "apps.triggers.app_invocation": False,
    "apps.canvas.hosted_agent_node": False,
    "apps.embedding.postmessage": False,
}

# Platform capabilities that are ALWAYS available (infrastructure is live today).
# These are safe to assume in manifest `compatibility.required_features[]`.
_ALWAYS_ON: frozenset[str] = frozenset(
    {
        "cas_bundle",         # services/btrfs-csi/pkg/cas/store.go
        "volume_fork",        # volumehub ForkVolume
        "volume_snapshot",    # volumehub CreateSnapshot / RestoreToSnapshot
        "manifest_schema_2025_02",  # parser accepts both 2025-01 and 2025-02
    }
)


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_flags() -> dict[str, bool]:
    resolved: dict[str, bool] = {}
    for flag, default in _DEFAULTS.items():
        env_key = "TSL_FEATURE_" + flag.replace(".", "_").upper()
        resolved[flag] = _env_bool(env_key, default)
    return resolved


def is_enabled(flag: str) -> bool:
    return _resolve_flags().get(flag, False)


def current_feature_set() -> list[str]:
    """Return the sorted list of enabled feature flags + always-on capabilities."""
    enabled = {name for name, val in _resolve_flags().items() if val}
    return sorted(enabled | _ALWAYS_ON)


@lru_cache(maxsize=1)
def _ALWAYS_ON_list() -> list[str]:
    return sorted(_ALWAYS_ON)


def feature_set_hash() -> str:
    """Deterministic hash of the current feature set.

    Used to detect deployment drift on install-time compat checks and to key
    config snapshots on AppVersion records.
    """
    blob = json.dumps(current_feature_set(), sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def diff(required: list[str]) -> list[str]:
    """Return features listed in `required` that are NOT available in this
    deployment. Empty list means compatible.
    """
    available = set(current_feature_set())
    return [f for f in required if f not in available]


def manifest_schema_supported() -> list[str]:
    return list(MANIFEST_SCHEMA_SUPPORTED)


def runtime_api_supported() -> list[str]:
    return list(RUNTIME_API_SUPPORTED)


def build_sha() -> str:
    """Deployment build identifier. `BUILD_SHA` env var injected by CI;
    otherwise "dev"."""
    return os.environ.get("BUILD_SHA", "dev")
