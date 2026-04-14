"""LocalOrchestrator per-project root resolution for desktop mode."""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest

_ORCHESTRATOR_ROOT = Path(__file__).resolve().parents[3]
if str(_ORCHESTRATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_ORCHESTRATOR_ROOT))

from app.config import get_settings  # noqa: E402
from app.services.orchestration.local import (  # noqa: E402
    _PROJECT_ROOT_CACHE,
    LocalOrchestrator,
    _invalidate_project_root_cache,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_caches() -> None:
    get_settings.cache_clear()  # type: ignore[attr-defined]
    _invalidate_project_root_cache()
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]
    _invalidate_project_root_cache()


@pytest.fixture
def desktop_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("DEPLOYMENT_MODE", "desktop")
    monkeypatch.setenv("TESSLATE_STUDIO_HOME", str(tmp_path))
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path / "legacy"))
    return tmp_path


async def test_resolver_returns_self_root_without_project_id(
    desktop_home: Path,
) -> None:
    orch = LocalOrchestrator()
    root = await orch._resolve_project_root(None)
    assert root == orch.root


async def test_resolver_builds_slug_id_path_when_slug_known(
    desktop_home: Path,
) -> None:
    orch = LocalOrchestrator()
    pid = uuid4()
    root = await orch._resolve_project_root(pid, "my-app")
    assert root == (desktop_home / "projects" / f"my-app-{pid}").resolve()


async def test_resolver_is_noop_outside_desktop_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEPLOYMENT_MODE", "docker")
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    orch = LocalOrchestrator()
    root = await orch._resolve_project_root(uuid4(), "my-app")
    assert root == orch.root  # docker mode → single root fallback


async def test_multi_project_file_isolation(desktop_home: Path) -> None:
    """Two projects: read_file under project A must not see B's data."""
    orch = LocalOrchestrator()
    pid_a, slug_a = uuid4(), "app-a"
    pid_b, slug_b = uuid4(), "app-b"

    for pid, slug in ((pid_a, slug_a), (pid_b, slug_b)):
        (desktop_home / "projects" / f"{slug}-{pid}").mkdir(parents=True, exist_ok=True)

    user = uuid4()
    assert await orch.write_file(
        user, pid_a, "main", "hello.txt", "from-a", project_slug=slug_a
    )
    assert await orch.write_file(
        user, pid_b, "main", "hello.txt", "from-b", project_slug=slug_b
    )

    a = await orch.read_file(user, pid_a, "main", "hello.txt", project_slug=slug_a)
    b = await orch.read_file(user, pid_b, "main", "hello.txt", project_slug=slug_b)
    assert a == "from-a"
    assert b == "from-b"


async def test_cache_population_and_invalidation(desktop_home: Path) -> None:
    orch = LocalOrchestrator()
    pid = uuid4()
    (desktop_home / "projects" / f"seed-{pid}").mkdir(parents=True, exist_ok=True)

    # Slug-known path doesn't populate cache (no DB lookup needed).
    await orch._resolve_project_root(pid, "seed")
    assert pid not in _PROJECT_ROOT_CACHE

    # Manually seed the cache then invalidate.
    _PROJECT_ROOT_CACHE[pid] = desktop_home / "projects" / f"seed-{pid}"
    _invalidate_project_root_cache(pid)
    assert pid not in _PROJECT_ROOT_CACHE


async def test_cache_clear_all(desktop_home: Path) -> None:
    _PROJECT_ROOT_CACHE[UUID("00000000-0000-0000-0000-000000000001")] = desktop_home
    _PROJECT_ROOT_CACHE[UUID("00000000-0000-0000-0000-000000000002")] = desktop_home
    _invalidate_project_root_cache()
    assert _PROJECT_ROOT_CACHE == {}
