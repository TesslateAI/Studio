"""
Shared fixtures for git_ops tool tests.

Every test in this package runs against a real, disposable git
repository materialized under ``tmp_path``. The ``PROJECT_ROOT``
environment variable is pointed at that directory so the
``LocalOrchestrator`` resolves all paths to it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

# Ensure the orchestrator package is importable without relying on
# tests/conftest.py being loaded first.
_ORCHESTRATOR_ROOT = Path(__file__).resolve().parents[4]
if str(_ORCHESTRATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_ORCHESTRATOR_ROOT))


def _run(cwd: Path, *args: str, env: dict | None = None) -> str:
    """
    Run a subprocess in ``cwd`` and return its combined output.

    Used only by the test fixtures to stage known repo state before
    the tools under test are exercised.
    """
    result = subprocess.run(
        list(args),
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return (result.stdout or "") + (result.stderr or "")


@pytest.fixture
def temp_git_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """
    Initialize a fresh git repository with known state under ``tmp_path``.

    State after fixture execution:
        - ``main`` branch (configured as init.defaultBranch).
        - Three commits with known content authored by "Alice" (except
          one commit authored by "Bob") authored at fixed dates so tests
          can filter deterministically.
        - A 5-line ``poem.txt`` file whose every line was authored in
          the first commit by Alice.
        - An extra ``feature`` branch containing one additional commit
          on top of ``main`` for diff/branch comparison tests.
        - One modified unstaged file (``README.md``).
        - One staged new file (``src/staged.py``).
        - One untracked file (``notes.txt``).

    The ``PROJECT_ROOT`` environment variable is pointed at the repo
    so tools executing through ``LocalOrchestrator`` resolve here.

    Additionally, the orchestrator factory cache and settings cache are
    cleared and ``DEPLOYMENT_MODE`` is set to ``local`` so
    ``get_orchestrator()`` returns a ``LocalOrchestrator`` pinned to
    this repo.
    """
    repo = tmp_path / f"repo-{uuid4().hex[:8]}"
    repo.mkdir(parents=True)

    # Isolate git's global/system config from the host developer machine.
    env = {
        "HOME": str(tmp_path),
        "GIT_CONFIG_GLOBAL": str(tmp_path / ".gitconfig-global"),
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_AUTHOR_DATE": "2024-01-01T12:00:00+00:00",
        "GIT_COMMITTER_DATE": "2024-01-01T12:00:00+00:00",
        "GIT_TERMINAL_PROMPT": "0",
        "PATH": "/usr/bin:/bin:/usr/local/bin",
    }

    _run(repo, "git", "init", "-q", "-b", "main", env=env)
    _run(repo, "git", "config", "user.email", "alice@example.com", env=env)
    _run(repo, "git", "config", "user.name", "Alice", env=env)
    _run(repo, "git", "config", "commit.gpgsign", "false", env=env)
    _run(repo, "git", "config", "tag.gpgsign", "false", env=env)

    # --- Commit 1: initial README plus the poem file authored by Alice.
    (repo / "README.md").write_text(
        "# Test Repo\n\nInitial content for the test repository.\n",
        encoding="utf-8",
    )
    (repo / "poem.txt").write_text(
        "line one\nline two\nline three\nline four\nline five\n",
        encoding="utf-8",
    )
    _run(repo, "git", "add", "README.md", "poem.txt", env=env)
    env_c1 = {
        **env,
        "GIT_AUTHOR_DATE": "2024-01-01T12:00:00+00:00",
        "GIT_COMMITTER_DATE": "2024-01-01T12:00:00+00:00",
    }
    _run(repo, "git", "commit", "-q", "-m", "Initial commit", env=env_c1)

    # --- Commit 2: add src/app.py. Still authored by Alice.
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text(
        "def hello():\n    return 'hi'\n",
        encoding="utf-8",
    )
    _run(repo, "git", "add", "src/app.py", env=env)
    env_c2 = {
        **env,
        "GIT_AUTHOR_DATE": "2024-02-01T12:00:00+00:00",
        "GIT_COMMITTER_DATE": "2024-02-01T12:00:00+00:00",
    }
    _run(repo, "git", "commit", "-q", "-m", "Add app.py", env=env_c2)

    # --- Commit 3: authored by Bob — used by git_log author filter tests.
    (repo / "src" / "app.py").write_text(
        "def hello():\n    return 'hello world'\n",
        encoding="utf-8",
    )
    _run(repo, "git", "add", "src/app.py", env=env)
    env_c3 = {
        **env,
        "GIT_AUTHOR_NAME": "Bob",
        "GIT_AUTHOR_EMAIL": "bob@example.com",
        "GIT_AUTHOR_DATE": "2024-03-01T12:00:00+00:00",
        "GIT_COMMITTER_DATE": "2024-03-01T12:00:00+00:00",
    }
    _run(repo, "git", "commit", "-q", "-m", "Update greeting", env=env_c3)

    # --- Feature branch with one extra commit (for diff base..target tests).
    _run(repo, "git", "checkout", "-q", "-b", "feature", env=env)
    (repo / "src" / "feature.py").write_text(
        "def feature():\n    return 'new feature'\n",
        encoding="utf-8",
    )
    _run(repo, "git", "add", "src/feature.py", env=env)
    env_feat = {
        **env,
        "GIT_AUTHOR_DATE": "2024-04-01T12:00:00+00:00",
        "GIT_COMMITTER_DATE": "2024-04-01T12:00:00+00:00",
    }
    _run(repo, "git", "commit", "-q", "-m", "Add feature.py", env=env_feat)

    # Back to main for the working-tree state the tests expect.
    _run(repo, "git", "checkout", "-q", "main", env=env)

    # --- Worktree modifications exercised by git_status / git_diff tests.
    # Modified unstaged file.
    (repo / "README.md").write_text(
        "# Test Repo\n\nInitial content for the test repository.\n\nExtra line.\n",
        encoding="utf-8",
    )
    # Staged new file.
    (repo / "src" / "staged.py").write_text(
        "STAGED = True\n",
        encoding="utf-8",
    )
    _run(repo, "git", "add", "src/staged.py", env=env)
    # Untracked file.
    (repo / "notes.txt").write_text("scratch notes\n", encoding="utf-8")

    # ------------------------------------------------------------------
    # Point LocalOrchestrator at the repo and clear any cached factory
    # / settings state so the tools under test resolve here.
    # ------------------------------------------------------------------
    monkeypatch.setenv("PROJECT_ROOT", str(repo))
    monkeypatch.setenv("DEPLOYMENT_MODE", "local")

    from app.config import get_settings
    from app.services.orchestration.factory import OrchestratorFactory

    get_settings.cache_clear()
    OrchestratorFactory.clear_cache()

    yield repo

    # Clean up factory / settings cache so unrelated tests are unaffected.
    OrchestratorFactory.clear_cache()
    get_settings.cache_clear()


@pytest.fixture
def tool_context() -> dict:
    """
    Standard tool-execution context with disposable identifiers.

    ``LocalOrchestrator`` ignores user/project/container identity — it
    operates solely on ``PROJECT_ROOT`` — so any UUIDs work.
    """
    return {
        "user_id": uuid4(),
        "project_id": uuid4(),
        "container_name": "main",
    }
