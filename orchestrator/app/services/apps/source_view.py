"""Source file listing for installed Tesslate Apps.

Enforces the `source_visibility` policy from the AppVersion manifest:

  - public      → anyone (including anonymous).
  - installers  → only users with a non-uninstalled AppInstance.
  - private     → nobody (raises).

Defense-in-depth: HARDCODED_EXCLUSIONS are ALWAYS filtered, regardless of the
manifest. Never return `.env*`, `secrets/**`, `.git/**`, or
`.tesslate/internal/**`.
"""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AppInstance, AppVersion

logger = logging.getLogger(__name__)


HARDCODED_EXCLUSIONS: tuple[str, ...] = (
    ".env*",
    "secrets/**",
    ".git/**",
    ".tesslate/internal/**",
)

_MANIFEST_ROOT_FILE = "app.manifest.json"


class SourceAccessError(Exception):
    """Base class for source view errors."""


class PrivateSourceError(SourceAccessError):
    """Raised when source visibility is 'private'."""


class InstallerOnlySourceError(SourceAccessError):
    """Raised when viewer is not an installer of an 'installers'-scope app."""


@dataclass(frozen=True)
class SourceListing:
    files: list[str]
    manifest_always_public: bool


async def default_list_volume_files(volume_id: str | None) -> list[str]:
    """Placeholder volume file lister. Wave 2 stub — actual wiring to
    hub_client / fileops is a later wave. Returns empty list."""
    return []


def _matches_any(path: str, patterns: tuple[str, ...] | list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pat) for pat in patterns)


async def _is_installer(
    db: AsyncSession, *, viewer_user_id: UUID, app_id: UUID
) -> bool:
    row = (
        await db.execute(
            select(AppInstance.id)
            .where(AppInstance.installer_user_id == viewer_user_id)
            .where(AppInstance.app_id == app_id)
            .where(AppInstance.state != "uninstalled")
            .limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


async def list_files(
    db: AsyncSession,
    *,
    app_version_id: UUID,
    viewer_user_id: UUID | None,
    list_volume_files: Callable[[str | None], Awaitable[list[str]]] = default_list_volume_files,
) -> SourceListing:
    av: AppVersion | None = (
        await db.execute(select(AppVersion).where(AppVersion.id == app_version_id))
    ).scalar_one_or_none()
    if av is None:
        raise SourceAccessError(f"app_version {app_version_id} not found")

    manifest = av.manifest_json or {}
    policy = (manifest.get("source_visibility") or {})
    level = (policy.get("level") or "private").lower()
    excluded_manifest: list[str] = list(policy.get("excluded_paths") or [])
    manifest_always_public: bool = bool(policy.get("manifest_always_public", False))

    if level == "private":
        raise PrivateSourceError("source visibility is private")
    if level == "installers":
        if viewer_user_id is None or not await _is_installer(
            db, viewer_user_id=viewer_user_id, app_id=av.app_id
        ):
            raise InstallerOnlySourceError(
                "source visibility restricted to installers"
            )
    elif level != "public":
        raise SourceAccessError(f"unknown source_visibility level: {level!r}")

    raw = await list_volume_files(av.bundle_hash)
    exclusions = tuple(excluded_manifest) + HARDCODED_EXCLUSIONS

    filtered = [p for p in raw if not _matches_any(p, exclusions)]

    if manifest_always_public and _MANIFEST_ROOT_FILE in raw and _MANIFEST_ROOT_FILE not in filtered:
        filtered.append(_MANIFEST_ROOT_FILE)

    return SourceListing(files=filtered, manifest_always_public=manifest_always_public)
