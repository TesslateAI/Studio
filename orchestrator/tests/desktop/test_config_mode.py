"""Desktop deployment mode + $OPENSAIL_HOME resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.desktop_paths import ensure_opensail_home, resolve_opensail_home
from app.services.orchestration.deployment_mode import DeploymentMode


def test_deployment_mode_accepts_desktop() -> None:
    assert DeploymentMode.from_string("desktop") == DeploymentMode.DESKTOP
    assert DeploymentMode.DESKTOP.is_desktop is True
    assert DeploymentMode.LOCAL.is_desktop is False


def test_deployment_mode_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        DeploymentMode.from_string("not-a-mode")


def test_explicit_opensail_home_wins(tmp_path: Path) -> None:
    assert resolve_opensail_home(str(tmp_path)) == tmp_path


def test_env_var_opensail_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENSAIL_HOME", str(tmp_path))
    assert resolve_opensail_home(None) == tmp_path


def test_default_opensail_home_per_os(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENSAIL_HOME", raising=False)
    root = resolve_opensail_home(None)
    assert root.is_absolute()
    name = root.name.lower()
    # macOS / Windows use "Tesslate Studio"; Linux uses "tesslate-studio"
    assert "tesslate" in name


def test_ensure_opensail_home_creates_tree(tmp_path: Path) -> None:
    root = ensure_opensail_home(str(tmp_path))
    for sub in ("projects", "cache", "logs", "agents", "skills", "bases", "themes"):
        assert (root / sub).is_dir()
