"""Unit tests for ``services.automations.artifacts.create_artifact``.

Routing rules covered:

* Content under :data:`INLINE_SIZE_LIMIT_BYTES` (8 KiB) → inline / base64.
* Content above the cap with a CAS uploader present → cas + sha256 ref.
* ``external_url`` callers → external_url passthrough.
* Preview text capped at :data:`PREVIEW_TEXT_CHARS` (200) for textual kinds.

Tests run against an in-memory SQLite engine with the full
``Base.metadata`` schema rather than alembic head — the artifacts row is
self-contained (no FK fan-out) so a metadata.create_all keeps the test
boundary tight + fast.
"""

from __future__ import annotations

import base64
import hashlib
import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Importing models + models_automations registers all tables on Base.metadata.
from app import models, models_automations  # noqa: F401
from app.database import Base
from app.models_automations import AutomationRunArtifact
from app.services.automations import artifacts


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    """Per-test SQLite engine + session with the full Base schema."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


# A run_id is a foreign key to automation_runs.id but with FK off (above)
# we can use a synthetic UUID without seeding the parent row. The artifact
# row's CHECK / NOT NULL constraints don't span runs.


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_artifact_inline_under_threshold(db: AsyncSession) -> None:
    """4 KiB content → storage_mode='inline', storage_ref is base64 payload."""
    run_id = uuid.uuid4()
    content = "x" * 4096  # 4 KiB, well under the 8 KiB cap.

    row = await artifacts.create_artifact(
        db,
        run_id=run_id,
        kind="text",
        name="four-kib.txt",
        content=content,
    )

    assert isinstance(row, AutomationRunArtifact)
    assert row.storage_mode == "inline"
    # Roundtrip: base64-decode the storage_ref and compare to the input.
    decoded = base64.b64decode(row.storage_ref).decode("utf-8")
    assert decoded == content
    assert row.size_bytes == 4096
    # Preview is capped at PREVIEW_TEXT_CHARS — 200 of the 4096 'x'.
    assert row.preview_text == "x" * artifacts.PREVIEW_TEXT_CHARS


@pytest.mark.asyncio
async def test_create_artifact_routed_to_cas_when_oversized(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """32 KiB content + working CAS uploader → storage_mode='cas', sha256 ref."""
    # Patch the CAS uploader to behave as if the blob was accepted. The
    # production stub returns None (forcing inline+truncate fallback);
    # we override so the CAS branch is exercised end-to-end.
    async def _fake_cas_upload(content_bytes: bytes, sha256_hex: str) -> str:
        return f"cas:{sha256_hex}"

    monkeypatch.setattr(artifacts, "_upload_to_cas", _fake_cas_upload)

    run_id = uuid.uuid4()
    payload = b"y" * (32 * 1024)  # 32 KiB, well over the 8 KiB cap.
    expected_sha = hashlib.sha256(payload).hexdigest()

    row = await artifacts.create_artifact(
        db,
        run_id=run_id,
        kind="log",
        name="big.log",
        content=payload,
    )

    assert row.storage_mode == "cas"
    assert row.storage_ref == f"cas:{expected_sha}"
    assert row.size_bytes == 32 * 1024
    # Meta gets the sha256 stamped for downstream lookup.
    assert row.meta.get("sha256") == expected_sha
    # truncated marker NOT present — the CAS upload succeeded.
    assert "truncated" not in row.meta


@pytest.mark.asyncio
async def test_create_artifact_external_url_passthrough(db: AsyncSession) -> None:
    """external_url= overrides content routing entirely."""
    run_id = uuid.uuid4()
    url = "https://s3.example.com/buckets/run/abcdef.png"

    row = await artifacts.create_artifact(
        db,
        run_id=run_id,
        kind="image",
        name="screenshot.png",
        external_url=url,
    )

    assert row.storage_mode == "external_url"
    assert row.storage_ref == url
    # Image kind → no preview.
    assert row.preview_text is None
    # No content → no size bytes.
    assert row.size_bytes is None


@pytest.mark.asyncio
async def test_preview_text_truncates_to_200_chars(db: AsyncSession) -> None:
    """Long markdown content truncates the preview to PREVIEW_TEXT_CHARS."""
    run_id = uuid.uuid4()
    # Build a 1000-char markdown body that's still under the 8 KiB inline cap.
    body = "# Heading\n\n" + ("hello world " * 100)
    assert len(body.encode("utf-8")) < artifacts.INLINE_SIZE_LIMIT_BYTES

    row = await artifacts.create_artifact(
        db,
        run_id=run_id,
        kind="markdown",
        name="report.md",
        content=body,
    )

    assert row.preview_text is not None
    assert len(row.preview_text) == artifacts.PREVIEW_TEXT_CHARS
    # The preview is the first PREVIEW_TEXT_CHARS chars of the original body.
    assert row.preview_text == body[: artifacts.PREVIEW_TEXT_CHARS]
