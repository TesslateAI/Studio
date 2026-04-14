"""sync_client: pack/manifest/push/pull behaviors (respx-mocked, fully offline)."""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import respx


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def studio_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("TESSLATE_STUDIO_HOME", str(tmp_path))
    monkeypatch.delenv("TESSLATE_CLOUD_TOKEN", raising=False)
    (tmp_path / "projects").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cache").mkdir(parents=True, exist_ok=True)
    from app.config import get_settings

    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


@pytest.fixture
def paired(studio_home: Path):
    from app.services import token_store

    token_store.set_cloud_token("tsk_test")
    yield
    token_store.clear_cloud_token()


@pytest.fixture
def cloud_singleton(monkeypatch: pytest.MonkeyPatch):
    from app.services import cloud_client as cc_mod

    async def _no_sleep(_s: float) -> None:
        return None

    monkeypatch.setattr(cc_mod.CloudClient, "_sleep", staticmethod(_no_sleep))

    holder: dict[str, cc_mod.CloudClient] = {}

    async def fake_get():
        if "c" not in holder:
            holder["c"] = cc_mod.CloudClient(base_url="https://cloud.test")
        return holder["c"]

    monkeypatch.setattr("app.services.sync_client.get_cloud_client", fake_get)


def _make_project(root: Path, *, last_sync_at=None) -> SimpleNamespace:
    """Build a minimal Project-like object pointed at ``root``."""
    return SimpleNamespace(
        id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        slug="proj",
        source_path=str(root),
        last_sync_at=last_sync_at,
    )


def _seed_project_tree(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text("hello world")
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("print(1)\n")
    # Excluded entries
    (root / "node_modules").mkdir()
    (root / "node_modules" / "foo.js").write_text("console.log('x')")
    (root / ".venv").mkdir()
    (root / ".venv" / "pyvenv.cfg").write_text("home = /")
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main")
    (root / ".tesslate").mkdir()
    (root / ".tesslate" / "logs").mkdir()
    (root / ".tesslate" / "logs" / "a.log").write_text("log bytes")


# ---------------------------------------------------------------------------
# pack + manifest
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pack_excludes_junk(tmp_path: Path) -> None:
    from app.services import sync_client

    root = tmp_path / "proj"
    _seed_project_tree(root)
    project = _make_project(root)

    zip_path = await sync_client.pack_project(project)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = set(zf.namelist())
    finally:
        zip_path.unlink(missing_ok=True)

    assert "README.md" in names
    assert "src/app.py" in names
    assert not any(n.startswith("node_modules/") for n in names)
    assert not any(n.startswith(".venv/") for n in names)
    assert not any(n.startswith(".git/") for n in names)
    assert not any(n.startswith(".tesslate/logs") for n in names)


@pytest.mark.asyncio
async def test_manifest_is_stable(tmp_path: Path) -> None:
    from app.services import sync_client

    root = tmp_path / "proj"
    _seed_project_tree(root)
    project = _make_project(root)

    m1 = await sync_client.compute_manifest(project)
    m2 = await sync_client.compute_manifest(project)

    # created_at differs, but file list / hashes must be identical.
    assert [f["path"] for f in m1["files"]] == [f["path"] for f in m2["files"]]
    assert [f["sha256"] for f in m1["files"]] == [f["sha256"] for f in m2["files"]]
    assert m1["total_size"] == m2["total_size"]
    # Known content: README.md sha256
    import hashlib as _h

    expected = _h.sha256(b"hello world").hexdigest()
    readme = next(f for f in m1["files"] if f["path"] == "README.md")
    assert readme["sha256"] == expected


# ---------------------------------------------------------------------------
# push
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_push_happy_path_updates_last_sync(
    tmp_path: Path, studio_home: Path, paired, cloud_singleton
) -> None:
    from app.services import sync_client

    root = tmp_path / "proj"
    _seed_project_tree(root)
    project = _make_project(root)
    pid = str(project.id)

    with respx.mock(assert_all_called=False) as router:
        router.get(f"https://cloud.test/api/v1/projects/sync/manifest/{pid}").mock(
            return_value=httpx.Response(404)
        )
        router.post("https://cloud.test/api/v1/projects/sync/push").mock(
            return_value=httpx.Response(
                200,
                json={
                    "sync_id": "snap-1",
                    "uploaded_at": "2026-04-14T12:00:00+00:00",
                    "snapshot_id": "snap-1",
                    "size_bytes": 123,
                },
            )
        )

        result = await sync_client.push(project)

    assert result.sync_id == "snap-1"
    assert result.bytes_uploaded > 0
    assert project.last_sync_at is not None


@pytest.mark.asyncio
async def test_push_conflict_when_remote_newer(
    tmp_path: Path, studio_home: Path, paired, cloud_singleton
) -> None:
    from app.services import sync_client

    root = tmp_path / "proj"
    _seed_project_tree(root)
    older = datetime.now(timezone.utc) - timedelta(hours=1)
    project = _make_project(root, last_sync_at=older)
    pid = str(project.id)

    newer = (datetime.now(timezone.utc)).isoformat()
    with respx.mock(assert_all_called=False) as router:
        router.get(f"https://cloud.test/api/v1/projects/sync/manifest/{pid}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "project_id": pid,
                    "snapshot_id": "snap-remote",
                    "manifest": {},
                    "updated_at": newer,
                },
            )
        )
        push_route = router.post("https://cloud.test/api/v1/projects/sync/push")

        with pytest.raises(sync_client.ConflictError):
            await sync_client.push(project)

        assert not push_route.called  # pre-flight blocked the push


