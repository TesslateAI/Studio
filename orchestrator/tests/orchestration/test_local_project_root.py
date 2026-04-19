"""Per-project root resolution under the desktop local runtime."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.config import get_settings
from app.services.orchestration.local import _get_project_root


@pytest.fixture
def desktop_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the studio home at an isolated tmpdir and flip to desktop mode."""
    monkeypatch.setenv("TESSLATE_STUDIO_HOME", str(tmp_path))
    monkeypatch.setenv("DEPLOYMENT_MODE", "desktop")
    # Blow away the cached settings so the new env vars take effect.
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def test_three_projects_resolve_to_disjoint_roots(desktop_home: Path) -> None:
    projects = [
        SimpleNamespace(id=uuid4(), slug="alpha"),
        SimpleNamespace(id=uuid4(), slug="beta"),
        SimpleNamespace(id=uuid4(), slug="gamma"),
    ]

    roots = [_get_project_root(p) for p in projects]

    # All three are distinct paths.
    assert len({str(r) for r in roots}) == 3

    # Each lives under $TESSLATE_STUDIO_HOME/projects/.
    projects_dir = (desktop_home / "projects").resolve()
    for p, root in zip(projects, roots, strict=True):
        assert root.parent == projects_dir
        assert root.name == f"{p.slug}-{p.id}"


def test_falls_back_to_cwd_without_project_arg(
    desktop_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Even under desktop mode, a None project reverts to the legacy path.
    monkeypatch.delenv("PROJECT_ROOT", raising=False)
    root = _get_project_root(None)
    # Should NOT be under the studio-home projects dir (that requires a project).
    assert (desktop_home / "projects") not in root.parents


def test_non_desktop_mode_ignores_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEPLOYMENT_MODE", "docker")
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    get_settings.cache_clear()
    try:
        root = _get_project_root(SimpleNamespace(id=uuid4(), slug="whatever"))
        # Falls through to PROJECT_ROOT because mode != desktop.
        assert root == tmp_path.resolve()
    finally:
        get_settings.cache_clear()
