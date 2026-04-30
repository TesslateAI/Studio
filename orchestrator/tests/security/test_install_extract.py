"""
Malicious-archive corpus + tests for ``services.install_extract.safe_extract``.

Each test builds an adversarial ``tar.zst`` (or sibling format) with a known
attack pattern and asserts the extractor refuses it with the right
:class:`UnsafeArchiveError` reason. A control test verifies a clean archive
extracts cleanly.

The corpus is built by fixture functions (not checked-in binaries) so the
malicious payloads regenerate on every test run from auditable Python code.
The fixture writes artefacts into ``tests/security/fixtures/malicious_archives/``
so they're inspectable when a test fails — but the directory is regenerated
fresh in each session.
"""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest
import zstandard

from app.services.install_extract import (
    ArchiveTooLargeError,
    ExtractionResult,
    UnsafeArchiveError,
    UnsupportedArchiveFormatError,
    safe_extract,
)


# ---------------------------------------------------------------------------
# Corpus directory
# ---------------------------------------------------------------------------


_CORPUS_DIR = Path(__file__).parent / "fixtures" / "malicious_archives"


@pytest.fixture(scope="session", autouse=True)
def _ensure_corpus_dir():
    """Make sure the corpus dir exists; rebuild every session."""
    _CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    yield


@pytest.fixture
def dest_root(tmp_path: Path) -> Path:
    out = tmp_path / "extract"
    out.mkdir()
    return out


# ---------------------------------------------------------------------------
# Helpers — build malicious archives in-memory and write to corpus dir
# ---------------------------------------------------------------------------


def _zstd_compress(buf: bytes) -> bytes:
    return zstandard.ZstdCompressor(level=10).compress(buf)


def _build_tar(entries: list[tarfile.TarInfo], file_data: dict[str, bytes]) -> bytes:
    """Build a tar archive (uncompressed) from raw TarInfo + file_data dict."""
    out = io.BytesIO()
    # Write in stream mode so PAX headers don't sneak in via tarfile defaults.
    with tarfile.open(fileobj=out, mode="w:") as tf:
        for info in entries:
            data = file_data.get(info.name, b"")
            if info.type == tarfile.REGTYPE:
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
            else:
                # symlinks / hardlinks / dirs carry no payload.
                info.size = 0
                tf.addfile(info)
    return out.getvalue()


def _write_corpus(name: str, data: bytes) -> Path:
    p = _CORPUS_DIR / name
    p.write_bytes(data)
    return p


# ---------------------------------------------------------------------------
# Corpus fixtures — one per attack pattern + a happy-path control.
# ---------------------------------------------------------------------------


@pytest.fixture
def parent_traversal_archive() -> Path:
    info = tarfile.TarInfo(name="../../../etc/passwd")
    info.type = tarfile.REGTYPE
    info.mode = 0o644
    payload = _build_tar([info], {"../../../etc/passwd": b"pwned\n"})
    return _write_corpus("parent_traversal.tar.zst", _zstd_compress(payload))


@pytest.fixture
def absolute_path_archive() -> Path:
    info = tarfile.TarInfo(name="/tmp/pwned")
    info.type = tarfile.REGTYPE
    info.mode = 0o644
    payload = _build_tar([info], {"/tmp/pwned": b"pwned\n"})
    return _write_corpus("absolute_path.tar.zst", _zstd_compress(payload))


@pytest.fixture
def symlink_escape_archive() -> Path:
    # Symlink whose linkname climbs out of the destination root.
    info = tarfile.TarInfo(name="inside")
    info.type = tarfile.SYMTYPE
    info.linkname = "../../../../etc/passwd"
    info.mode = 0o777
    payload = _build_tar([info], {})
    return _write_corpus("symlink_escape.tar.zst", _zstd_compress(payload))


@pytest.fixture
def hardlink_escape_archive() -> Path:
    info = tarfile.TarInfo(name="link_to_outside")
    info.type = tarfile.LNKTYPE
    info.linkname = "../../etc/passwd"
    info.mode = 0o644
    payload = _build_tar([info], {})
    return _write_corpus("hardlink_escape.tar.zst", _zstd_compress(payload))


@pytest.fixture
def null_byte_archive() -> Path:
    """Build a tar.zst that smuggles a null byte in the entry name via PAX.

    POSIX ustar headers cap names at 100 bytes and treat NUL as the
    C-string terminator, so a NUL inside the regular ``name`` field is
    silently stripped on read. PAX extended headers (the modern superset
    tar uses for long names / unicode) carry the path as a UTF-8 string
    in a separate header block — and tarfile preserves null bytes there.
    This is the realistic shape of a "null byte name" attack against any
    extractor that has to support modern tar archives.
    """
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:", format=tarfile.PAX_FORMAT) as tf:
        info = tarfile.TarInfo(name="innocent.txt")
        info.type = tarfile.REGTYPE
        info.mode = 0o644
        info.size = 1
        info.pax_headers = {"path": "evil\x00name.txt"}
        tf.addfile(info, io.BytesIO(b"x"))
    return _write_corpus("null_byte.tar.zst", _zstd_compress(out.getvalue()))


