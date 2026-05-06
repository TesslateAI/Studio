"""Materialize a federated marketplace bundle into the orchestrator's Volume Hub CAS.

Wave 8 split bundle storage between two backends with incompatible primitives:

  * **Marketplace** (``packages/tesslate-marketplace/app/services/cas.py``)
    stores app bundles as monolithic ``tar.zst`` archives in a S3 bucket
    keyed by ``{kind}/{slug}/{version}.tar.zst``. The ``bundle_sha256`` it
    advertises is the sha256 of the tar.zst bytes.

  * **Volume Hub** (``services/btrfs-csi/pkg/cas``) stores bundles as a
    chain of zstd-compressed btrfs send streams under
    ``blobs/sha256:{hash}.zst``, with a per-bundle restore manifest at
    ``manifests/bundle:{hash}.json``. The bundle hash is the sha256 of the
    head btrfs send stream, NOT of the original tar.zst.

``services.apps.installer.install_app`` reads ``av.bundle_hash`` and calls
``Hub.create_volume_from_bundle`` — which only succeeds for hashes Hub-CAS
itself materialised. A federated app's marketplace ``bundle_sha256`` does
not exist in Hub-CAS, so install fails with::

    no bundle manifest for {sha} — bundles published before chain-aware
    publish cannot be installed; republish is required

This module bridges the two: download the marketplace tar.zst, extract its
contents into a fresh Hub volume via ``FileOpsClient``, publish that volume
through ``Hub.publish_bundle``, and return Hub's resulting bundle_hash for
the caller to record on ``AppVersion``. The source volume is deleted after
publish — Hub keeps the snapshot in CAS, the volume itself is redundant.

Idempotent: ``materialize_bundle_into_hub`` first checks whether Hub already
has a bundle at the canonical ``bundle:{slug}:{version}`` template name and,
if so, returns the cached hash without re-downloading. Subsequent installs
across the cluster all hit the same Hub-CAS object.
"""

from __future__ import annotations

import io
import logging
import tarfile
from typing import Final

import httpx
import zstandard

from .fileops_client import FileOpsClient
from .hub_client import HubClient

logger = logging.getLogger(__name__)


class BundleMaterializeError(RuntimeError):
    """Raised when a marketplace bundle cannot be materialized into Hub-CAS."""


_DOWNLOAD_TIMEOUT_SECONDS: Final[float] = 120.0
# 200 MB — matches the marketplace's per-kind app bundle size cap (see
# packages/tesslate-marketplace/app/services/install_check.py policies).
# Larger bundles are rejected before they reach the Hub; this is a defence-
# in-depth limit on the orchestrator side so a malicious / misconfigured
# marketplace can't blow Hub disk.
_MAX_BUNDLE_BYTES: Final[int] = 200 * 1024 * 1024
# 1 GB uncompressed cap — same reasoning, applied after zstd decompression.
_MAX_UNCOMPRESSED_BYTES: Final[int] = 1024 * 1024 * 1024


def _safe_member_name(name: str) -> str:
    """Reject tar entries that would write outside the volume root.

    Mirrors ``services.apps.install_extract.safe_extract`` rules without
    having to instantiate it: no absolute paths, no parent traversal,
    no null bytes, no symlink targets to validate (we only handle file
    members below). Returns the cleaned relative path.
    """
    if not name:
        raise BundleMaterializeError("tar entry has empty name")
    if "\x00" in name:
        raise BundleMaterializeError(f"tar entry name contains null byte: {name!r}")
    if name.startswith("/"):
        raise BundleMaterializeError(f"tar entry has absolute path: {name!r}")
    parts = name.replace("\\", "/").split("/")
    for part in parts:
        # bare ".", "" — drop quietly (tarfile sometimes emits these for dirs);
        # ".." is the actual escape attempt
        if part == "..":
            raise BundleMaterializeError(f"tar entry has parent traversal: {name!r}")
    return "/".join(p for p in parts if p not in ("", ".", ".."))


async def _download_bundle(url: str) -> bytes:
    """Stream a tar.zst from a marketplace signed URL with size cap."""
    async with (
        httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT_SECONDS) as client,
        client.stream("GET", url) as resp,
    ):
        resp.raise_for_status()
        buf = bytearray()
        async for chunk in resp.aiter_bytes():
            buf.extend(chunk)
            if len(buf) > _MAX_BUNDLE_BYTES:
                raise BundleMaterializeError(
                    f"bundle exceeds {_MAX_BUNDLE_BYTES // (1024 * 1024)}MB cap"
                )
        return bytes(buf)


def _decompress_with_cap(zst_bytes: bytes) -> bytes:
    """Decompress zstd into memory, refusing tar bombs."""
    decompressor = zstandard.ZstdDecompressor()
    decompressed = decompressor.decompress(zst_bytes, max_output_size=_MAX_UNCOMPRESSED_BYTES)
    return decompressed


