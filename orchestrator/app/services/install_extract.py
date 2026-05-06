"""
Path-traversal-hardened tar.zst extractor for marketplace bundles.

Wave 6 makes this the **only** extraction path used by
``services/marketplace_installer.py``. The marketplace service has its own
copy at ``packages/tesslate-marketplace/app/services/install_check.py``;
the two implementations stay in sync but live in separate codebases
because the marketplace service and the orchestrator are deployed
independently.

Defense-in-depth: every layer below catches an attack the others might
miss. If you add new extraction logic, add new checks — never weaken
existing ones.

Checks per archive entry (in order):
  1. Reject anything that isn't a regular file, directory, symlink, or
     hardlink (no devices, no FIFOs).
  2. Reject names containing null bytes.
  3. Normalise path separators (Windows-built archives may use ``\\``).
  4. Reject absolute paths (``/foo`` or ``C:\\foo``) — names MUST be
     relative.
  5. Reject any explicit ``..`` segment in the name (refuse before
     resolution; some FS / symlink interactions can defeat resolve()).
  6. Resolve to an absolute path; reject if outside ``dest_root``
     (resolved).
  7. For symlinks/hardlinks: resolve link target relative to the entry's
     parent dir, then refuse if outside ``dest_root``.
  8. Track total uncompressed size; refuse if > ``max_uncompressed_bytes``
     (default 1 GB) — defense against tar/zip-bomb attacks.
  9. Strip setuid/setgid/world-write bits from extracted file modes.

Archive format restrictions:
  - Only ``tar.zst`` is accepted. zip / plain tar / gzip / bzip2 are
    rejected by extension AND by content signature.
"""

from __future__ import annotations

import io
import logging
import os
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import zstandard

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

DEFAULT_MAX_UNCOMPRESSED_BYTES: Final[int] = 1024 * 1024 * 1024  # 1 GB
_READ_CHUNK_BYTES: Final[int] = 64 * 1024
_ZSTD_MAGIC: Final[bytes] = b"\x28\xb5\x2f\xfd"


# ---------------------------------------------------------------------------
# Typed errors
# ---------------------------------------------------------------------------


class UnsafeArchiveError(Exception):
    """Raised whenever the extractor refuses to process an archive entry.

    ``reason`` is a stable machine-readable token (e.g. ``"parent_traversal"``,
    ``"absolute_path"``) so callers and tests can branch on it without
    string-matching the human message.
    """

    def __init__(self, reason: str, message: str, *, entry: str | None = None) -> None:
        super().__init__(f"{reason}: {message}" + (f" (entry={entry!r})" if entry else ""))
        self.reason = reason
        self.entry = entry
        self.message = message


class UnsupportedArchiveFormatError(UnsafeArchiveError):
    """Archive is not ``tar.zst`` (wrong extension or wrong magic bytes)."""

    def __init__(self, detected: str) -> None:
        super().__init__(
            "unsupported_format",
            f"only tar.zst is accepted; got {detected!r}",
        )
        self.detected = detected


