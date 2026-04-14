"""GUID TypeDecorator round-trips on SQLite (Postgres tested in integration)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Column, MetaData, Table, insert, select
from sqlalchemy.ext.asyncio import create_async_engine

from app.types.guid import GUID


@pytest.mark.asyncio
async def test_guid_roundtrip_sqlite() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    metadata = MetaData()
    t = Table("t", metadata, Column("id", GUID(), primary_key=True))

    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
        uid = uuid.uuid4()
        await conn.execute(insert(t).values(id=uid))
        rows = (await conn.execute(select(t.c.id))).all()

    assert rows == [(uid,)]
    assert isinstance(rows[0][0], uuid.UUID)
    await engine.dispose()


@pytest.mark.asyncio
async def test_guid_accepts_string_input() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    metadata = MetaData()
    t = Table("t", metadata, Column("id", GUID(), primary_key=True))

    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
        uid_str = str(uuid.uuid4())
        await conn.execute(insert(t).values(id=uid_str))
        rows = (await conn.execute(select(t.c.id))).all()

    assert rows[0][0] == uuid.UUID(uid_str)
    await engine.dispose()


def test_guid_null_passthrough() -> None:
    g = GUID()

    class _Dialect:
        name = "sqlite"

    assert g.process_bind_param(None, _Dialect()) is None
    assert g.process_result_value(None, _Dialect()) is None
