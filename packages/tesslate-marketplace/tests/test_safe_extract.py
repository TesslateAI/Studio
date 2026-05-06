"""Path-traversal safety — malicious tar.zst archives are rejected."""

from __future__ import annotations

import io
import tarfile

import pytest
import zstandard

from app.services.install_check import (
    BundleValidationError,
    safe_extract,
    write_tar_zst,
)


def _build_tar_zst(members: list[tuple[str, bytes]], *, write_mode: str = "w:") -> bytes:
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode=write_mode) as tf:
        for name, data in members:
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mode = 0o644
            tf.addfile(info, io.BytesIO(data))
    cctx = zstandard.ZstdCompressor()
    return cctx.compress(tar_buffer.getvalue())


def test_safe_extract_round_trip(tmp_path):
    blob = write_tar_zst({"hello.txt": b"world", "nested/dir/file.json": b"{}"})
    archive = tmp_path / "bundle.tar.zst"
    archive.write_bytes(blob)
    dest = tmp_path / "out"
    members = safe_extract(archive, dest)
    assert (dest / "hello.txt").read_bytes() == b"world"
    assert (dest / "nested" / "dir" / "file.json").read_bytes() == b"{}"
    assert "hello.txt" in members


def test_safe_extract_rejects_parent_traversal(tmp_path):
    blob = _build_tar_zst([("../../etc/passwd", b"root:x:0:0:")])
    archive = tmp_path / "evil.tar.zst"
    archive.write_bytes(blob)
    with pytest.raises(BundleValidationError):
        safe_extract(archive, tmp_path / "out")


def test_safe_extract_rejects_absolute_path(tmp_path):
    blob = _build_tar_zst([("/tmp/yikes", b"oops")])
    archive = tmp_path / "evil.tar.zst"
    archive.write_bytes(blob)
    with pytest.raises(BundleValidationError):
        safe_extract(archive, tmp_path / "out")