class ArchiveTooLargeError(UnsafeArchiveError):
    """Total uncompressed size exceeds the per-extract maximum."""

    def __init__(self, total_bytes: int, max_bytes: int) -> None:
        super().__init__(
            "archive_too_large",
            f"uncompressed total {total_bytes} exceeds max {max_bytes}",
        )
        self.total_bytes = total_bytes
        self.max_bytes = max_bytes


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class ExtractionResult:
    """Summary of a successful :func:`safe_extract` call."""

    members: list[str] = field(default_factory=list)
    total_uncompressed_bytes: int = 0
    files: int = 0
    dirs: int = 0
    symlinks: int = 0
    hardlinks: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _detect_archive_format(archive_path: Path) -> str:
    """Sniff the archive format by extension AND magic bytes.

    Returns the canonical format name. Raises
    :class:`UnsupportedArchiveFormatError` if it's not ``tar.zst``.
    """
    name_lower = archive_path.name.lower()
    # Extension check first — cheap and gives a stable error message.
    if not (name_lower.endswith(".tar.zst") or name_lower.endswith(".tzst")):
        # Other common archive extensions surface explicitly.
        if name_lower.endswith(".zip"):
            raise UnsupportedArchiveFormatError("zip")
        if name_lower.endswith(".tar"):
            raise UnsupportedArchiveFormatError("tar")
        if name_lower.endswith(".tar.gz") or name_lower.endswith(".tgz"):
            raise UnsupportedArchiveFormatError("tar.gz")
        if name_lower.endswith(".tar.bz2"):
            raise UnsupportedArchiveFormatError("tar.bz2")
        if name_lower.endswith(".tar.xz"):
            raise UnsupportedArchiveFormatError("tar.xz")
        raise UnsupportedArchiveFormatError(name_lower.rsplit(".", 1)[-1])

    # Magic-bytes check — defends against an attacker renaming a zip to .tar.zst.
    try:
        with archive_path.open("rb") as f:
            head = f.read(4)
    except OSError as exc:
        raise UnsafeArchiveError(
            "io_error",
            f"failed to read archive header: {exc}",
        ) from exc
    if head != _ZSTD_MAGIC:
        raise UnsupportedArchiveFormatError(
            f"bad_magic:{head.hex()}",
        )
    return "tar.zst"


def _normalise_name(name: str) -> str:
    """Convert backslashes to forward slashes (Windows-built archives) and
    strip leading ``./`` segments. Does not resolve symlinks."""
    n = name.replace("\\", "/")
    while n.startswith("./"):
        n = n[2:]
    return n


def _check_no_null_byte(name: str) -> None:
    if "\x00" in name:
        raise UnsafeArchiveError(
            "null_byte",
            "archive entry name contains a null byte",
            entry=name,
        )


def _check_not_absolute(name: str) -> None:
    # Forward-slash absolute (POSIX).
    if name.startswith("/"):
        raise UnsafeArchiveError(
            "absolute_path",
            "archive entry uses an absolute POSIX path",
            entry=name,
        )
    # Windows drive-letter or UNC absolute (e.g. ``C:foo``, ``\\server\share``).
    # We've already converted ``\\`` to ``/`` so any remaining colon in the
    # first segment is a Windows-style absolute path.
    head = name.split("/", 1)[0]
    if ":" in head:
        raise UnsafeArchiveError(
            "absolute_path",
            "archive entry uses a Windows-style absolute path or device name",
            entry=name,
        )
    if os.path.isabs(name):
        raise UnsafeArchiveError(
            "absolute_path",
            "archive entry resolves as an absolute path on this OS",
            entry=name,
        )


def _check_no_parent_segment(name: str) -> None:
    parts = name.split("/")
    for part in parts:
        if part == "..":
            raise UnsafeArchiveError(
                "parent_traversal",
                "archive entry contains a parent-directory traversal segment",
                entry=name,
            )


def _resolve_within(dest_root: Path, name: str) -> Path:
    """Resolve ``dest_root / name`` and refuse if it escapes ``dest_root``.

    Uses ``Path.resolve(strict=False)`` so non-existent files (the common
    case at extraction time) work; the check is purely syntactic on the
    resolved path.
    """
    candidate = (dest_root / name).resolve(strict=False)
    root_resolved = dest_root.resolve(strict=False)
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        raise UnsafeArchiveError(
            "escapes_destination",
            f"resolved entry path {candidate!s} is outside destination {root_resolved!s}",
            entry=name,
        ) from None
    return candidate


