"""Tests for _auto_title_chat in worker.py."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.worker import _auto_title_chat


async def _mock_chat_generator(*chunks):
    """Create an async generator that yields chunks."""

    async def gen(*args, **kwargs):
        for c in chunks:
            yield c

    return gen


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.commit = AsyncMock()
    return db


@pytest.fixture
def mock_chat():
    chat = MagicMock()
    chat.id = uuid4()
    chat.title = None
    return chat


@pytest.fixture
def mock_adapter():
    adapter = MagicMock()

    async def fake_chat(messages, **kwargs):
        yield "Fix login page"

    adapter.chat = fake_chat
    return adapter


@pytest.mark.asyncio
async def test_sets_title_on_first_message(mock_chat, mock_adapter, mock_db):
    """Title is generated and saved when chat has no title."""
    await _auto_title_chat(mock_chat, mock_adapter, "Please fix my login page", mock_db)

    assert mock_chat.title == "Fix login page"
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_skips_when_title_exists(mock_chat, mock_adapter, mock_db):
    """No LLM call when chat already has a title."""
    mock_chat.title = "Existing Title"

    await _auto_title_chat(mock_chat, mock_adapter, "some message", mock_db)

    assert mock_chat.title == "Existing Title"
    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_skips_when_chat_is_none(mock_adapter, mock_db):
    """Handles None chat gracefully."""
    await _auto_title_chat(None, mock_adapter, "some message", mock_db)
    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_strips_quotes(mock_chat, mock_db):
    """Quotes around title are stripped."""
    adapter = MagicMock()

    async def fake_chat(messages, **kwargs):
        yield '"Fix login page"'

    adapter.chat = fake_chat

    await _auto_title_chat(mock_chat, adapter, "fix my login", mock_db)

    assert mock_chat.title == "Fix login page"


@pytest.mark.asyncio
async def test_truncates_long_title(mock_chat, mock_db):
    """Titles longer than 100 chars are truncated."""
    adapter = MagicMock()
    long_title = "A" * 150

    async def fake_chat(messages, **kwargs):
        yield long_title

    adapter.chat = fake_chat

    await _auto_title_chat(mock_chat, adapter, "message", mock_db)

    assert len(mock_chat.title) == 100


@pytest.mark.asyncio
async def test_llm_failure_does_not_crash(mock_chat, mock_db):
    """LLM errors are caught — title stays None, no exception raised."""
    adapter = MagicMock()

    async def fail_chat(messages, **kwargs):
        raise RuntimeError("LLM is down")
        yield  # make it a generator  # noqa: E501

    adapter.chat = fail_chat

    await _auto_title_chat(mock_chat, adapter, "message", mock_db)

    assert mock_chat.title is None
    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_response_does_not_set_title(mock_chat, mock_db):
    """Empty LLM response leaves title as None."""
    adapter = MagicMock()

    async def empty_chat(messages, **kwargs):
        yield "   "

    adapter.chat = empty_chat

    await _auto_title_chat(mock_chat, adapter, "message", mock_db)

    assert mock_chat.title is None
    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_multi_chunk_response(mock_chat, mock_db):
    """Multiple chunks are concatenated into one title."""
    adapter = MagicMock()

    async def multi_chat(messages, **kwargs):
        yield "Fix "
        yield "login "
        yield "page"

    adapter.chat = multi_chat

    await _auto_title_chat(mock_chat, adapter, "fix my login", mock_db)

    assert mock_chat.title == "Fix login page"
