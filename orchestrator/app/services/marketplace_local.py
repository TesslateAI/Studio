"""
Filesystem-backed marketplace source for desktop mode.

The ``Local`` system source is a sentinel — it has no real hub, no HTTP
endpoint, no hub-id pinning. Items live as directories under
``$OPENSAIL_HOME/{kind}s/{slug}/`` (and optionally a per-version subdir
``$OPENSAIL_HOME/{kind}s/{slug}/{version}/``). This module is the
authoritative populator for that source's catalog cache and the
authoritative source of "bundle envelopes" for items installed locally.

Wave 6 makes this the only path the installer uses for ``local://``
sources — it short-circuits the HTTP marketplace_client and treats the
local filesystem as if it were a hub.

Invariants:
  - The Local source row's ``base_url`` MUST start with ``local://``.
  - Every item is a directory with a ``manifest.json`` at its root (or at
    a ``{version}/`` subdir, where ``version`` is a semver-ish string).
  - Bundle "downloads" are filesystem copies; sha256 is computed against
    the on-disk archive (or, if no archive exists, a virtual archive
    materialised on demand from the directory tree).

This module deliberately does NOT mutate ``MarketplaceSource``. The sync
worker is responsible for writing rows; this module only emits virtual
events the caller applies.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import tarfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Iterable, Literal
from uuid import UUID

import zstandard
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    MarketplaceAgent,
    MarketplaceApp,
    MarketplaceBase,
    MarketplaceSource,
    Theme,
    WorkflowTemplate,
)
from .desktop_paths import resolve_opensail_home

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


LOCAL_SOURCE_HANDLE: Final[str] = "local"
LOCAL_BASE_URL_PREFIX: Final[str] = "local://"

# Map our "kind" strings to the on-disk directory name.
_KIND_TO_DIR: Final[dict[str, str]] = {
    "agent": "agents",
    "skill": "skills",
    "mcp_server": "mcp_servers",
    "base": "bases",
    "theme": "themes",
    "workflow_template": "workflow_templates",
    "app": "apps",
}

_MANIFEST_FILENAME: Final[str] = "manifest.json"
_HASH_CHUNK_BYTES: Final[int] = 64 * 1024


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


EventOp = Literal["upsert", "delete", "version_remove"]


@dataclass(frozen=True)
class LocalEnvelope:
    """The local equivalent of a /v1 bundle envelope.

    Same shape as the federated envelope so the installer can branch on
    ``url.startswith('local://')`` and otherwise treat it identically.
    """

    url: str  # local://path/to/bundle.tar.zst OR local-dir://path
    sha256: str
    size_bytes: int
    content_type: str
    archive_format: str
    expires_at: str | None
    attestation: dict[str, Any] | None
    # Only present for ``local-dir://`` envelopes — direct on-disk path
    # so the installer can copy without re-downloading.
    local_path: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "content_type": self.content_type,
            "archive_format": self.archive_format,
            "expires_at": self.expires_at,
            "attestation": self.attestation,
        }


@dataclass(frozen=True)
class LocalChangeEvent:
    """A virtual changes-feed event emitted by the local scan."""

    op: EventOp
    kind: str
    slug: str
    version: str | None = None
    payload: dict[str, Any] | None = None


@dataclass
class LocalSyncResult:
    """Counts emitted by a single :func:`sync_local` run."""

    source_id: UUID
    items_upserted: int = 0
    items_deleted: int = 0
    versions_removed: int = 0
    error: str | None = None
    events: list[LocalChangeEvent] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------


def _opensail_root() -> Path:
    return resolve_opensail_home()


def _kind_dir(kind: str) -> Path:
    if kind not in _KIND_TO_DIR:
        raise ValueError(f"unknown kind: {kind!r}")
    return _opensail_root() / _KIND_TO_DIR[kind]


def _read_manifest(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("marketplace_local: skipping unparseable manifest %s: %s", path, exc)
        return None
    if not isinstance(data, dict):
        return None
    return data


def _looks_like_version_dir(name: str) -> bool:
    """A version subdirectory name must look like a semver-ish token.

    We accept anything starting with a digit so ``1.0.0``, ``1``,
    ``2.3.0-beta.1``, ``20240101`` all qualify. Anything else (e.g.
    ``cache``, ``.tmp``) is treated as a regular file/directory inside
    the slug.
    """
    return bool(name) and name[0].isdigit()


def _hash_file(path: Path) -> tuple[str, int]:
    """Compute streaming sha256 + byte size of a regular file."""
    h = hashlib.sha256()
    total = 0
    with path.open("rb") as f:
        while True:
            chunk = f.read(_HASH_CHUNK_BYTES)
            if not chunk:
                break
            h.update(chunk)
            total += len(chunk)
    return h.hexdigest(), total


def _hash_directory_as_tar_zst(directory: Path) -> tuple[str, int, bytes]:
    """Materialise a deterministic tar.zst of ``directory`` and return
    (sha256, size, archive bytes).

    This is how virtual-bundle envelopes work for items that aren't
    pre-bundled — the installer needs an on-disk file to extract from,
    so we synthesise one. Determinism (stable mtime, sorted entries) is
    required so the sha256 is reproducible across runs.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:") as tf:
        for entry in sorted(_walk(directory)):
            rel = entry.relative_to(directory)
            info = tarfile.TarInfo(name=str(rel))
            stat = entry.lstat()
            if entry.is_dir():
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                info.size = 0
                info.mtime = 0
                tf.addfile(info)
                continue
            if entry.is_symlink():
                info.type = tarfile.SYMTYPE
                info.linkname = os.readlink(entry)
                info.mode = 0o755
                info.size = 0
                info.mtime = 0
                tf.addfile(info)
                continue
            info.type = tarfile.REGTYPE
            info.size = stat.st_size
            info.mode = 0o644
            info.mtime = 0
            with entry.open("rb") as f:
                tf.addfile(info, f)
    raw = buf.getvalue()
    compressed = zstandard.ZstdCompressor(level=10).compress(raw)
    return hashlib.sha256(compressed).hexdigest(), len(compressed), compressed


