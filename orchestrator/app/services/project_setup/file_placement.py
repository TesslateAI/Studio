import asyncio
import io
import logging
import os
import shutil
import subprocess
import tarfile
from dataclasses import dataclass

from ...services.base_config_parser import (
    TesslateProjectConfig,
    serialize_config_to_json,
    write_tesslate_config,
)

logger = logging.getLogger(__name__)

SKIP_DIRS = frozenset(
    {".git", "node_modules", ".next", "__pycache__", ".venv", "venv", "dist", "build"}
)


@dataclass
class PlacedFiles:
    """Result of file placement."""

    volume_id: str | None = None
    node_name: str | None = None
    project_path: str | None = None  # Docker filesystem path


async def place_files(
    source_path: str,
    config: TesslateProjectConfig,
    project_slug: str,
    deployment_mode: str,
    task=None,
    write_config: bool = True,
) -> PlacedFiles:
    """
    Place source files into the project's storage location.

    Args:
        source_path: Path to source files (temp dir or cache dir)
        config: Resolved project config to write
        project_slug: Project slug
        deployment_mode: "docker" or "kubernetes"
        task: Optional task for progress updates
        write_config: Whether to write .tesslate/config.json to the destination.
            Set to False when config is a fallback so the Setup page can
            distinguish "no config" from "real template config".
    """
    if deployment_mode == "docker":
        return await _place_docker(source_path, config, project_slug, task, write_config)
    else:
        return await _place_kubernetes(source_path, config, project_slug, task, write_config)


async def _place_docker(
    source_path: str,
    config: TesslateProjectConfig,
    project_slug: str,
    task=None,
    write_config: bool = True,
) -> PlacedFiles:
    """Copy files to Docker volume at /projects/{slug}/"""
    volume_path = f"/projects/{project_slug}"
    os.makedirs(volume_path, exist_ok=True)

    if task:
        task.update_progress(60, 100, "Copying files to project volume...")

    # Copy source files, skipping generated/dependency dirs
    for item in os.listdir(source_path):
        if item in SKIP_DIRS:
            continue
        src = os.path.join(source_path, item)
        dst = os.path.join(volume_path, item)
        if os.path.isdir(src):
            await asyncio.to_thread(shutil.copytree, src, dst, dirs_exist_ok=True)
        else:
            await asyncio.to_thread(shutil.copy2, src, dst)

    # Write resolved config (skip for fallback — let Setup page handle it)
    if write_config:
        write_tesslate_config(volume_path, config)

    # Fix permissions for devserver (runs as user 1000:1000)
    await asyncio.to_thread(subprocess.run, ["chown", "-R", "1000:1000", volume_path], check=True)

    logger.info(f"[PLACEMENT] Copied files to Docker volume: {volume_path}")

    if task:
        task.update_progress(80, 100, "Files placed in project volume")

    return PlacedFiles(project_path=volume_path)


async def _place_kubernetes(
    source_path: str,
    config: TesslateProjectConfig,
    project_slug: str,  # noqa: ARG001 — reserved for future per-project naming
    task=None,
    write_config: bool = True,
) -> PlacedFiles:
    """Write files to btrfs volume via FileOps gRPC."""
    from ...services.fileops_client import FileOpsClient
    from ...services.node_discovery import NodeDiscovery
    from ...services.volume_manager import get_volume_manager

    if task:
        task.update_progress(50, 100, "Creating project volume...")

    vm = get_volume_manager()
    volume_id, node_name = await vm.create_empty_volume()

    if task:
        task.update_progress(60, 100, "Writing files to volume...")

    # Build tar archive locally — one gRPC call instead of N per-file writes
    tar_data, files_written = await asyncio.to_thread(
        _build_source_tar, source_path, config if write_config else None
    )

    discovery = NodeDiscovery()
    address = await discovery.get_fileops_address(node_name)

    async with FileOpsClient(address) as client:
        await client.tar_extract(volume_id, ".", tar_data)

    logger.info(
        f"[PLACEMENT] Placed {files_written} files on volume {volume_id} via tar ({len(tar_data)} bytes)"
    )

    if task:
        task.update_progress(80, 100, f"Wrote {files_written} files to volume")

    return PlacedFiles(volume_id=volume_id, node_name=node_name)


def _build_source_tar(
    source_path: str,
    config: TesslateProjectConfig | None = None,
) -> tuple[bytes, int]:
    """Build a tar archive from a source directory.

    Runs in a thread (blocking I/O). Returns (tar_bytes, file_count).
    Excludes common generated/dependency directories (node_modules, .git, etc.).
    Optionally injects .tesslate/config.json into the archive.
    """
    buf = io.BytesIO()
    file_count = 0

    with tarfile.open(fileobj=buf, mode="w") as tar:
        for root, dirs, files in os.walk(source_path):
            # Prune skipped directories in-place so os.walk doesn't descend
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

            for fname in files:
                full_path = os.path.join(root, fname)
                arcname = os.path.relpath(full_path, source_path).replace("\\", "/")
                try:
                    tar.add(full_path, arcname=arcname)
                    file_count += 1
                except (OSError, ValueError) as e:
                    logger.warning("[PLACEMENT] Skipping %s: %s", arcname, e)

        # Inject .tesslate/config.json if provided
        if config is not None:
            config_bytes = serialize_config_to_json(config).encode("utf-8")
            info = tarfile.TarInfo(name=".tesslate/config.json")
            info.size = len(config_bytes)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(config_bytes))
            file_count += 1

    return buf.getvalue(), file_count
