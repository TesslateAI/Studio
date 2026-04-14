"""Unit tests for project sync service helpers."""
from __future__ import annotations

import pytest

import app.models  # noqa: F401
from app.services.public.sync_service import (
    FilesystemSyncStorage,
    compute_blob_key,
    detect_conflicts,
)


def test_compute_blob_key_is_sha256():
    key = compute_blob_key(b"hello")
    assert len(key) == 64
    assert key == compute_blob_key(b"hello")
    assert key != compute_blob_key(b"world")


def test_detect_conflicts_none_when_cloud_empty():
    assert detect_conflicts({"a.txt": "h1"}, {}) == []
    assert detect_conflicts({"a.txt": "h1"}, None) == []


def test_detect_conflicts_flags_divergent_paths():
    incoming = {"a.txt": "new", "b.txt": "same"}
    cloud = {"a.txt": "old", "b.txt": "same"}
    result = detect_conflicts(incoming, cloud)
    assert len(result) == 1
    assert result[0]["path"] == "a.txt"
    assert result[0]["cloud_hash"] == "old"
    assert result[0]["incoming_hash"] == "new"


def test_detect_conflicts_ignores_one_sided_files():
    incoming = {"a.txt": "h1", "only-client.txt": "hx"}
    cloud = {"a.txt": "h1", "only-cloud.txt": "hy"}
    assert detect_conflicts(incoming, cloud) == []


@pytest.mark.asyncio
async def test_filesystem_storage_put_get_roundtrip(tmp_path):
    storage = FilesystemSyncStorage(root=str(tmp_path))
    key = compute_blob_key(b"payload")
    await storage.put(key, b"payload")
    assert await storage.exists(key) is True
    assert await storage.get(key) == b"payload"


@pytest.mark.asyncio
async def test_filesystem_storage_get_missing_raises(tmp_path):
    storage = FilesystemSyncStorage(root=str(tmp_path))
    with pytest.raises(FileNotFoundError):
        await storage.get("0" * 64)
