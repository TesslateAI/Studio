"""
Unified project filesystem-path resolver.

Callers that need to read or write project files from outside an orchestrator
exec session (routers doing direct I/O, background tasks, CLI tools) ask this
module instead of branching on ``deployment_mode == "docker"``.

Contract:

- Docker: returns ``/projects/<slug>`` — the shared volume mount that the host
  and every project container share.
- Desktop: returns ``$OPENSAIL_HOME/projects/<slug>-<id>`` — the
  per-project root materialized by ``file_placement._place_desktop`` (and
  referenced by ``LocalOrchestrator`` for multi-project isolation).
- Kubernetes: returns ``None`` — there is no host-reachable path; callers
  must route through an orchestrator's FileOps interface instead.

Callers that previously wrote::

    if settings.deployment_mode == "docker":
        path = f"/projects/{project.slug}"
        ...

become::

    fs_path = get_project_fs_path(project)
    if fs_path is not None:
        ...

which keeps docker behavior identical and automatically includes desktop.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import get_settings


def get_project_fs_path(project: Any | None) -> Path | None:
    """Return the host-reachable filesystem path for ``project``.

    ``None`` means the caller must use an orchestrator's FileOps interface
    (kubernetes) or no project was supplied.

    ``project`` can be a SQLAlchemy ``Project`` row or any object exposing
    ``slug`` and ``id`` attributes. We read attributes defensively so model
    changes don't break this helper.
    """
    if project is None:
        return None

    slug = getattr(project, "slug", None)
    if not slug:
        return None

    settings = get_settings()
    mode = (settings.deployment_mode or "").lower()

    if mode == "docker":
        return Path(f"/projects/{slug}")

    if mode == "desktop":
        from .desktop_paths import ensure_opensail_home

        home = ensure_opensail_home(settings.opensail_home or None)
        pid = getattr(project, "id", None)
        dir_name = f"{slug}-{pid}" if pid is not None else slug
        return (home / "projects" / dir_name).resolve()

    # kubernetes / unknown — no host-reachable path.
    return None


def has_fs_path(project: Any | None) -> bool:
    """Convenience boolean form of :func:`get_project_fs_path`."""
    return get_project_fs_path(project) is not None


# File tree walk helpers. Used by routers that previously branched on docker
# mode to read directly from ``/projects/<slug>/`` — desktop's per-project
# directory has the same shape, so callers can share one implementation.

_EXCLUDED_DIRS: frozenset[str] = frozenset(
    {
        "node_modules",
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "dist",
        "build",
        ".next",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "target",
    }
)

_EXCLUDED_FILES: frozenset[str] = frozenset({".DS_Store", "Thumbs.db", ".env", ".env.local"})

_BINARY_EXTENSIONS: frozenset[str] = frozenset(
    {
        "png",
        "jpg",
        "jpeg",
        "gif",
        "ico",
        "webp",
        "svg",
        "bmp",
        "pdf",
        "zip",
        "tar",
        "gz",
        "tgz",
        "bz2",
        "7z",
        "rar",
        "exe",
        "dll",
        "so",
        "dylib",
        "bin",
        "mp3",
        "mp4",
        "mov",
        "avi",
        "wav",
        "webm",
        "woff",
        "woff2",
        "ttf",
        "otf",
        "eot",
    }
)


async def read_all_files(
    base: Path,
    *,
    max_files: int = 200,
    max_file_size: int = 100_000,
    subdir: str | None = None,
) -> list[dict[str, str]]:
    """Walk ``base`` (optionally ``base/subdir``) and return text files with
    content. Skips binary extensions, excluded dirs/files, oversized files.

    Matches the shape DockerOrchestrator.get_files_with_content used to
    return so callers stay unchanged: list of ``{"file_path", "content"}``.
    """
    import os

    import aiofiles

    root = base / subdir if subdir else base
    if not root.exists() or not root.is_dir():
        return []

    out: list[dict[str, str]] = []
    count = 0
    for dirpath, dirs, filenames in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _EXCLUDED_DIRS]

        for fname in filenames:
            if count >= max_files:
                return out
            if fname in _EXCLUDED_FILES:
                continue
            ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
            if ext in _BINARY_EXTENSIONS:
                continue

            full = Path(dirpath) / fname
            try:
                if full.stat().st_size > max_file_size:
                    continue
            except OSError:
                continue

            try:
                async with aiofiles.open(full, encoding="utf-8") as f:
                    content = await f.read()
            except (OSError, UnicodeDecodeError):
                continue

            rel = full.relative_to(root)
            out.append({"file_path": str(rel), "content": content})
            count += 1

    return out