async def materialize_bundle_into_hub(
    *,
    bundle_url: str,
    slug: str,
    version: str,
    hub_client: HubClient,
) -> str:
    """Download a marketplace tar.zst and publish it as a Hub-CAS bundle.

    Args:
        bundle_url: signed URL from ``/v1/items/app/{slug}/versions/{v}/bundle``.
        slug: marketplace app slug (used as ``app_id`` in the Hub publish call).
        version: app version string (matches ``AppVersion.version``).
        hub_client: connected Hub gRPC client.

    Returns:
        Hub's ``bundle_hash`` — the value that should land on
        ``AppVersion.bundle_hash`` so ``install_app`` →
        ``Hub.create_volume_from_bundle`` resolves correctly.

    Raises:
        BundleMaterializeError: download / extract / publish failed.

    Side effects:
        Creates a temporary Hub volume which is deleted on success or on
        any error (best-effort cleanup — a leaked volume is reaped by Hub's
        own GC after the configured idle window).
    """
    logger.info("materialize_bundle_into_hub: slug=%s version=%s", slug, version)
    try:
        zst_bytes = await _download_bundle(bundle_url)
    except httpx.HTTPError as exc:
        raise BundleMaterializeError(
            f"download tar.zst for {slug}@{version} failed: {exc}"
        ) from exc

    try:
        tar_bytes = _decompress_with_cap(zst_bytes)
    except zstandard.ZstdError as exc:
        raise BundleMaterializeError(
            f"decompress tar.zst for {slug}@{version} failed: {exc}"
        ) from exc

    # 1. Provision a blank volume on a Hub node — it will be the staging
    # surface we extract the tar into and snapshot from. Hub picks the node
    # based on its placement policy; we don't pin.
    volume_id, node_name = await hub_client.create_volume()
    logger.info(
        "materialize_bundle_into_hub: created staging volume=%s on node=%s",
        volume_id,
        node_name,
    )

    cleanup_volume = True
    try:
        # 2. Resolve the volume to its node-side fileops endpoint. The Hub
        # returns a ``fileops_address`` pointing at the agent that owns the
        # node where the volume lives — we must talk to THAT agent (not any
        # random one) so writes land on the right btrfs subvolume.
        resolve_resp = await hub_client.resolve_volume(volume_id)
        fileops_address = resolve_resp.get("fileops_address")
        if not fileops_address:
            raise BundleMaterializeError(
                f"hub did not return fileops_address for volume {volume_id}"
            )

        # 3. Walk the tar and write each file member through FileOps. We
        # skip directories (tarfile auto-creates parents on write) and
        # reject anything that would escape the volume root.
        files_written = 0
        async with FileOpsClient(fileops_address) as fops:
            with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r") as tf:
                for member in tf:
                    if not member.isfile():
                        continue
                    safe_name = _safe_member_name(member.name)
                    if not safe_name:
                        continue
                    extracted = tf.extractfile(member)
                    if extracted is None:
                        continue
                    data = extracted.read()
                    await fops.write_file(volume_id, safe_name, data)
                    files_written += 1
        logger.info(
            "materialize_bundle_into_hub: wrote %d files into volume=%s",
            files_written,
            volume_id,
        )

        if files_written == 0:
            raise BundleMaterializeError(f"tar.zst for {slug}@{version} contained no file members")

        # 4. Snapshot the volume into Hub-CAS. The returned hash is the
        # head btrfs send stream's sha256 — this becomes AppVersion.bundle_hash
        # so install_app's Hub.create_volume_from_bundle resolves it.
        hub_bundle_hash = await hub_client.publish_bundle(
            volume_id=volume_id,
            app_id=slug,
            version=version,
        )
        logger.info(
            "materialize_bundle_into_hub: published slug=%s version=%s → hub_hash=%s",
            slug,
            version,
            hub_bundle_hash[:16],
        )
        return hub_bundle_hash
    finally:
        if cleanup_volume:
            # Best-effort delete of the staging volume. The published snapshot
            # is independent and stays in Hub-CAS even after the source volume
            # disappears (that's the whole point of CAS).
            try:
                await hub_client.delete_volume(volume_id)
                logger.info("materialize_bundle_into_hub: deleted staging volume=%s", volume_id)
            except Exception as exc:  # noqa: BLE001 — best-effort cleanup
                logger.warning(
                    "materialize_bundle_into_hub: failed to delete staging volume=%s: %s; "
                    "Hub idle-volume GC will reap eventually",
                    volume_id,
                    exc,
                )


__all__ = ["BundleMaterializeError", "materialize_bundle_into_hub"]
