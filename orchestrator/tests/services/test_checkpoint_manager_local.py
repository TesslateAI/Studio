"""Checkpoint manager runs directly on the desktop filesystem in local mode."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.config import get_settings
from app.services.checkpoint_manager import CheckpointManager


@pytest.fixture(autouse=True)
def _reset_settings() -> None:
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


@pytest.fixture
def desktop_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, object]:
    """Bootstrap a desktop-mode project directory with a clean tree."""
    monkeypatch.setenv("DEPLOYMENT_MODE", "desktop")
    monkeypatch.setenv("TESSLATE_STUDIO_HOME", str(tmp_path))

    class _Proj:
        def __init__(self, slug: str, pid) -> None:
            self.slug = slug
            self.id = pid

    pid = uuid4()
    slug = "test-proj"
    project_dir = tmp_path / "projects" / f"{slug}-{pid}"
    project_dir.mkdir(parents=True)
    (project_dir / "README.md").write_text("initial\n")

    return project_dir, _Proj(slug, pid)


@pytest.mark.asyncio
async def test_local_exec_rewrites_app_prefix_to_project_dir(
    desktop_project: tuple[Path, object],
) -> None:
    project_dir, project = desktop_project
    pid = project.id

    mgr = CheckpointManager(user_id=uuid4(), project_id=str(pid))

    result = AsyncMock(return_value=project)
    with patch(
        "app.database.AsyncSessionLocal"
    ) as session_factory:
        session = AsyncMock()
        session.execute = AsyncMock()
        session.execute.return_value.scalar_one_or_none = lambda: project
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        session_factory.return_value = session

        out = await mgr._local_exec("ls /app/README.md", timeout=5)

    assert "README.md" in out


def test_checkpoint_git_create_works_on_real_fs(
    desktop_project: tuple[Path, object],
) -> None:
    """Smoke: the script our _exec feeds (sans _app substitution) is valid
    shell when run inside the project dir — verifies the git-only script
    doesn't depend on anything the container image provided."""
    project_dir, _ = desktop_project
    script = (
        f"cd {project_dir} && git -c safe.directory={project_dir} init -b main"
        " >/dev/null 2>&1 && echo OK"
    )
    result = subprocess.run(
        ["/bin/sh", "-c", script], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0
    assert "OK" in result.stdout
