"""
Integration tests for the ``view_image`` tool.
"""

from __future__ import annotations

import base64
import struct
import zlib
from pathlib import Path

import pytest

from app.agent.tools.file_ops.view_image import MAX_IMAGE_BYTES, view_image_tool

pytestmark = pytest.mark.asyncio


def _png_1x1() -> bytes:
    """Build a valid 1x1 red PNG from scratch (no external deps)."""
    signature = b"\x89PNG\r\n\x1a\n"

    def _chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = _chunk(
        b"IHDR",
        struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0),  # width, height, 8-bit RGB
    )
    # One scanline: filter byte 0, then R G B.
    raw = b"\x00\xff\x00\x00"
    idat = _chunk(b"IDAT", zlib.compress(raw))
    iend = _chunk(b"IEND", b"")
    return signature + ihdr + idat + iend


async def test_view_image_round_trip_png(
    bound_orchestrator, project_root: Path, fops_context
) -> None:
    png = _png_1x1()
    (project_root / "img.png").write_bytes(png)

    result = await view_image_tool({"path": "img.png"}, fops_context)

    assert result["success"] is True
    parts = result["content_parts"]
    assert len(parts) == 2
    image_part = parts[0]
    assert image_part["type"] == "image"
    assert image_part["source"]["media_type"] == "image/png"

    data = image_part["source"]["data"]
    decoded = base64.b64decode(data)
    assert decoded == png

    assert parts[1]["type"] == "text"
    assert "img.png" in parts[1]["text"]
    assert result["details"]["size_bytes"] == len(png)


async def test_view_image_missing_file(bound_orchestrator, fops_context) -> None:
    result = await view_image_tool({"path": "nope.png"}, fops_context)
    assert result["success"] is False
    assert "does not exist" in result["message"]


async def test_view_image_unsupported_extension(
    bound_orchestrator, project_root: Path, fops_context
) -> None:
    (project_root / "data.bin").write_bytes(b"not an image")
    result = await view_image_tool({"path": "data.bin"}, fops_context)
    assert result["success"] is False
    assert "Unsupported image type" in result["message"]


async def test_view_image_vision_disabled(
    bound_orchestrator, project_root: Path, fops_context
) -> None:
    (project_root / "img.png").write_bytes(_png_1x1())
    fops_context["model_supports_vision"] = False
    result = await view_image_tool({"path": "img.png"}, fops_context)
    assert result["success"] is False
    assert "does not support vision" in result["message"]


async def test_view_image_too_large(
    bound_orchestrator, project_root: Path, fops_context, monkeypatch
) -> None:
    huge = project_root / "huge.png"
    huge.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * (MAX_IMAGE_BYTES + 1))
    result = await view_image_tool({"path": "huge.png"}, fops_context)
    assert result["success"] is False
    assert "exceeds" in result["message"]


async def test_view_image_invalid_detail(
    bound_orchestrator, project_root: Path, fops_context
) -> None:
    (project_root / "img.png").write_bytes(_png_1x1())
    result = await view_image_tool({"path": "img.png", "detail": "ultra"}, fops_context)
    assert result["success"] is False
    assert "Invalid detail" in result["message"]