@pytest.fixture
def tar_bomb_archive() -> Path:
    """A small archive that decompresses to >1 GB.

    Build a tar containing a single declared-massive file. We physically
    write 4 MB of zeros (well above the typical truncation buffer) — the
    streaming decompressor will only read what's there and the size guard
    must trip on the *member's declared size*, not the payload bytes.

    To make the payload pass tar's checksum validation we instead write a
    file whose physical size matches its declared size — but we set the
    declared size to >1 GB and feed real bytes (zeros, which compress to
    a few bytes under zstd). This produces a real bomb archive that's
    tiny on disk but explodes on extraction.
    """
    declared_size = 2 * 1024 * 1024 * 1024  # 2 GB > 1 GB max

    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:") as tf:
        info = tarfile.TarInfo(name="bomb.bin")
        info.type = tarfile.REGTYPE
        info.mode = 0o644
        info.size = declared_size
        # Stream zeros into the tar. Use ``addfile`` with a streaming
        # reader so we don't allocate 2 GB in memory.
        class _ZeroReader(io.RawIOBase):
            def __init__(self, n: int) -> None:
                self._remaining = n

            def readable(self) -> bool:
                return True

            def readinto(self, b: bytearray) -> int:  # type: ignore[override]
                if self._remaining <= 0:
                    return 0
                n = min(len(b), self._remaining)
                b[:n] = b"\x00" * n
                self._remaining -= n
                return n

        reader = io.BufferedReader(_ZeroReader(declared_size))
        tf.addfile(info, reader)

    payload = out.getvalue()
    # zstd compresses runs of zeros to ~few KB.
    compressed = _zstd_compress(payload)
    return _write_corpus("tar_bomb.tar.zst", compressed)


@pytest.fixture
def wrong_format_archive() -> Path:
    """A `.zip` file — must be rejected by extension AND magic check."""
    # Minimal zip header (PK\x03\x04...) so even a magic-byte check fails.
    zip_bytes = b"PK\x03\x04" + b"\x00" * 26 + b"hello"
    return _write_corpus("wrong_format.zip", zip_bytes)


@pytest.fixture
def valid_archive() -> Path:
    info = tarfile.TarInfo(name="manifest.json")
    info.type = tarfile.REGTYPE
    info.mode = 0o644
    payload = _build_tar([info], {"manifest.json": b'{"hello":"world"}'})
    return _write_corpus("valid.tar.zst", _zstd_compress(payload))


# ---------------------------------------------------------------------------
# Tests — happy path
# ---------------------------------------------------------------------------


def test_valid_archive_extracts_cleanly(valid_archive: Path, dest_root: Path) -> None:
    result = safe_extract(valid_archive, dest_root)
    assert isinstance(result, ExtractionResult)
    extracted = dest_root / "manifest.json"
    assert extracted.is_file()
    assert extracted.read_bytes() == b'{"hello":"world"}'
    assert result.files == 1
    assert result.dirs == 0
    assert result.symlinks == 0
    assert result.total_uncompressed_bytes == len(b'{"hello":"world"}')
    # File mode strips group/other write + setuid/setgid bits.
    mode = extracted.stat().st_mode & 0o777
    assert mode & 0o022 == 0  # no group/world write
    assert mode & 0o4000 == 0  # no setuid


# ---------------------------------------------------------------------------
# Tests — the corpus
# ---------------------------------------------------------------------------


def test_parent_traversal_rejected(parent_traversal_archive: Path, dest_root: Path) -> None:
    with pytest.raises(UnsafeArchiveError) as exc_info:
        safe_extract(parent_traversal_archive, dest_root)
    assert exc_info.value.reason == "parent_traversal"
    # /etc/passwd MUST NOT exist or be modified.
    assert not (dest_root / ".." / ".." / ".." / "etc" / "passwd").exists()


def test_absolute_path_rejected(absolute_path_archive: Path, dest_root: Path) -> None:
    with pytest.raises(UnsafeArchiveError) as exc_info:
        safe_extract(absolute_path_archive, dest_root)
    assert exc_info.value.reason == "absolute_path"


def test_symlink_escape_rejected(symlink_escape_archive: Path, dest_root: Path) -> None:
    with pytest.raises(UnsafeArchiveError) as exc_info:
        safe_extract(symlink_escape_archive, dest_root)
    assert exc_info.value.reason == "symlink_escapes_destination"
    # Symlink MUST NOT exist on disk.
    assert not (dest_root / "inside").is_symlink()


