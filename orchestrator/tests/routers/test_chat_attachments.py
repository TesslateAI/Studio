"""Standalone-chat attachment upload + GC + binding behavior."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

import pytest
from alembic import command
from alembic.config import Config
from fastapi import UploadFile
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def _install_sqlite_now(engine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn, _record):
        dbapi_conn.create_function("now", 0, lambda: datetime.now(UTC).isoformat(sep=" "))


def _alembic_cfg() -> Config:
    orchestrator_dir = Path(__file__).resolve().parents[2]
    cfg = Config(str(orchestrator_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(orchestrator_dir / "alembic"))
    return cfg


@pytest.fixture
def migrated_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "ca.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("OPENSAIL_HOME", str(tmp_path / "studio-home"))
    monkeypatch.setenv("DEPLOYMENT_MODE", "desktop")

    from app.config import get_settings

    get_settings.cache_clear()
    orchestrator_dir = Path(__file__).resolve().parents[2]
    original = os.getcwd()
    os.chdir(orchestrator_dir)
    try:
        command.upgrade(_alembic_cfg(), "head")
    finally:
        os.chdir(original)
    yield url
    get_settings.cache_clear()


def _make_user() -> Mock:
    user = Mock()
    user.id = uuid.uuid4()
    user.default_team_id = None
    user.is_superuser = False
    return user


async def _seed_chat_with_workspace(maker, user_id):
    from app.models import Chat, Project

    async with maker() as db:
        project = Project(
            name="ws-1",
            slug=f"ws-{uuid.uuid4().hex[:6]}",
            owner_id=user_id,
            team_id=None,
            project_kind="workspace",
            compute_tier="none",
            environment_status="active",
            created_via="empty",
        )
        db.add(project)
        await db.flush()
        chat = Chat(
            id=uuid.uuid4(),
            user_id=user_id,
            project_id=project.id,
            title="t",
            origin="standalone",
        )
        db.add(chat)
        await db.commit()
        await db.refresh(project)
        await db.refresh(chat)
        return chat.id, project.id


async def _seed_standalone_chat(maker, user_id):
    from app.models import Chat

    async with maker() as db:
        chat = Chat(
            id=uuid.uuid4(),
            user_id=user_id,
            project_id=None,
            title="t",
            origin="standalone",
        )
        db.add(chat)
        await db.commit()
        return chat.id


def _make_upload(name: str, content: bytes, content_type: str = "text/plain") -> UploadFile:
    bio = BytesIO(content)
    return UploadFile(filename=name, file=bio, headers={"content-type": content_type})


def test_upload_rejects_chat_without_workspace(migrated_sqlite, tmp_path: Path) -> None:
    from app.routers.chat_attachments import upload_chat_attachment

    engine = create_async_engine(migrated_sqlite, future=True)
    _install_sqlite_now(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    user = _make_user()

    async def _run() -> object:
        chat_id = await _seed_standalone_chat(maker, user.id)
        async with maker() as db:
            up = _make_upload("note.txt", b"hello")
            return await upload_chat_attachment(chat_id, up, current_user=user, db=db)

    res = asyncio.run(_run())
    # JSONResponse(status_code=409, content={...})
    assert res.status_code == 409
    body = res.body.decode("utf-8")
    assert "no_workspace" in body

    asyncio.run(engine.dispose())


def test_upload_writes_file_and_inserts_row(migrated_sqlite, tmp_path: Path) -> None:
    from app.models import ChatAttachment
    from app.routers.chat_attachments import upload_chat_attachment

    engine = create_async_engine(migrated_sqlite, future=True)
    _install_sqlite_now(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    user = _make_user()

    async def _run() -> dict:
        chat_id, _ = await _seed_chat_with_workspace(maker, user.id)
        async with maker() as db:
            up = _make_upload("hello.txt", b"hello world")
            return await upload_chat_attachment(chat_id, up, current_user=user, db=db)

    result = asyncio.run(_run())
    assert isinstance(result, dict)
    assert result["filename"] == "hello.txt"
    assert result["size_bytes"] == len(b"hello world")
    assert result["sha256"] is not None
    assert os.path.exists(result["file_path"])

    async def _check_row():
        async with maker() as db:
            rows = await db.execute(
                select(ChatAttachment).where(
                    ChatAttachment.id == uuid.UUID(result["attachment_id"])
                )
            )
            return rows.scalar_one()

    row = asyncio.run(_check_row())
    assert row.message_id is None  # orphan until message saved
    assert row.size_bytes == len(b"hello world")

    asyncio.run(engine.dispose())


def test_upload_streaming_aborts_on_oversized_file(migrated_sqlite, tmp_path: Path) -> None:
    """Upload of a 26 MB body must 413 even when Content-Length is missing.

    Mirrors the "lying Content-Length" defense from the plan: the streaming
    write counts bytes and aborts past the cap, leaving no partial file.
    """
    from app.routers.chat_attachments import (
        MAX_ATTACHMENT_BYTES,
        upload_chat_attachment,
    )

    engine = create_async_engine(migrated_sqlite, future=True)
    _install_sqlite_now(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    user = _make_user()

    async def _run() -> object:
        chat_id, _ = await _seed_chat_with_workspace(maker, user.id)
        async with maker() as db:
            big = b"\x00" * (MAX_ATTACHMENT_BYTES + 1024)
            up = UploadFile(filename="big.bin", file=BytesIO(big))
            return await upload_chat_attachment(chat_id, up, current_user=user, db=db)

    res = asyncio.run(_run())
    assert getattr(res, "status_code", None) == 413
    body = res.body.decode("utf-8")
    assert "file_too_large" in body

    asyncio.run(engine.dispose())


def test_upload_accepts_any_extension(migrated_sqlite, tmp_path: Path) -> None:
    """No mime allowlist — .exe / .zip / .bin / no-extension all accepted."""
    from app.routers.chat_attachments import upload_chat_attachment

    engine = create_async_engine(migrated_sqlite, future=True)
    _install_sqlite_now(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    user = _make_user()

    async def _run_one(name: str) -> dict:
        chat_id, _ = await _seed_chat_with_workspace(maker, user.id)
        async with maker() as db:
            up = _make_upload(name, b"payload-bytes", content_type="application/octet-stream")
            return await upload_chat_attachment(chat_id, up, current_user=user, db=db)

    for name in ("payload.exe", "archive.zip", "blob.bin", "no-extension"):
        result = asyncio.run(_run_one(name))
        assert result["filename"] == name
        assert os.path.exists(result["file_path"])

    asyncio.run(engine.dispose())


def test_orphan_gc_prunes_old_unbound_rows(migrated_sqlite, tmp_path: Path) -> None:
    """Rows older than the cutoff with ``message_id=NULL`` get pruned."""
    from app.models import ChatAttachment
    from app.routers.chat_attachments import gc_orphan_chat_attachments

    engine = create_async_engine(migrated_sqlite, future=True)
    _install_sqlite_now(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    user = _make_user()

    async def _setup() -> tuple[Path, Path]:
        chat_id, _ = await _seed_chat_with_workspace(maker, user.id)
        async with maker() as db:
            old_path = tmp_path / "old.bin"
            old_path.write_bytes(b"old")
            new_path = tmp_path / "new.bin"
            new_path.write_bytes(b"new")
            old_row = ChatAttachment(
                chat_id=chat_id,
                user_id=user.id,
                message_id=None,
                file_path=str(old_path),
                original_filename="old.bin",
                sha256="a" * 64,
                mime_type="application/octet-stream",
                size_bytes=3,
                created_at=datetime.now(UTC) - timedelta(days=2),
            )
            new_row = ChatAttachment(
                chat_id=chat_id,
                user_id=user.id,
                message_id=None,
                file_path=str(new_path),
                original_filename="new.bin",
                sha256="b" * 64,
                mime_type="application/octet-stream",
                size_bytes=3,
                created_at=datetime.now(UTC),
            )
            db.add(old_row)
            db.add(new_row)
            await db.commit()
            return old_path, new_path

    old_path, new_path = asyncio.run(_setup())

    async def _gc() -> int:
        async with maker() as db:
            return await gc_orphan_chat_attachments(db)

    pruned = asyncio.run(_gc())
    assert pruned == 1
    assert not old_path.exists()
    assert new_path.exists()

    asyncio.run(engine.dispose())
