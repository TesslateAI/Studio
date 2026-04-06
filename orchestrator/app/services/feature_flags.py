"""
Feature flag service.

Loads feature flags from YAML files with per-environment overrides.
Flags are defined in orchestrator/feature_flags/:
  - defaults.yaml   — canonical schema; every flag must be here
  - {env}.yaml       — per-environment overrides (minikube, beta, production, ...)

Usage:
    from app.services.feature_flags import get_feature_flags

    ff = get_feature_flags()
    if ff.enabled("two_fa"):
        ...

    # Frontend-visible flags only
    ff.public_flags  # {"two_fa": False, "template_builder": True}
"""

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Resolve the feature_flags/ directory relative to this file.
# Layout: orchestrator/app/services/feature_flags.py -> orchestrator/feature_flags/
_FLAGS_DIR = Path(__file__).resolve().parent.parent.parent / "feature_flags"


class FeatureFlagError(Exception):
    """Raised when flag configuration is invalid."""


class FeatureFlags:
    """Immutable container of resolved feature flags."""

    def __init__(self, flags: dict[str, bool], public_keys: list[str], env: str) -> None:
        self._flags = dict(flags)
        self._public_keys = list(public_keys)
        self._env = env

    @property
    def env(self) -> str:
        return self._env

    @property
    def flags(self) -> dict[str, bool]:
        """Return a copy of all resolved flags (backend use)."""
        return dict(self._flags)

    @property
    def public_flags(self) -> dict[str, bool]:
        """Return only flags marked as public (for the API / frontend)."""
        return {k: self._flags[k] for k in self._public_keys if k in self._flags}

    def enabled(self, flag: str) -> bool:
        """Check if a flag is enabled. Raises KeyError for unknown flags."""
        if flag not in self._flags:
            raise KeyError(
                f"Unknown feature flag '{flag}'. Available flags: {sorted(self._flags.keys())}"
            )
        return self._flags[flag]

    def __repr__(self) -> str:
        enabled = [k for k, v in sorted(self._flags.items()) if v]
        return f"FeatureFlags(env={self._env!r}, enabled={enabled})"


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file and return its contents as a dict."""
    with open(path) as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


def _validate_flags(
    defaults: dict[str, bool], overrides: dict[str, Any], env_name: str
) -> dict[str, bool]:
    """Validate and merge overrides into defaults.

    Rules:
    - Override keys must exist in defaults (unknown keys rejected)
    - All values must be boolean
    """
    unknown = set(overrides.keys()) - set(defaults.keys())
    if unknown:
        raise FeatureFlagError(
            f"Unknown feature flag(s) in {env_name}.yaml: {sorted(unknown)}. "
            f"All flags must be defined in defaults.yaml first."
        )

    merged = dict(defaults)
    for key, value in overrides.items():
        if not isinstance(value, bool):
            raise FeatureFlagError(
                f"Feature flag '{key}' in {env_name}.yaml must be boolean, "
                f"got {type(value).__name__}: {value!r}"
            )
        merged[key] = value

    return merged


def _parse_defaults(raw: dict[str, Any]) -> tuple[dict[str, bool], list[str]]:
    """Separate flag definitions from the public list.

    Returns (flags_dict, public_keys).
    """
    public_keys: list[str] = []
    flags: dict[str, bool] = {}

    for key, value in raw.items():
        if key == "public":
            if not isinstance(value, list):
                raise FeatureFlagError(
                    f"'public' in defaults.yaml must be a list, got {type(value).__name__}"
                )
            public_keys = value
            continue
        if not isinstance(value, bool):
            raise FeatureFlagError(
                f"Feature flag '{key}' in defaults.yaml must be boolean, "
                f"got {type(value).__name__}: {value!r}"
            )
        flags[key] = value

    # Validate that every public key references an actual flag
    unknown_public = set(public_keys) - set(flags.keys())
    if unknown_public:
        raise FeatureFlagError(
            f"Public list references unknown flag(s): {sorted(unknown_public)}. "
            f"Each entry must match a flag defined in defaults.yaml."
        )

    return flags, public_keys


def load_feature_flags(env: str) -> FeatureFlags:
    """Load and resolve feature flags for the given environment.

    1. Read defaults.yaml (required — defines the schema + public list)
    2. Read {env}.yaml if it exists (optional overrides)
    3. Validate: no unknown keys, all values boolean
    4. Return frozen FeatureFlags instance
    """
    defaults_path = _FLAGS_DIR / "defaults.yaml"
    if not defaults_path.exists():
        raise FeatureFlagError(f"defaults.yaml not found at {defaults_path}")

    raw = _load_yaml(defaults_path)
    defaults, public_keys = _parse_defaults(raw)

    # Load env-specific overrides
    env_path = _FLAGS_DIR / f"{env}.yaml"
    if env_path.exists():
        overrides = _load_yaml(env_path)
        merged = _validate_flags(defaults, overrides, env)
        logger.info("Feature flags loaded: env=%s, overrides=%s", env, sorted(overrides.keys()))
    else:
        merged = dict(defaults)
        logger.warning("Feature flags loaded: env=%s (no overrides file)", env)

    return FeatureFlags(merged, public_keys, env)


@lru_cache
def get_feature_flags() -> FeatureFlags:
    """Cached singleton — loads flags once at startup."""
    from ..config import get_settings

    settings = get_settings()
    return load_feature_flags(settings.deployment_env)