def _check_link_target_safe(
    dest_root: Path, entry_name: str, link_target: str, kind: str
) -> Path:
    """Resolve a sym/hard link target relative to the entry's parent dir
    and refuse if it lands outside ``dest_root``.

    For absolute link targets (``linkname.startswith('/')``), refuse
    outright — links inside an extracted archive must be relative.
    """
    if "\x00" in link_target:
        raise UnsafeArchiveError(
            f"{kind}_null_byte",
            f"{kind} target contains a null byte",
            entry=entry_name,
        )
    normalised_target = link_target.replace("\\", "/")
    if normalised_target.startswith("/") or os.path.isabs(normalised_target):
        raise UnsafeArchiveError(
            f"{kind}_absolute_target",
            f"{kind} {entry_name!r} targets absolute path {link_target!r}",
            entry=entry_name,
        )
    if ":" in normalised_target.split("/", 1)[0]:
        raise UnsafeArchiveError(
            f"{kind}_absolute_target",
            f"{kind} {entry_name!r} targets Windows-style absolute path {link_target!r}",
            entry=entry_name,
        )
    # Resolve the target relative to the entry's *parent* dir, mirroring
    # how the OS would interpret the link after extraction.
    entry_path = (dest_root / entry_name).resolve(strict=False)
    parent = entry_path.parent
    resolved_target = (parent / normalised_target).resolve(strict=False)
    root_resolved = dest_root.resolve(strict=False)
    try:
        resolved_target.relative_to(root_resolved)
    except ValueError:
        raise UnsafeArchiveError(
            f"{kind}_escapes_destination",
            f"{kind} target {resolved_target!s} resolves outside {root_resolved!s}",
            entry=entry_name,
        ) from None
    return resolved_target


