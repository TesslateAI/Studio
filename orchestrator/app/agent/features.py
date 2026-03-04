"""
Feature flags for Tesslate Agent.

All features are ENABLED by default. Disable via:
- Environment variables: TESSLATE_FEATURE_SUBAGENTS=0
- Per-agent config: MarketplaceAgent.config["features"]["subagents"] = false
"""

import os
from dataclasses import dataclass
from enum import Enum


class Feature(Enum):
    """Available feature flags."""

    STREAMING = "streaming"
    WEB_SEARCH = "web_search"
    PLAN_MODE = "plan_mode"
    SUBAGENTS = "subagents"
    APPLY_PATCH = "apply_patch"


@dataclass
class FeatureSpec:
    """Specification for a feature."""

    key: str
    default_enabled: bool


# Feature specifications - all enabled by default
FEATURES = {
    Feature.STREAMING: FeatureSpec("streaming", default_enabled=True),
    Feature.WEB_SEARCH: FeatureSpec("web_search", default_enabled=True),
    Feature.PLAN_MODE: FeatureSpec("plan_mode", default_enabled=True),
    Feature.SUBAGENTS: FeatureSpec("subagents", default_enabled=True),
    Feature.APPLY_PATCH: FeatureSpec("apply_patch", default_enabled=True),
}


class Features:
    """Feature flag container.

    All features are enabled by default. Use disable() or environment
    variables (TESSLATE_FEATURE_*=0) to turn them off.
    """

    def __init__(self, overrides: dict[Feature, bool] | None = None):
        """Initialize with all default-enabled features, then apply overrides."""
        self._enabled = {f for f, spec in FEATURES.items() if spec.default_enabled}
        if overrides:
            for feature, enabled in overrides.items():
                if enabled:
                    self._enabled.add(feature)
                else:
                    self._enabled.discard(feature)

    def enabled(self, feature: Feature) -> bool:
        """Check if a feature is enabled."""
        return feature in self._enabled

    def enable(self, feature: Feature) -> "Features":
        """Enable a feature. Returns self for chaining."""
        self._enabled.add(feature)
        return self

    def disable(self, feature: Feature) -> "Features":
        """Disable a feature. Returns self for chaining."""
        self._enabled.discard(feature)
        return self

    @classmethod
    def from_env(cls) -> "Features":
        """Load feature flags from environment variables.

        TESSLATE_FEATURE_STREAMING=0  -> disable streaming
        TESSLATE_FEATURE_WEB_SEARCH=0 -> disable web search
        TESSLATE_FEATURE_PLAN_MODE=0  -> disable plan mode
        TESSLATE_FEATURE_SUBAGENTS=0  -> disable subagents
        TESSLATE_FEATURE_APPLY_PATCH=0 -> disable apply_patch
        """
        f = cls()
        for feature, spec in FEATURES.items():
            env_key = f"TESSLATE_FEATURE_{spec.key.upper()}"
            if os.environ.get(env_key) == "0":
                f.disable(feature)
        return f

    @classmethod
    def from_config(cls, config: dict | None = None) -> "Features":
        """Build Features from agent config dict (from MarketplaceAgent.config).

        Config format: {"features": {"subagents": false, "apply_patch": true, ...}}
        Starts from env-based defaults, then applies config overrides.
        """
        f = cls.from_env()
        if not config:
            return f

        features_dict = config.get("features")
        if not features_dict or not isinstance(features_dict, dict):
            return f

        # Map string keys to Feature enum
        key_to_feature = {spec.key: feature for feature, spec in FEATURES.items()}

        for key, enabled in features_dict.items():
            feature = key_to_feature.get(key)
            if feature is not None:
                if enabled:
                    f.enable(feature)
                else:
                    f.disable(feature)

        return f

    def to_dict(self) -> dict[str, bool]:
        """Serialize to dict for API responses."""
        return {spec.key: self.enabled(feature) for feature, spec in FEATURES.items()}

    def __repr__(self) -> str:
        enabled_names = [f.value for f in self._enabled]
        return f"Features(enabled={enabled_names})"
