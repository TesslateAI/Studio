"""`GET /api/desktop/agents/{ticket_id}/diff` runs `git diff HEAD` for the project."""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.routers.desktop.sessions import _git_diff_for_project
from app.routers import desktop
from app.users import current_active_user


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    (path / "file.txt").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)


@pytest.mark.asyncio
async def test_git_diff_for_project_empty_when_no_git(tmp_path):
    project = Mock(source_path=str(tmp_path), slug="s", id=uuid.uuid4())
    assert await _git_diff_for_project(project) == ""


@pytest.mark.asyncio
async def test_git_diff_for_project_returns_diff(tmp_path):
    _init_git_repo(tmp_path)
    (tmp_path / "file.txt").write_text("hello\nchanged\n")
    project = Mock(source_path=str(tmp_path), slug="s", id=uuid.uuid4())
    diff = await _git_diff_for_project(project)
    assert "+changed" in diff
    assert "file.txt" in diff


@pytest.mark.asyncio
async def test_git_diff_for_project_no_source_path_no_raise():
    project = Mock(source_path=None, slug="s", id=uuid.uuid4())
    # Falls through to _get_project_root which won't exist under tmp — returns "".
    assert await _git_diff_for_project(project) == ""


def test_diff_endpoint_404_when_ticket_missing():
    app = FastAPI()
    app.include_router(desktop.router)
    fake_user = Mock(id="00000000-0000-0000-0000-000000000001")
    app.dependency_overrides[current_active_user] = lambda: fake_user

    class _Result:
        def scalar_one_or_none(self):
            return None

    class _Session:
        async def execute(self, _stmt):
            return _Result()

    async def _db():
        yield _Session()

    app.dependency_overrides[get_db] = _db
    with TestClient(app) as client:
        resp = client.get(f"/api/desktop/agents/{uuid.uuid4()}/diff")
    assert resp.status_code == 404
