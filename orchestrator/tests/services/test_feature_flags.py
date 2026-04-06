"""
Unit tests for the feature flag service.

Tests YAML loading, defaults, per-env overrides, public/private separation,
validation, and the FeatureFlags container class.
"""

import textwrap
from pathlib import Path

import pytest
import yaml

from app.services.feature_flags import (
    FeatureFlagError,
    FeatureFlags,
    _load_yaml,
    _parse_defaults,
    _validate_flags,
    load_feature_flags,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_yaml(path: Path, content: dict | str) -> None:
    """Write a YAML file from dict or raw string."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        path.write_text(textwrap.dedent(content))
    else:
        path.write_text(yaml.dump(content))


def _make_flags_dir(tmp_path: Path, defaults: dict, envs: dict[str, dict] | None = None) -> Path:
    """Create a feature_flags directory with defaults and optional env overrides."""
    flags_dir = tmp_path / "feature_flags"
    flags_dir.mkdir()
    _write_yaml(flags_dir / "defaults.yaml", defaults)
    if envs:
        for env_name, overrides in envs.items():
            _write_yaml(flags_dir / f"{env_name}.yaml", overrides)
    return flags_dir


# ===========================================================================
# FeatureFlags container
# ===========================================================================


@pytest.mark.unit
class TestFeatureFlags:
    """Tests for the FeatureFlags immutable container."""

    def test_enabled_returns_correct_value(self):
        ff = FeatureFlags({"alpha": True, "beta": False}, public_keys=[], env="test")
        assert ff.enabled("alpha") is True
        assert ff.enabled("beta") is False

    def test_enabled_raises_on_unknown_flag(self):
        ff = FeatureFlags({"alpha": True}, public_keys=[], env="test")
        with pytest.raises(KeyError, match="Unknown feature flag 'nope'"):
            ff.enabled("nope")

    def test_flags_returns_all(self):
        ff = FeatureFlags({"a": True, "b": False, "c": True}, public_keys=["a"], env="test")
        assert ff.flags == {"a": True, "b": False, "c": True}

    def test_flags_returns_copy(self):
        original = {"a": True, "b": False}
        ff = FeatureFlags(original, public_keys=[], env="test")
        copy = ff.flags
        copy["a"] = False  # mutate the copy
        assert ff.enabled("a") is True  # original unaffected

    def test_public_flags_returns_only_public(self):
        ff = FeatureFlags(
            {"a": True, "b": False, "c": True},
            public_keys=["a", "b"],
            env="test",
        )
        assert ff.public_flags == {"a": True, "b": False}

    def test_public_flags_excludes_backend_only(self):
        ff = FeatureFlags(
            {"frontend_flag": True, "backend_flag": False},
            public_keys=["frontend_flag"],
            env="test",
        )
        assert "backend_flag" not in ff.public_flags
        assert "frontend_flag" in ff.public_flags

    def test_env_property(self):
        ff = FeatureFlags({}, public_keys=[], env="staging")
        assert ff.env == "staging"

    def test_repr(self):
        ff = FeatureFlags({"x": True, "y": False, "z": True}, public_keys=[], env="dev")
        r = repr(ff)
        assert "dev" in r
        assert "x" in r
        assert "z" in r
        assert "y" not in r  # disabled flags not in enabled list


# ===========================================================================
# _parse_defaults
# ===========================================================================


@pytest.mark.unit
class TestParseDefaults:
    """Tests for parsing defaults.yaml including the public list."""

    def test_separates_flags_and_public(self):
        raw = {"a": True, "b": False, "public": ["a"]}
        flags, public = _parse_defaults(raw)
        assert flags == {"a": True, "b": False}
        assert public == ["a"]

    def test_no_public_key_returns_empty_list(self):
        raw = {"a": True, "b": False}
        flags, public = _parse_defaults(raw)
        assert flags == {"a": True, "b": False}
        assert public == []

    def test_public_referencing_unknown_flag_raises(self):
        raw = {"a": True, "public": ["a", "nonexistent"]}
        with pytest.raises(FeatureFlagError, match="unknown flag.*nonexistent"):
            _parse_defaults(raw)

    def test_public_not_a_list_raises(self):
        raw = {"a": True, "public": "a"}
        with pytest.raises(FeatureFlagError, match="must be a list"):
            _parse_defaults(raw)

    def test_non_boolean_flag_raises(self):
        raw = {"a": "yes", "public": []}
        with pytest.raises(FeatureFlagError, match="must be boolean"):
            _parse_defaults(raw)


# ===========================================================================
# _validate_flags
# ===========================================================================


@pytest.mark.unit
class TestValidateFlags:
    """Tests for override validation logic."""

    def test_valid_override(self):
        defaults = {"a": True, "b": False}
        overrides = {"a": False}
        merged = _validate_flags(defaults, overrides, "test")
        assert merged == {"a": False, "b": False}

    def test_unknown_key_rejected(self):
        defaults = {"a": True}
        overrides = {"a": True, "bogus": False}
        with pytest.raises(FeatureFlagError, match="Unknown feature flag.*bogus"):
            _validate_flags(defaults, overrides, "test")

    def test_multiple_unknown_keys_all_reported(self):
        defaults = {"a": True}
        overrides = {"foo": True, "bar": False}
        with pytest.raises(FeatureFlagError, match="bar.*foo"):
            _validate_flags(defaults, overrides, "test")

    def test_non_boolean_override_rejected(self):
        defaults = {"a": True}
        overrides = {"a": "yes"}
        with pytest.raises(FeatureFlagError, match="must be boolean.*str"):
            _validate_flags(defaults, overrides, "test")

    def test_integer_override_rejected(self):
        defaults = {"a": True}
        overrides = {"a": 1}
        with pytest.raises(FeatureFlagError, match="must be boolean.*int"):
            _validate_flags(defaults, overrides, "test")

    def test_empty_overrides_returns_defaults(self):
        defaults = {"a": True, "b": False}
        merged = _validate_flags(defaults, {}, "test")
        assert merged == defaults

    def test_override_does_not_mutate_defaults(self):
        defaults = {"a": True, "b": False}
        defaults_copy = dict(defaults)
        _validate_flags(defaults, {"a": False}, "test")
        assert defaults == defaults_copy


# ===========================================================================
# _load_yaml
# ===========================================================================


@pytest.mark.unit
class TestLoadYaml:
    """Tests for YAML file loading."""

    def test_loads_valid_yaml(self, tmp_path):
        p = tmp_path / "test.yaml"
        _write_yaml(p, {"flag_a": True, "flag_b": False})
        result = _load_yaml(p)
        assert result == {"flag_a": True, "flag_b": False}

    def test_empty_file_returns_empty_dict(self, tmp_path):
        p = tmp_path / "empty.yaml"
        p.write_text("")
        result = _load_yaml(p)
        assert result == {}

    def test_comment_only_file_returns_empty_dict(self, tmp_path):
        p = tmp_path / "comments.yaml"
        p.write_text("# just a comment\n# nothing here\n")
        result = _load_yaml(p)
        assert result == {}

    def test_non_dict_yaml_returns_empty_dict(self, tmp_path):
        """A YAML file that parses to a list should be treated as empty."""
        p = tmp_path / "list.yaml"
        p.write_text("- item1\n- item2\n")
        result = _load_yaml(p)
        assert result == {}


# ===========================================================================
# load_feature_flags (full pipeline)
# ===========================================================================


@pytest.mark.unit
class TestLoadFeatureFlags:
    """Tests for the full load + merge pipeline."""

    def test_defaults_only_no_env_file(self, tmp_path, monkeypatch):
        flags_dir = _make_flags_dir(tmp_path, {"x": True, "y": False})
        monkeypatch.setattr("app.services.feature_flags._FLAGS_DIR", flags_dir)

        ff = load_feature_flags("nonexistent")
        assert ff.enabled("x") is True
        assert ff.enabled("y") is False
        assert ff.env == "nonexistent"

    def test_env_override_applied(self, tmp_path, monkeypatch):
        flags_dir = _make_flags_dir(
            tmp_path,
            defaults={"a": True, "b": False, "c": True},
            envs={"staging": {"a": False, "b": True}},
        )
        monkeypatch.setattr("app.services.feature_flags._FLAGS_DIR", flags_dir)

        ff = load_feature_flags("staging")
        assert ff.enabled("a") is False  # overridden
        assert ff.enabled("b") is True  # overridden
        assert ff.enabled("c") is True  # default preserved

    def test_public_keys_preserved_through_load(self, tmp_path, monkeypatch):
        flags_dir = _make_flags_dir(
            tmp_path,
            defaults={"a": True, "b": False, "public": ["a"]},
        )
        monkeypatch.setattr("app.services.feature_flags._FLAGS_DIR", flags_dir)

        ff = load_feature_flags("docker")
        assert ff.public_flags == {"a": True}
        assert "b" not in ff.public_flags

    def test_env_override_affects_public_flags(self, tmp_path, monkeypatch):
        flags_dir = _make_flags_dir(
            tmp_path,
            defaults={"a": False, "b": True, "public": ["a"]},
            envs={"prod": {"a": True}},
        )
        monkeypatch.setattr("app.services.feature_flags._FLAGS_DIR", flags_dir)

        ff = load_feature_flags("prod")
        assert ff.public_flags == {"a": True}  # overridden value

    def test_missing_defaults_raises(self, tmp_path, monkeypatch):
        empty_dir = tmp_path / "feature_flags"
        empty_dir.mkdir()
        monkeypatch.setattr("app.services.feature_flags._FLAGS_DIR", empty_dir)

        with pytest.raises(FeatureFlagError, match="defaults.yaml not found"):
            load_feature_flags("any")

    def test_non_boolean_in_defaults_raises(self, tmp_path, monkeypatch):
        flags_dir = _make_flags_dir(tmp_path, {"bad_flag": "yes"})
        monkeypatch.setattr("app.services.feature_flags._FLAGS_DIR", flags_dir)

        with pytest.raises(FeatureFlagError, match="must be boolean"):
            load_feature_flags("docker")

    def test_unknown_key_in_env_raises(self, tmp_path, monkeypatch):
        flags_dir = _make_flags_dir(
            tmp_path,
            defaults={"a": True},
            envs={"bad": {"a": True, "unknown_flag": False}},
        )
        monkeypatch.setattr("app.services.feature_flags._FLAGS_DIR", flags_dir)

        with pytest.raises(FeatureFlagError, match="Unknown feature flag.*unknown_flag"):
            load_feature_flags("bad")

    def test_env_file_with_only_comments(self, tmp_path, monkeypatch):
        """An env file with only comments should behave like no overrides."""
        flags_dir = tmp_path / "feature_flags"
        flags_dir.mkdir()
        _write_yaml(flags_dir / "defaults.yaml", {"a": True, "b": False})
        (flags_dir / "empty_env.yaml").write_text("# No overrides\n")
        monkeypatch.setattr("app.services.feature_flags._FLAGS_DIR", flags_dir)

        ff = load_feature_flags("empty_env")
        assert ff.enabled("a") is True
        assert ff.enabled("b") is False


# ===========================================================================
# Real YAML files (smoke tests against actual repo files)
# ===========================================================================


@pytest.mark.unit
class TestRealYamlFiles:
    """Smoke tests that verify the actual YAML files in the repo parse correctly."""

    def test_defaults_yaml_exists_and_parses(self):
        from app.services.feature_flags import _FLAGS_DIR

        defaults_path = _FLAGS_DIR / "defaults.yaml"
        assert defaults_path.exists(), f"defaults.yaml missing at {defaults_path}"
        raw = _load_yaml(defaults_path)
        flags, public = _parse_defaults(raw)
        assert len(flags) > 0, "defaults.yaml has no flags"

    def test_public_list_references_valid_flags(self):
        from app.services.feature_flags import _FLAGS_DIR

        raw = _load_yaml(_FLAGS_DIR / "defaults.yaml")
        flags, public = _parse_defaults(raw)
        for key in public:
            assert key in flags, f"Public key '{key}' not found in flag definitions"

    def test_all_env_files_are_valid_subsets_of_defaults(self):
        """Every env YAML file must only contain keys from defaults."""
        from app.services.feature_flags import _FLAGS_DIR

        raw = _load_yaml(_FLAGS_DIR / "defaults.yaml")
        flags, _ = _parse_defaults(raw)
        for env_file in _FLAGS_DIR.glob("*.yaml"):
            if env_file.name == "defaults.yaml":
                continue
            overrides = _load_yaml(env_file)
            unknown = set(overrides.keys()) - set(flags.keys())
            assert not unknown, f"{env_file.name} contains unknown flags: {unknown}"
            for key, value in overrides.items():
                assert isinstance(value, bool), (
                    f"{env_file.name}: {key} is {type(value).__name__}, expected bool"
                )

    def test_load_all_real_environments(self):
        """Verify all real env files load without error."""
        from app.services.feature_flags import _FLAGS_DIR

        for env_file in _FLAGS_DIR.glob("*.yaml"):
            if env_file.name == "defaults.yaml":
                continue
            env_name = env_file.stem
            ff = load_feature_flags(env_name)
            assert ff.env == env_name
            assert len(ff.flags) > 0

    def test_production_enables_two_fa(self):
        """Production must have two_fa enabled (per terraform.production.tfvars)."""
        ff = load_feature_flags("production")
        assert ff.enabled("two_fa") is True

    def test_docker_defaults_two_fa_disabled(self):
        """Docker (no overlay file) should use defaults — two_fa is false."""
        ff = load_feature_flags("docker")
        assert ff.enabled("two_fa") is False

    def test_minikube_matches_defaults(self):
        """Minikube has no overrides — should match defaults exactly."""
        ff = load_feature_flags("minikube")
        assert ff.enabled("two_fa") is False
        assert ff.enabled("template_builder") is True
        assert ff.enabled("fileops_v2") is True

    def test_beta_matches_terraform(self):
        """Beta flags should match terraform.beta.tfvars — two_fa disabled."""
        ff = load_feature_flags("beta")
        assert ff.enabled("two_fa") is False

    def test_backend_only_flags_not_in_public(self):
        """Agent flags should not be exposed to the frontend."""
        ff = load_feature_flags("docker")
        for key in ff.public_flags:
            assert not key.startswith("agent_"), f"Agent flag '{key}' should not be in public flags"

    def test_public_flags_are_subset_of_all_flags(self):
        ff = load_feature_flags("docker")
        for key in ff.public_flags:
            assert key in ff.flags
