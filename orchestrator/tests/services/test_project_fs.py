"""``get_project_fs_path`` branches across deployment modes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest

from app.config import get_settings
from app.services.project_fs import get_project_fs_path, has_fs_path, read_all_files


@dataclass
class _Proj:
    slug: str
    id: object


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_none_project_returns_none() -> None:
    assert get_project_fs_path(None) is None
    assert has_fs_path(None) is False


def test_missing_slug_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEPLOYMENT_MODE", "docker")
    project = _Proj(slug="", id=uuid4())
    assert get_project_fs_path(project) is None


def test_docker_mode_returns_projects_mount(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEPLOYMENT_MODE", "docker")
    project = _Proj(slug="my-app", id=uuid4())
    assert get_project_fs_path(project) == Path("/projects/my-app")


def test_desktop_mode_returns_opensail_home_subpath(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEPLOYMENT_MODE", "desktop")
    monkeypatch.setenv("OPENSAIL_HOME", str(tmp_path))
    pid = uuid4()
    project = _Proj(slug="my-app", id=pid)
    expected = (tmp_path / "projects" / f"my-app-{pid}").resolve()
    assert get_project_fs_path(project) == expected


def test_kubernetes_mode_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEPLOYMENT_MODE", "kubernetes")
    project = _Proj(slug="my-app", id=uuid4())
    assert get_project_fs_path(project) is None
    assert has_fs_path(project) is False


@pytest.mark.asyncio
async def test_read_all_files_walks_and_filters(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.ts").write_text("export const x = 1;")
    (tmp_path / "README.md").write_text("hi")
    # Excluded by EXCLUDED_DIRS.
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.js").write_text("x")
    # Binary extension — skipped.
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    out = await read_all_files(tmp_path, max_files=10, max_file_size=1024)
    paths = {f["file_path"] for f in out}
    assert paths == {"src/app.ts", "README.md"}


@pytest.mark.asyncio
async def test_read_all_files_respects_max_files(tmp_path: Path) -> None:
    for i in range(5):
        (tmp_path / f"f{i}.txt").write_text(str(i))
    out = await read_all_files(tmp_path, max_files=2, max_file_size=1024)
    assert len(out) == 2


@pytest.mark.asyncio
async def test_read_all_files_missing_base_returns_empty(tmp_path: Path) -> None:
    assert await read_all_files(tmp_path / "nope") == []
