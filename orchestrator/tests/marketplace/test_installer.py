"""marketplace_installer: happy path, sha mismatch, ack non-blocking, uninstall."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest
import respx


@pytest.fixture
def opensail_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("OPENSAIL_HOME", str(tmp_path))
    monkeypatch.delenv("TESSLATE_CLOUD_TOKEN", raising=False)
    for sub in ("agents", "skills", "bases", "themes", "cache"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    from app.config import get_settings

    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


@pytest.fixture
def paired(opensail_home: Path):
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

    monkeypatch.setattr("app.services.marketplace_installer.get_cloud_client", fake_get)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.mark.asyncio
async def test_install_happy_path(opensail_home: Path, paired, cloud_singleton) -> None:
    from app.services import marketplace_installer

    payload = b"skill body contents"
    sha = _sha(payload)

    with respx.mock(assert_all_called=False) as router:
        router.post("https://cloud.test/api/v1/marketplace/install").mock(
            return_value=httpx.Response(
                200,
                json={
                    "install_id": "inst-123",
                    "download_urls": [
                        {
                            "url": "https://cdn.test/skill.md",
                            "sha256": sha,
                            "name": "skill.md",
                        }
                    ],
                    "manifest": {
                        "slug": "my-skill",
                        "name": "My Skill",
                        "version": "1.0.0",
                    },
                },
            )
        )
        router.get("https://cdn.test/skill.md").mock(
            return_value=httpx.Response(200, content=payload)
        )
        ack = router.post("https://cloud.test/api/v1/marketplace/install/inst-123/ack").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )

        result = await marketplace_installer.install("skill", "my-skill")

    assert result.kind == "skill"
    assert result.slug == "my-skill"
    assert result.install_id == "inst-123"
    install_dir = opensail_home / "skills" / "my-skill"
    assert install_dir.is_dir()
    assert (install_dir / "skill.md").read_bytes() == payload
    manifest = json.loads((install_dir / "manifest.json").read_text())
    assert manifest["source"] == "local"
    assert manifest["installed_from"] == "cloud"
    assert manifest["install_id"] == "inst-123"
    assert manifest["slug"] == "my-skill"
    assert ack.called


@pytest.mark.asyncio
async def test_install_sha_mismatch_leaves_no_files(
    opensail_home: Path, paired, cloud_singleton
) -> None:
    from app.services import marketplace_installer

    with respx.mock(assert_all_called=False) as router:
        router.post("https://cloud.test/api/v1/marketplace/install").mock(
            return_value=httpx.Response(
                200,
                json={
                    "install_id": "inst-bad",
                    "download_urls": [
                        {
                            "url": "https://cdn.test/x.bin",
                            "sha256": "0" * 64,
                            "name": "x.bin",
                        }
                    ],
                    "manifest": {"slug": "bad-skill", "name": "Bad"},
                },
            )
        )
        router.get("https://cdn.test/x.bin").mock(
            return_value=httpx.Response(200, content=b"real bytes")
        )

        with pytest.raises(marketplace_installer.InstallError, match="sha256"):
            await marketplace_installer.install("skill", "bad-skill")

    assert not (opensail_home / "skills" / "bad-skill").exists()
    assert not (opensail_home / "skills" / "bad-skill.installing").exists()


@pytest.mark.asyncio
async def test_install_ack_failure_is_non_blocking(
    opensail_home: Path, paired, cloud_singleton
) -> None:
    from app.services import marketplace_installer

    payload = b"theme bytes"
    sha = _sha(payload)

    with respx.mock(assert_all_called=False) as router:
        router.post("https://cloud.test/api/v1/marketplace/install").mock(
            return_value=httpx.Response(
                200,
                json={
                    "install_id": "inst-ack-fail",
                    "download_urls": [
                        {
                            "url": "https://cdn.test/theme.css",
                            "sha256": sha,
                            "name": "theme.css",
                        }
                    ],
                    "manifest": {"slug": "my-theme", "name": "Theme"},
                },
            )
        )
        router.get("https://cdn.test/theme.css").mock(
            return_value=httpx.Response(200, content=payload)
        )
        router.post("https://cloud.test/api/v1/marketplace/install/inst-ack-fail/ack").mock(
            return_value=httpx.Response(500)
        )

        result = await marketplace_installer.install("theme", "my-theme")

    assert result.install_id == "inst-ack-fail"
    assert (opensail_home / "themes" / "my-theme" / "manifest.json").is_file()


@pytest.mark.asyncio
async def test_uninstall_removes_directory(opensail_home: Path) -> None:
    from app.services import marketplace_installer

    target = opensail_home / "agents" / "gone"
    target.mkdir(parents=True)
    (target / "manifest.json").write_text("{}")

    removed = await marketplace_installer.uninstall("agent", "gone")
    assert removed is True
    assert not target.exists()


@pytest.mark.asyncio
async def test_uninstall_missing_returns_false(opensail_home: Path) -> None:
    from app.services import marketplace_installer

    assert await marketplace_installer.uninstall("agent", "nope") is False


@pytest.mark.asyncio
async def test_install_duplicate_raises(opensail_home: Path, paired, cloud_singleton) -> None:
    from app.services import marketplace_installer

    (opensail_home / "skills" / "dup").mkdir(parents=True)
    with pytest.raises(marketplace_installer.InstallError, match="already"):
        await marketplace_installer.install("skill", "dup")
