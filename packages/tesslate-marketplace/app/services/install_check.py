"""
Bundle integrity + safe extraction.

Three checks every bundle goes through:
1. **Size** — `len(data) <= max_bundle_size_bytes[kind]`.
2. **Archive format** — currently only `tar.zst` is supported.
3. **Path traversal** — extraction rejects any tar entry whose normalised
   destination escapes the target directory or is absolute.

`safe_extract` is intentionally exposed at module scope so unit tests can drive
it with adversarial archives.
"""

from __future__ import annotations

import hashlib
import io
import os
import tarfile
from pathlib import Path
from typing import IO, NamedTuple

import zstandard

from ..config import DEFAULT_MAX_BUNDLE_SIZE_BYTES


class BundleValidationError(ValueError):
    """Raised when a bundle fails one of the install_check gates."""


class BundleStats(NamedTuple):
    sha256: str
    size_bytes: int


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_bundle_size(kind: str, size_bytes: int) -> None:
    cap = DEFAULT_MAX_BUNDLE_SIZE_BYTES.get(kind)
    if cap is None:
        raise BundleValidationError(f"no size policy registered for kind={kind!r}")
    if size_bytes > cap:
        raise BundleValidationError(
            f"bundle for kind={kind!r} is {size_bytes} bytes; cap is {cap}"
        )


def validate_archive_format(archive_format: str) -> None:
    if archive_format != "tar.zst":
        raise BundleValidationError(
            f"unsupported archive_format={archive_format!r}; only tar.zst is allowed"
        )


def _is_within(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def _resolve_safe(target: Path, member: tarfile.TarInfo) -> Path:
    name = member.name
    # Normalise OS separators just in case a Windows-built archive is consumed.
    normalised = name.replace("\\", "/")
    if normalised.startswith("/") or os.path.isabs(normalised):
        raise BundleValidationError(f"absolute path inside archive: {name!r}")
    if any(part == ".." for part in normalised.split("/")):
        # Stop early before resolution — a parent-traversal segment is enough
        # signal even if the resolved target happens to land inside.
        raise BundleValidationError(f"parent traversal segment in archive entry: {name!r}")
    candidate = (target / normalised).resolve()
    target_resolved = target.resolve()
    if not _is_within(target_resolved, candidate):
        raise BundleValidationError(f"archive entry escapes destination: {name!r}")
    return candidate


def safe_extract(archive_path: str | Path, dest_dir: str | Path) -> list[str]:
    """Extract a tar.zst archive into `dest_dir`.

    Refuses any entry whose normalised destination is absolute or escapes the
    destination root, including symlinks/hardlinks pointing outside.

    Returns the list of extracted member names (relative paths).
    """
    archive = Path(archive_path)
    target = Path(dest_dir)
    target.mkdir(parents=True, exist_ok=True)

    decompressor = zstandard.ZstdDecompressor()
    with archive.open("rb") as src:
        decompressed = decompressor.stream_reader(src)
        # tarfile does not accept arbitrary readers — wrap in a BufferedReader.
        with tarfile.open(fileobj=io.BufferedReader(decompressed), mode="r|") as tf:
            extracted: list[str] = []
            for member in tf:
                # Reject anything that isn't a regular file, dir, or symlink.
                if not (member.isreg() or member.isdir() or member.islnk() or member.issym()):
                    raise BundleValidationError(
                        f"unsupported tar member type ({member.type}): {member.name!r}"
                    )
                safe_path = _resolve_safe(target, member)
                if member.isdir():
                    safe_path.mkdir(parents=True, exist_ok=True)
                    extracted.append(member.name)
                    continue
                if member.issym() or member.islnk():
                    link_target = (safe_path.parent / member.linkname).resolve()
                    if not _is_within(target.resolve(), link_target):
                        raise BundleValidationError(
                            f"link target escapes destination: {member.name!r} -> {member.linkname!r}"
                        )
                    safe_path.parent.mkdir(parents=True, exist_ok=True)
                    if safe_path.exists() or safe_path.is_symlink():
                        safe_path.unlink()
                    if member.issym():
                        os.symlink(member.linkname, safe_path)
                    else:
                        # tarfile cannot replay hardlinks across an extraction
                        # boundary easily; copy the bytes from the link target
                        # within the destination.
                        link_path = (target / member.linkname.lstrip("/")).resolve()
                        if not _is_within(target.resolve(), link_path) or not link_path.exists():
                            raise BundleValidationError(
                                f"hardlink target outside destination: {member.linkname!r}"
                            )
                        safe_path.write_bytes(link_path.read_bytes())
                    extracted.append(member.name)
                    continue
                # Regular file
                safe_path.parent.mkdir(parents=True, exist_ok=True)
                extracted_file = tf.extractfile(member)
                assert extracted_file is not None
                with safe_path.open("wb") as out:
                    while True:
                        chunk = extracted_file.read(64 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
                if member.mode:
                    # Strip group/other write bits for safety; preserve user perms.
                    os.chmod(safe_path, member.mode & 0o755)
                extracted.append(member.name)
    return extracted


def write_tar_zst(members: dict[str, bytes]) -> bytes:
    """Build a tar.zst archive from {filename: bytes} mapping. Used by the
    seed-bundle builder."""
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w:") as tf:
        for name, data in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mode = 0o644
            tf.addfile(info, io.BytesIO(data))
    cctx = zstandard.ZstdCompressor(level=10)
    return cctx.compress(tar_buffer.getvalue())


def read_tar_zst(data: bytes) -> dict[str, bytes]:
    """Round-trip helper used in tests."""
    dctx = zstandard.ZstdDecompressor()
    decompressed = dctx.decompress(data)
    out: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(decompressed), mode="r:") as tf:
        for member in tf:
            if not member.isreg():
                continue
            f: IO[bytes] | None = tf.extractfile(member)
            if f is None:
                continue
            out[member.name] = f.read()
    return out


def stat_bundle(data: bytes) -> BundleStats:
    return BundleStats(sha256=compute_sha256(data), size_bytes=len(data))
