"""
Tests for ``app.services.marketplace_local`` — the filesystem-backed
sentinel marketplace source.

Pure-Python tests — no DB required for the scan and envelope helpers.
DB-backed ``sync_local`` tests are marked ``integration`` because they
need a real Postgres + the seeded Local source row.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.services import marketplace_local
from app.services.marketplace_local import (
    LOCAL_BASE_URL_PREFIX,
    LOCAL_SOURCE_HANDLE,
    LocalChangeEvent,
    LocalEnvelope,
    LocalItemRecord,
    get_bundle_envelope,
    materialise_bundle,
    scan_all_kinds,
    scan_kind,
)


@pytest.fixture
def opensail_home(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSAIL_HOME", str(tmp_path))
    return tmp_path


# ---------------------------------------------------------------------------
# scan_kind / scan_all_kinds
# ---------------------------------------------------------------------------


def test_scan_kind_returns_empty_for_missing_dir(opensail_home: Path) -> None:
    assert scan_kind("agent") == []


def test_scan_kind_finds_versionless_item(opensail_home: Path) -> None:
    item_dir = opensail_home / "agents" / "coder"
    item_dir.mkdir(parents=True)
    (item_dir / "manifest.json").write_text(
        json.dumps({"name": "Coder", "version": "1.2.3"})
    )

    records = scan_kind("agent")
    assert len(records) == 1
    rec = records[0]
    assert isinstance(rec, LocalItemRecord)
    assert rec.kind == "agent"
    assert rec.slug == "coder"
    assert rec.version == "1.2.3"
    assert rec.manifest["name"] == "Coder"
    assert rec.bundle_path is None
    # Synthetic bundle hash is deterministic across runs.
    assert len(rec.sha256) == 64
    assert rec.size_bytes > 0


def test_scan_kind_finds_versioned_layout(opensail_home: Path) -> None:
    base = opensail_home / "skills" / "rusty"
    (base / "1.0.0").mkdir(parents=True)
    (base / "1.0.0" / "manifest.json").write_text('{"name":"Rusty"}')
    (base / "2.0.0").mkdir(parents=True)
    (base / "2.0.0" / "manifest.json").write_text('{"name":"Rusty v2"}')

    records = scan_kind("skill")
    assert {r.version for r in records} == {"1.0.0", "2.0.0"}
    assert all(r.slug == "rusty" for r in records)


def test_scan_kind_skips_dirs_without_manifest(opensail_home: Path) -> None:
    (opensail_home / "themes" / "broken").mkdir(parents=True)
    assert scan_kind("theme") == []


def test_scan_kind_uses_pre_built_bundle_if_present(opensail_home: Path) -> None:
    item_dir = opensail_home / "agents" / "with-bundle"
    item_dir.mkdir(parents=True)
    (item_dir / "manifest.json").write_text('{"name":"x","version":"0.0.1"}')
    bundle = item_dir / "bundle.tar.zst"
    bundle.write_bytes(b"\x28\xb5\x2f\xfd" + b"\x00" * 100)  # zstd magic + bytes

    records = scan_kind("agent")
    assert len(records) == 1
    expected_sha = hashlib.sha256(bundle.read_bytes()).hexdigest()
    assert records[0].sha256 == expected_sha
    assert records[0].bundle_path == bundle


def test_scan_all_kinds_walks_every_kind_dir(opensail_home: Path) -> None:
    (opensail_home / "agents" / "a").mkdir(parents=True)
    (opensail_home / "agents" / "a" / "manifest.json").write_text('{"name":"a"}')
    (opensail_home / "themes" / "t").mkdir(parents=True)
    (opensail_home / "themes" / "t" / "manifest.json").write_text('{"name":"t"}')

    recs = scan_all_kinds()
    kinds = {r.kind for r in recs}
    assert "agent" in kinds and "theme" in kinds


# ---------------------------------------------------------------------------
# get_bundle_envelope
# ---------------------------------------------------------------------------


def test_get_bundle_envelope_versionless(opensail_home: Path) -> None:
    item = opensail_home / "agents" / "alpha"
    item.mkdir(parents=True)
    (item / "manifest.json").write_text('{"name":"Alpha","version":"1.0.0"}')

    env = get_bundle_envelope("agent", "alpha")
    assert isinstance(env, LocalEnvelope)
    assert env.url.startswith("local-dir://")
    assert env.archive_format == "tar.zst"
    assert env.expires_at is None
    # sha256 must be a 64-char hex digest, not the empty-bytes placeholder
    # (the actual integrity comparison happens in the next test via
    # materialise_bundle round-trip).
    assert len(env.sha256) == 64
    assert env.size_bytes > 0


def test_get_bundle_envelope_dir_sha_matches_materialised(opensail_home: Path, tmp_path: Path) -> None:
    item = opensail_home / "agents" / "alpha"
    item.mkdir(parents=True)
    (item / "manifest.json").write_text('{"name":"Alpha","version":"1.0.0"}')

    env = get_bundle_envelope("agent", "alpha")
    out = tmp_path / "out.tar.zst"
    materialise_bundle(env, out)
    actual_sha = hashlib.sha256(out.read_bytes()).hexdigest()
    assert actual_sha == env.sha256
    assert out.stat().st_size == env.size_bytes


def test_get_bundle_envelope_uses_pre_built_bundle(opensail_home: Path, tmp_path: Path) -> None:
    item = opensail_home / "agents" / "beta"
    item.mkdir(parents=True)
    (item / "manifest.json").write_text('{"name":"Beta","version":"1.0.0"}')
    bundle = item / "bundle.tar.zst"
    bundle_bytes = b"\x28\xb5\x2f\xfd" + b"hello-bundle"
    bundle.write_bytes(bundle_bytes)

    env = get_bundle_envelope("agent", "beta")
    assert env.url.startswith("local-file://")
    assert env.sha256 == hashlib.sha256(bundle_bytes).hexdigest()

    out = tmp_path / "copy.tar.zst"
    materialise_bundle(env, out)
    assert out.read_bytes() == bundle_bytes


def test_get_bundle_envelope_versioned(opensail_home: Path, tmp_path: Path) -> None:
    base = opensail_home / "skills" / "rusty"
    (base / "1.0.0").mkdir(parents=True)
    (base / "1.0.0" / "manifest.json").write_text('{"name":"Rusty"}')

    env = get_bundle_envelope("skill", "rusty", "1.0.0")
    assert env.url.startswith("local-dir://")
    out = tmp_path / "out.tar.zst"
    materialise_bundle(env, out)
    assert out.stat().st_size == env.size_bytes


def test_get_bundle_envelope_picks_latest_version(opensail_home: Path) -> None:
    base = opensail_home / "skills" / "rusty"
    (base / "1.0.0").mkdir(parents=True)
    (base / "1.0.0" / "manifest.json").write_text('{"name":"Rusty"}')
    (base / "2.0.0").mkdir(parents=True)
    (base / "2.0.0" / "manifest.json").write_text('{"name":"Rusty v2"}')

    env = get_bundle_envelope("skill", "rusty")
    assert env.url.endswith("/2.0.0")


def test_get_bundle_envelope_missing_item_raises(opensail_home: Path) -> None:
    with pytest.raises(FileNotFoundError):
        get_bundle_envelope("agent", "does-not-exist")


def test_get_bundle_envelope_missing_version_raises(opensail_home: Path) -> None:
    item = opensail_home / "agents" / "alpha"
    item.mkdir(parents=True)
    (item / "manifest.json").write_text('{"name":"x","version":"0.0.1"}')
    with pytest.raises(FileNotFoundError):
        get_bundle_envelope("agent", "alpha", "9.9.9")


# ---------------------------------------------------------------------------
# Determinism: re-scanning the same tree yields the same sha256
# ---------------------------------------------------------------------------


def test_directory_bundle_is_deterministic(opensail_home: Path) -> None:
    item = opensail_home / "agents" / "alpha"
    item.mkdir(parents=True)
    (item / "manifest.json").write_text('{"name":"Alpha","version":"1.0.0"}')
    (item / "code.py").write_text("print('hi')")

    sha_first = get_bundle_envelope("agent", "alpha").sha256
    sha_second = get_bundle_envelope("agent", "alpha").sha256
    assert sha_first == sha_second


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_module_exports_constants() -> None:
    assert LOCAL_SOURCE_HANDLE == "local"
    assert LOCAL_BASE_URL_PREFIX == "local://"


# ---------------------------------------------------------------------------
# DB-backed sync_local — integration test (skipped without DB)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sync_local_emits_upsert_events(opensail_home, monkeypatch) -> None:
    """Smoke test for sync_local against an in-memory SQLite DB. The
    DB-touching path: scan emits one upsert per record + clears
    last_sync_error on success.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.models import Base, MarketplaceSource

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)

    item = opensail_home / "agents" / "alpha"
    item.mkdir(parents=True)
    (item / "manifest.json").write_text('{"name":"Alpha","version":"1.0.0"}')

    async with SessionFactory() as session:
        source = MarketplaceSource(
            handle="local",
            display_name="Local",
            base_url="local://filesystem",
            scope="system",
            trust_level="local",
            is_active=True,
        )
        session.add(source)
        await session.commit()
        await session.refresh(source)

        result = await marketplace_local.sync_local(session)
        assert result.items_upserted == 1
        assert any(
            isinstance(e, LocalChangeEvent) and e.op == "upsert" and e.slug == "alpha"
            for e in result.events
        )

    await engine.dispose()