def _walk(root: Path) -> Iterable[Path]:
    """Like ``Path.rglob('*')`` but skips hidden dirs (``.git``, etc.)."""
    for child in root.iterdir():
        if child.name.startswith("."):
            continue
        yield child
        if child.is_dir() and not child.is_symlink():
            yield from _walk(child)


# ---------------------------------------------------------------------------
# Public API: scan
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LocalItemRecord:
    """One scanned item — what the catalog sync would upsert."""

    kind: str
    slug: str
    version: str
    manifest: dict[str, Any]
    item_path: Path
    bundle_path: Path | None  # path to a pre-built bundle if present
    sha256: str
    size_bytes: int


def scan_kind(kind: str) -> list[LocalItemRecord]:
    """Walk ``$OPENSAIL_HOME/{kind}s/`` and return one record per item.

    For each ``{slug}/`` directory:
      - If it contains numbered subdirs (e.g. ``1.0.0/``), each subdir is
        a separate version.
      - Otherwise the slug dir is treated as the single ``latest`` version.
      - A manifest.json is required at the version-dir root.
      - If the version dir contains ``bundle.tar.zst`` we use that for
        sha256/size; otherwise we synthesise a virtual bundle.

    Items without a manifest.json are skipped (logged at debug).
    """
    base = _kind_dir(kind)
    if not base.exists():
        return []

    records: list[LocalItemRecord] = []
    for slug_dir in sorted(base.iterdir()):
        if not slug_dir.is_dir() or slug_dir.name.startswith("."):
            continue
        slug = slug_dir.name

        # Detect versioned layout: any direct subdirectory whose name
        # starts with a digit AND has a manifest.json inside.
        version_dirs: list[tuple[str, Path]] = []
        for child in slug_dir.iterdir():
            if (
                child.is_dir()
                and not child.is_symlink()
                and _looks_like_version_dir(child.name)
                and (child / _MANIFEST_FILENAME).is_file()
            ):
                version_dirs.append((child.name, child))

        if version_dirs:
            for version, vdir in sorted(version_dirs, key=lambda t: t[0]):
                rec = _build_record(kind, slug, version, vdir)
                if rec is not None:
                    records.append(rec)
        else:
            manifest_path = slug_dir / _MANIFEST_FILENAME
            if not manifest_path.is_file():
                logger.debug(
                    "marketplace_local: skipping %s/%s (no manifest)", kind, slug
                )
                continue
            manifest = _read_manifest(manifest_path)
            if manifest is None:
                continue
            version = str(manifest.get("version") or "0.0.0")
            rec = _build_record(kind, slug, version, slug_dir, manifest=manifest)
            if rec is not None:
                records.append(rec)
    return records