# ---------------------------------------------------------------------------
# pull
# ---------------------------------------------------------------------------


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_pull_extracts_atomically(
    tmp_path: Path, studio_home: Path, paired, cloud_singleton
) -> None:
    from app.services import sync_client

    root = tmp_path / "proj"
    _seed_project_tree(root)
    # Pre-existing file we expect to be replaced:
    (root / "README.md").write_text("OLD")
    project = _make_project(root)
    pid = str(project.id)

    zip_payload = _zip_bytes(
        {
            "README.md": b"NEW-from-cloud",
            "src/app.py": b"print('new')\n",
        }
    )

    with respx.mock(assert_all_called=False) as router:
        router.get(f"https://cloud.test/api/v1/projects/sync/pull/{pid}").mock(
            return_value=httpx.Response(
                200,
                content=zip_payload,
                headers={"content-type": "application/zip"},
            )
        )

        result = await sync_client.pull(pid, project=project)

    assert result.files_written == 2
    assert (root / "README.md").read_bytes() == b"NEW-from-cloud"
    # No leftover staging dirs
    assert not root.with_suffix(root.suffix + ".incoming").exists()
    assert not root.with_suffix(root.suffix + ".replaced").exists()


@pytest.mark.asyncio
async def test_pull_failure_leaves_project_intact(
    tmp_path: Path, studio_home: Path, paired, cloud_singleton
) -> None:
    from app.services import sync_client

    root = tmp_path / "proj"
    _seed_project_tree(root)
    (root / "README.md").write_text("ORIGINAL")
    project = _make_project(root)
    pid = str(project.id)

    with respx.mock(assert_all_called=False) as router:
        router.get(f"https://cloud.test/api/v1/projects/sync/pull/{pid}").mock(
            return_value=httpx.Response(500)
        )

        with pytest.raises(sync_client.SyncError):
            await sync_client.pull(pid, project=project)

    # Original tree untouched, no stray staging dirs.
    assert (root / "README.md").read_text() == "ORIGINAL"
    assert not (root.parent / (root.name + ".incoming")).exists()
    assert not (root.parent / (root.name + ".replaced")).exists()
