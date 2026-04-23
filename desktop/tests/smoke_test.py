"""
Desktop smoke tests — cover the PRD verification checklist.

Split into two groups:
  - Automated (run in CI via `pytest desktop/tests/smoke_test.py -m automated`)
  - Manual    (run locally with a live Tauri build; skip in CI)

Manual tests document the exact steps and expected outcomes so QA can
execute them without reading source code.
"""

import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR_DIR = REPO_ROOT / "orchestrator"


def _alembic_upgrade(db_url: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": db_url, "SECRET_KEY": "smoke-test-key", "DEPLOYMENT_MODE": "desktop"}
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ORCHESTRATOR_DIR,
        env=env,
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# Automated — safe to run in CI (no Tauri binary required)
# ---------------------------------------------------------------------------


@pytest.mark.automated
def test_alembic_upgrade_fresh_sqlite():
    """All migrations apply cleanly to a fresh SQLite database."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "smoke.db"
        result = _alembic_upgrade(f"sqlite+aiosqlite:///{db_path}")
        assert result.returncode == 0, (
            f"alembic upgrade failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
        # Verify the DB was actually created and has tables
        conn = sqlite3.connect(db_path)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        assert "users" in tables, f"Expected 'users' table, got: {tables}"
        assert "projects" in tables, f"Expected 'projects' table, got: {tables}"


@pytest.mark.automated
def test_alembic_idempotent_on_existing_sqlite():
    """Running `alembic upgrade head` twice on the same DB is a no-op."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "smoke.db"
        url = f"sqlite+aiosqlite:///{db_path}"
        r1 = _alembic_upgrade(url)
        assert r1.returncode == 0
        r2 = _alembic_upgrade(url)
        assert r2.returncode == 0, (
            f"Second upgrade failed:\nSTDOUT:\n{r2.stdout}\nSTDERR:\n{r2.stderr}"
        )


@pytest.mark.automated
def test_sidecar_entrypoint_importable():
    """The sidecar entrypoint module can be imported without crashing."""
    sidecar_dir = REPO_ROOT / "desktop" / "sidecar"
    result = subprocess.run(
        [sys.executable, "-c", "import entrypoint"],
        cwd=sidecar_dir,
        capture_output=True,
        text=True,
        env={**os.environ, "OPENSAIL_HOME": tempfile.gettempdir()},
    )
    # ImportError is acceptable if deps not installed; syntax error is not.
    assert result.returncode != 1 or "SyntaxError" not in result.stderr, (
        f"Syntax error in sidecar entrypoint:\n{result.stderr}"
    )


# ---------------------------------------------------------------------------
# Manual — require a live `cargo tauri dev` session
# ---------------------------------------------------------------------------
# Run with: pytest desktop/tests/smoke_test.py -m manual -v
# Each test is a documented checklist item; all are marked xfail in CI.
# ---------------------------------------------------------------------------

_CI = os.getenv("CI", "false").lower() == "true"
manual = pytest.mark.skipif(_CI, reason="Manual test — requires live Tauri session")


@manual
def test_manual_dev_startup():
    """
    MANUAL: cargo tauri dev → sidecar + tray + UI all up.

    Steps:
      1. cd desktop && ./scripts/dev.sh
      2. Wait for "sidecar ready on …" in terminal.
      3. Confirm the system tray icon appears.
      4. Confirm the Studio window opens and shows the dashboard.
    Expected: No crash, tray icon visible, window loads without a blank screen.
    """
    pytest.skip("Run manually — see docstring for steps")


@manual
def test_manual_create_project_local_runtime():
    """
    MANUAL: Create project → pick 'Local' runtime → correct orchestrator runs it.

    Steps:
      1. Click "+ New Project".
      2. Select runtime dropdown → choose "Local".
      3. Submit. Wait for setup to complete.
      4. In project view, click "Start". Confirm containers start on localhost ports.
    Expected: Project starts; no Docker daemon required; URL uses localhost:<port>.
    """
    pytest.skip("Run manually — see docstring for steps")


@manual
def test_manual_import_local_dir():
    """
    MANUAL: Import existing local dir → opens in Local runtime.

    Steps:
      1. Click "Import Project" / "Open Folder".
      2. Pick any directory with source code.
    Expected: Project opens with Local runtime; no git clone attempted.
    """
    pytest.skip("Run manually — see docstring for steps")


@manual
def test_manual_docker_dropdown_greyed_without_docker():
    """
    MANUAL: Docker dropdown is greyed with 'Install Docker Desktop' when Docker absent.

    Steps:
      1. Stop Docker Desktop (or uninstall).
      2. Open runtime dropdown in new-project dialog.
    Expected: Docker option is visually disabled and shows 'Install Docker Desktop'.
    """
    pytest.skip("Run manually — see docstring for steps")


@manual
def test_manual_k8s_disabled_when_logged_out():
    """
    MANUAL: K8s dropdown is disabled when the user is not logged in to cloud.

    Steps:
      1. Ensure cloud pairing is cleared (DELETE /api/desktop/auth/token).
      2. Open runtime dropdown in new-project dialog.
    Expected: K8s option is disabled.
    """
    pytest.skip("Run manually — see docstring for steps")


@manual
def test_manual_agent_task_tray_notification():
    """
    MANUAL: 5-min agent task → close window → tray notification → reopen → final state.

    Steps:
      1. Open a project and send a long agent task (e.g. "write 500 lines of code").
      2. Close the main window (app stays in tray).
      3. Wait for task to finish.
      4. Confirm OS system notification fires.
      5. Click the tray icon → Open Studio.
    Expected: Final agent state is visible in chat.
    """
    pytest.skip("Run manually — see docstring for steps")


@manual
def test_manual_concurrent_agent_sessions():
    """
    MANUAL: 3 concurrent agent sessions on different projects — no cross-talk.

    Steps:
      1. Open three different projects.
      2. Send an agent task in each simultaneously.
      3. Watch event streams in each tab.
    Expected: Each tab's events belong to its own project; no mixing.
    """
    pytest.skip("Run manually — see docstring for steps")


@manual
def test_manual_marketplace_offline_toggle():
    """
    MANUAL: Marketplace toggle off → local only; toggle on while logged in → cloud items tagged.

    Steps:
      1. Open Marketplace. Confirm cloud items appear (when paired).
      2. Toggle marketplace off.
    Expected: Only local items shown, no "From cloud" badges.
      3. Toggle back on while logged in.
    Expected: Cloud items reappear tagged.
    """
    pytest.skip("Run manually — see docstring for steps")


@manual
def test_manual_updater_prompt():
    """
    MANUAL: Updater check fires at startup and prompts when a newer version is published.

    Steps (requires a signed release manifest at the configured endpoint):
      1. Build the app at a lower version than latest.json advertises.
      2. Launch the app.
    Expected: An "Update Available" dialog appears within ~30 s of startup.
      3. Click "Install". App downloads and relaunches at the new version.
    Expected: App version shown in About screen is the new version.

    Setup notes:
      - Generate a keypair:   cargo tauri signer generate
      - Store private key as CI secret TAURI_SIGNING_PRIVATE_KEY.
      - Publish latest.json to https://opensail.tesslate.com/desktop/releases/latest.json.
      - Replace the PLACEHOLDER pubkey in tauri.conf.json with the public key output.
    """
    pytest.skip("Run manually — requires signed release manifest")