def _build_record(
    kind: str,
    slug: str,
    version: str,
    version_dir: Path,
    *,
    manifest: dict[str, Any] | None = None,
) -> LocalItemRecord | None:
    if manifest is None:
        manifest = _read_manifest(version_dir / _MANIFEST_FILENAME)
    if manifest is None:
        return None
    bundle = version_dir / "bundle.tar.zst"
    if bundle.is_file():
        sha256, size = _hash_file(bundle)
        bundle_path = bundle
    else:
        sha256, size, _ = _hash_directory_as_tar_zst(version_dir)
        bundle_path = None
    return LocalItemRecord(
        kind=kind,
        slug=slug,
        version=version,
        manifest=manifest,
        item_path=version_dir,
        bundle_path=bundle_path,
        sha256=sha256,
        size_bytes=size,
    )


def scan_all_kinds() -> list[LocalItemRecord]:
    out: list[LocalItemRecord] = []
    for kind in _KIND_TO_DIR:
        out.extend(scan_kind(kind))
    return out


# ---------------------------------------------------------------------------
# Public API: bundle envelope (the local equivalent of /v1/.../bundle)
# ---------------------------------------------------------------------------


def get_bundle_envelope(kind: str, slug: str, version: str | None = None) -> LocalEnvelope:
    """Return a :class:`LocalEnvelope` for a local item.

    Mirrors :meth:`marketplace_client.MarketplaceClient.get_bundle` shape
    so the installer's bundle-handling code can be source-agnostic.

    If ``version`` is None we pick the highest semver-sortable version
    directory present (or the slug dir itself if no versioned layout).

    Raises :class:`FileNotFoundError` if the item or version isn't on disk.
    """
    base = _kind_dir(kind)
    slug_dir = base / slug
    if not slug_dir.is_dir():
        raise FileNotFoundError(f"local marketplace item not found: {kind}/{slug}")

    if version is None:
        # Prefer numbered subdirs; otherwise the slug dir is the single version.
        candidates = [
            (c.name, c)
            for c in slug_dir.iterdir()
            if c.is_dir()
            and _looks_like_version_dir(c.name)
            and (c / _MANIFEST_FILENAME).is_file()
        ]
        if candidates:
            candidates.sort(key=lambda t: t[0], reverse=True)
            version, vdir = candidates[0]
        else:
            manifest = _read_manifest(slug_dir / _MANIFEST_FILENAME)
            if manifest is None:
                raise FileNotFoundError(
                    f"local marketplace item missing manifest: {kind}/{slug}"
                )
            version = str(manifest.get("version") or "0.0.0")
            vdir = slug_dir
    else:
        vdir = slug_dir / version
        if not vdir.is_dir():
            # Version-less layout — only valid if the slug dir's manifest matches.
            manifest = _read_manifest(slug_dir / _MANIFEST_FILENAME)
            if manifest and str(manifest.get("version") or "0.0.0") == version:
                vdir = slug_dir
            else:
                raise FileNotFoundError(
                    f"local marketplace item version not found: {kind}/{slug}@{version}"
                )

    bundle_file = vdir / "bundle.tar.zst"
    if bundle_file.is_file():
        sha256, size = _hash_file(bundle_file)
        url = f"local-file://{bundle_file.resolve()}"
        path = bundle_file
    else:
        sha256, size, _ = _hash_directory_as_tar_zst(vdir)
        url = f"local-dir://{vdir.resolve()}"
        path = vdir

    return LocalEnvelope(
        url=url,
        sha256=sha256,
        size_bytes=size,
        content_type="application/zstd",
        archive_format="tar.zst",
        expires_at=None,  # local URLs never expire
        attestation=None,
        local_path=path,
    )