def test_hardlink_escape_rejected(hardlink_escape_archive: Path, dest_root: Path) -> None:
    with pytest.raises(UnsafeArchiveError) as exc_info:
        safe_extract(hardlink_escape_archive, dest_root)
    assert exc_info.value.reason == "hardlink_escapes_destination"


def test_null_byte_rejected(null_byte_archive: Path, dest_root: Path) -> None:
    with pytest.raises(UnsafeArchiveError) as exc_info:
        safe_extract(null_byte_archive, dest_root)
    assert exc_info.value.reason == "null_byte"


def test_tar_bomb_rejected(tar_bomb_archive: Path, dest_root: Path) -> None:
    """Declared 2 GB file must trip the 1 GB max early — before write."""
    with pytest.raises(ArchiveTooLargeError) as exc_info:
        safe_extract(tar_bomb_archive, dest_root, max_uncompressed_bytes=1024 * 1024 * 1024)
    assert exc_info.value.reason == "archive_too_large"
    assert exc_info.value.max_bytes == 1024 * 1024 * 1024
    assert exc_info.value.total_bytes > exc_info.value.max_bytes
    # No partial output should leak — bomb.bin must not exist or be empty.
    bomb_out = dest_root / "bomb.bin"
    if bomb_out.exists():
        # Allowed if the size guard tripped *during* write — but it must
        # be small (<= chunk size), not the full 2 GB.
        assert bomb_out.stat().st_size < 1024 * 1024


def test_wrong_format_rejected(wrong_format_archive: Path, dest_root: Path) -> None:
    with pytest.raises(UnsupportedArchiveFormatError) as exc_info:
        safe_extract(wrong_format_archive, dest_root)
    assert exc_info.value.reason == "unsupported_format"
    assert exc_info.value.detected == "zip"


# ---------------------------------------------------------------------------
# Bonus tests — additional defence-in-depth checks
# ---------------------------------------------------------------------------


def test_renamed_zip_rejected_by_magic_bytes(tmp_path: Path, dest_root: Path) -> None:
    """A zip renamed to .tar.zst is caught by the magic-byte sniff."""
    fake = tmp_path / "lying.tar.zst"
    fake.write_bytes(b"PK\x03\x04" + b"\x00" * 100)
    with pytest.raises(UnsupportedArchiveFormatError) as exc_info:
        safe_extract(fake, dest_root)
    assert "bad_magic" in exc_info.value.detected


def test_missing_archive_rejected(tmp_path: Path, dest_root: Path) -> None:
    with pytest.raises(UnsafeArchiveError) as exc_info:
        safe_extract(tmp_path / "does_not_exist.tar.zst", dest_root)
    assert exc_info.value.reason == "io_error"


def test_dot_dot_in_middle_segment_rejected(dest_root: Path, tmp_path: Path) -> None:
    """Even ``a/../../b`` is refused — the syntactic check is strict."""
    info = tarfile.TarInfo(name="a/../../etc/x")
    info.type = tarfile.REGTYPE
    info.mode = 0o644
    payload = _build_tar([info], {"a/../../etc/x": b"hi"})
    archive = tmp_path / "mid.tar.zst"
    archive.write_bytes(_zstd_compress(payload))
    with pytest.raises(UnsafeArchiveError) as exc_info:
        safe_extract(archive, dest_root)
    assert exc_info.value.reason == "parent_traversal"


def test_setuid_bit_stripped(tmp_path: Path, dest_root: Path) -> None:
    info = tarfile.TarInfo(name="evil")
    info.type = tarfile.REGTYPE
    info.mode = 0o4755  # setuid
    payload = _build_tar([info], {"evil": b"hi"})
    archive = tmp_path / "suid.tar.zst"
    archive.write_bytes(_zstd_compress(payload))
    safe_extract(archive, dest_root)
    out = dest_root / "evil"
    assert out.is_file()
    assert (out.stat().st_mode & 0o4000) == 0


def test_unsupported_member_type_rejected(tmp_path: Path, dest_root: Path) -> None:
    """Block devices / FIFOs / character devices are refused."""
    info = tarfile.TarInfo(name="dev")
    info.type = tarfile.CHRTYPE  # character device — never legitimate in a bundle
    info.mode = 0o600
    payload = _build_tar([info], {})
    archive = tmp_path / "chr.tar.zst"
    archive.write_bytes(_zstd_compress(payload))
    with pytest.raises(UnsafeArchiveError) as exc_info:
        safe_extract(archive, dest_root)
    assert exc_info.value.reason == "unsupported_member_type"