def _safe_mode(mode: int) -> int:
    """Strip setuid / setgid / sticky / world-write bits from a file mode.

    Caps at ``0o755`` so an extracted file is at most user-rwx + group/other-rx.
    """
    return mode & 0o755


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def safe_extract(
    archive_path: Path,
    dest_root: Path,
    *,
    max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
) -> ExtractionResult:
    """Extract ``archive_path`` (tar.zst) into ``dest_root`` safely.

    Refuses any entry that fails the path-traversal / absolute-path /
    null-byte / link-escape / size-bomb checks. ``dest_root`` is created
    if missing.

    Raises :class:`UnsafeArchiveError` (or subclass) on any violation.
    Returns :class:`ExtractionResult` on success.
    """
    archive = Path(archive_path)
    dest = Path(dest_root)

    if not archive.is_file():
        raise UnsafeArchiveError(
            "io_error",
            f"archive does not exist or is not a file: {archive!s}",
        )

    _detect_archive_format(archive)

    dest.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest.resolve(strict=False)

    result = ExtractionResult()

    decompressor = zstandard.ZstdDecompressor()
    with archive.open("rb") as src:
        with decompressor.stream_reader(src) as reader:
            buffered = io.BufferedReader(reader)
            # Streaming mode tar (``r|``) so we don't try to seek the
            # decompressed stream.
            with tarfile.open(fileobj=buffered, mode="r|") as tf:
                for member in tf:
                    name = member.name
                    _check_no_null_byte(name)

                    # Reject anything other than reg/dir/sym/hard.
                    if not (
                        member.isreg()
                        or member.isdir()
                        or member.issym()
                        or member.islnk()
                    ):
                        raise UnsafeArchiveError(
                            "unsupported_member_type",
                            f"member type {member.type!r} not allowed",
                            entry=name,
                        )

                    normalised = _normalise_name(name)
                    if not normalised:
                        # Skip the archive's own ``./`` root marker silently
                        # — it's harmless and common.
                        continue

                    _check_not_absolute(normalised)
                    _check_no_parent_segment(normalised)
                    safe_path = _resolve_within(dest_resolved, normalised)

                    # Ensure parent dir exists for files / links.
                    if not member.isdir():
                        safe_path.parent.mkdir(parents=True, exist_ok=True)

                    if member.isdir():
                        safe_path.mkdir(parents=True, exist_ok=True)
                        result.dirs += 1
                        result.members.append(normalised)
                        continue

                    if member.issym():
                        target = _check_link_target_safe(
                            dest_resolved, normalised, member.linkname, "symlink"
                        )
                        # Replace any pre-existing entry at that name.
                        if safe_path.exists() or safe_path.is_symlink():
                            safe_path.unlink()
                        os.symlink(member.linkname, safe_path)
                        result.symlinks += 1
                        result.members.append(normalised)
                        # Symlinks contribute 0 uncompressed bytes — the
                        # link target is what matters and we already
                        # validated it.
                        continue

                    if member.islnk():
                        # Hardlinks inside tar archives reference another
                        # archive entry by name. Refuse if the linkname
                        # points outside dest_root.
                        target_path = _check_link_target_safe(
                            dest_resolved, normalised, member.linkname, "hardlink"
                        )
                        # tarfile cannot replay hardlinks across an
                        # extraction boundary easily; if the target file
                        # was already extracted, hardlink to it; otherwise
                        # refuse — out-of-order hardlinks suggest a
                        # malicious archive.
                        if not target_path.is_file():
                            raise UnsafeArchiveError(
                                "hardlink_dangling",
                                f"hardlink target not present in archive: {member.linkname!r}",
                                entry=normalised,
                            )
                        if safe_path.exists() or safe_path.is_symlink():
                            safe_path.unlink()
                        os.link(target_path, safe_path)
                        result.hardlinks += 1
                        result.members.append(normalised)
                        continue

                    # Regular file
                    size = int(member.size)
                    if size < 0:
                        raise UnsafeArchiveError(
                            "negative_size",
                            f"member declares negative size {size}",
                            entry=normalised,
                        )
                    # Pre-check size before allocating space.
                    projected_total = result.total_uncompressed_bytes + size
                    if projected_total > max_uncompressed_bytes:
                        raise ArchiveTooLargeError(projected_total, max_uncompressed_bytes)

                    extracted_file = tf.extractfile(member)
                    if extracted_file is None:
                        # Some pseudo-regular files (e.g. PAX headers) report
                        # isreg() but yield None — skip them.
                        continue

                    bytes_written = 0
                    with safe_path.open("wb") as out:
                        while True:
                            chunk = extracted_file.read(_READ_CHUNK_BYTES)
                            if not chunk:
                                break
                            bytes_written += len(chunk)
                            # Re-check inside the loop so a header that lies
                            # about its size still can't bomb us.
                            if (
                                result.total_uncompressed_bytes + bytes_written
                                > max_uncompressed_bytes
                            ):
                                # Best-effort cleanup of the partial file.
                                try:
                                    out.close()
                                    safe_path.unlink(missing_ok=True)
                                finally:
                                    raise ArchiveTooLargeError(
                                        result.total_uncompressed_bytes + bytes_written,
                                        max_uncompressed_bytes,
                                    )
                            out.write(chunk)

                    result.total_uncompressed_bytes += bytes_written
                    result.files += 1
                    result.members.append(normalised)

                    # Strip dangerous mode bits.
                    if member.mode:
                        try:
                            os.chmod(safe_path, _safe_mode(member.mode))
                        except OSError as exc:
                            logger.debug(
                                "safe_extract: chmod failed for %s: %s", safe_path, exc
                            )

    logger.info(
        "safe_extract: extracted %d files / %d dirs / %d symlinks / %d hardlinks "
        "(%d bytes uncompressed) from %s",
        result.files,
        result.dirs,
        result.symlinks,
        result.hardlinks,
        result.total_uncompressed_bytes,
        archive,
    )
    return result


__all__ = [
    "ArchiveTooLargeError",
    "DEFAULT_MAX_UNCOMPRESSED_BYTES",
    "ExtractionResult",
    "UnsafeArchiveError",
    "UnsupportedArchiveFormatError",
    "safe_extract",
]