def materialise_bundle(envelope: LocalEnvelope, out_path: Path) -> None:
    """Materialise the envelope's payload to ``out_path`` as a tar.zst file.

    For ``local-file://`` URLs this is a copy. For ``local-dir://`` URLs
    we re-build the deterministic tar.zst (the sha256 must match the
    envelope's, so we use the same builder).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if envelope.url.startswith("local-file://"):
        # Streaming copy — could be large.
        with envelope.local_path.open("rb") as src, out_path.open("wb") as dst:
            while True:
                chunk = src.read(_HASH_CHUNK_BYTES)
                if not chunk:
                    break
                dst.write(chunk)
        return
    if envelope.url.startswith("local-dir://"):
        _, _, archive_bytes = _hash_directory_as_tar_zst(envelope.local_path)
        out_path.write_bytes(archive_bytes)
        return
    raise ValueError(f"unrecognised local envelope URL: {envelope.url!r}")


# ---------------------------------------------------------------------------
# Public API: sync_local — populate the catalog cache from filesystem
# ---------------------------------------------------------------------------


_KIND_TO_MODEL: Final[dict[str, type]] = {
    "agent": MarketplaceAgent,
    "skill": MarketplaceAgent,
    "mcp_server": MarketplaceAgent,
    "base": MarketplaceBase,
    "app": MarketplaceApp,
    "theme": Theme,
    "workflow_template": WorkflowTemplate,
}


async def sync_local(
    db: AsyncSession,
    *,
    source_id: UUID | None = None,
) -> LocalSyncResult:
    """Scan ``$OPENSAIL_HOME/{kind}s/`` and emit virtual changes events
    that the caller can apply to the catalog cache for the Local source.

    Behaviour:
      - Resolves the Local source row by handle ('local') unless an
        explicit ``source_id`` is provided.
      - Walks every kind under OPENSAIL_HOME.
      - Compares the on-disk inventory against existing catalog rows for
        that source.
      - Returns the list of virtual events; the caller applies them.
        We deliberately don't mutate catalog rows here so that desktop
        and cloud share the same ``apply_change_event`` plumbing in
        :mod:`marketplace_sync`.

    Updates ``source.last_synced_at`` and clears ``source.last_sync_error``
    on success; sets the error string on failure (and re-raises so the
    caller can decide).
    """
    # Resolve the local source row.
    if source_id is not None:
        source = (
            await db.execute(
                select(MarketplaceSource).where(MarketplaceSource.id == source_id)
            )
        ).scalar_one_or_none()
    else:
        source = (
            await db.execute(
                select(MarketplaceSource)
                .where(MarketplaceSource.handle == LOCAL_SOURCE_HANDLE)
                .where(MarketplaceSource.scope == "system")
            )
        ).scalar_one_or_none()

    if source is None:
        raise LookupError(
            "sync_local: no Local marketplace source row found "
            "(expected handle='local' scope='system')"
        )

    if not source.base_url.startswith(LOCAL_BASE_URL_PREFIX):
        raise ValueError(
            f"sync_local: source {source.handle!r} is not a local source "
            f"(base_url={source.base_url!r})"
        )

    result = LocalSyncResult(source_id=source.id)

    try:
        on_disk = scan_all_kinds()
        on_disk_keys: set[tuple[str, str]] = {(r.kind, r.slug) for r in on_disk}

        for record in on_disk:
            payload = {
                "kind": record.kind,
                "slug": record.slug,
                "version": record.version,
                "manifest": record.manifest,
                "sha256": record.sha256,
                "size_bytes": record.size_bytes,
                "install_path": str(record.item_path),
            }
            result.events.append(
                LocalChangeEvent(
                    op="upsert",
                    kind=record.kind,
                    slug=record.slug,
                    version=record.version,
                    payload=payload,
                )
            )
            result.items_upserted += 1

        # Compare with existing cached rows under this source — anything
        # the catalog has but the FS doesn't anymore is a delete.
        for kind, model in _KIND_TO_MODEL.items():
            stmt = select(model).where(model.source_id == source.id)
            if model is MarketplaceAgent:
                # Filter by item_type so we only diff the right slice.
                if kind == "skill":
                    stmt = stmt.where(MarketplaceAgent.item_type == "skill")
                elif kind == "mcp_server":
                    stmt = stmt.where(MarketplaceAgent.item_type == "mcp_server")
                else:
                    stmt = stmt.where(MarketplaceAgent.item_type == "agent")
            cached_rows = (await db.execute(stmt)).scalars().all()
            for row in cached_rows:
                if (kind, row.slug) not in on_disk_keys:
                    result.events.append(
                        LocalChangeEvent(op="delete", kind=kind, slug=row.slug)
                    )
                    result.items_deleted += 1

        source.last_synced_at = datetime.now(UTC)
        source.last_sync_error = None
        await db.commit()
    except Exception as exc:
        result.error = str(exc)
        source.last_sync_error = f"sync_local: {exc!s}"[:500]
        # Don't fail the whole sync because last_sync_error couldn't be saved.
        try:
            await db.commit()
        except Exception:  # noqa: BLE001
            await db.rollback()
        raise

    return result


# ---------------------------------------------------------------------------
# Periodic registration helper (for the desktop scheduler)
# ---------------------------------------------------------------------------


SYNC_LOCAL_INTERVAL_SECONDS: Final[int] = 15 * 60


async def sync_local_loop(
    session_factory,
    *,
    interval_seconds: int = SYNC_LOCAL_INTERVAL_SECONDS,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Sleep-and-sync loop for the desktop worker.

    Long-running asyncio task that calls :func:`sync_local` every
    ``interval_seconds``. ``stop_event`` lets the supervisor cancel
    cleanly. Errors are logged and swallowed so the loop never dies.
    """
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        try:
            async with session_factory() as session:
                result = await sync_local(session)
                logger.info(
                    "sync_local_loop: upserted=%d deleted=%d (source=%s)",
                    result.items_upserted,
                    result.items_deleted,
                    result.source_id,
                )
        except Exception as exc:  # noqa: BLE001 — periodic loop must not die
            logger.warning("sync_local_loop: tick failed: %s", exc)
        try:
            if stop_event is not None:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
                if stop_event.is_set():
                    return
            else:
                await asyncio.sleep(interval_seconds)
        except asyncio.TimeoutError:
            continue
        except asyncio.CancelledError:
            return


__all__ = [
    "LOCAL_BASE_URL_PREFIX",
    "LOCAL_SOURCE_HANDLE",
    "LocalChangeEvent",
    "LocalEnvelope",
    "LocalItemRecord",
    "LocalSyncResult",
    "SYNC_LOCAL_INTERVAL_SECONDS",
    "get_bundle_envelope",
    "materialise_bundle",
    "scan_all_kinds",
    "scan_kind",
    "sync_local",
    "sync_local_loop",
]
