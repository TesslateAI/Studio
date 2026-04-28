"""Project-vs-App boundary helpers.

Installed app runtimes (`Project.project_kind == PROJECT_KIND_APP_RUNTIME`)
must never appear in the Projects dashboard — they live in the Apps
Dashboard (`/apps/installed`). Every query that returns a collection of
Projects to a user MUST route through `exclude_app_instances_clause()` to
preserve that invariant.

Lookups by Project.id / Project.slug are fine as-is; those are scoped by a
specific identifier, not by collection.
"""

from __future__ import annotations

from sqlalchemy.sql import ColumnElement

from ...models import PROJECT_KIND_APP_RUNTIME, Project


def exclude_app_instances_clause() -> ColumnElement[bool]:
    """Return a WHERE clause that filters out installed-app runtime projects.

    Keeps projects whose `project_kind` is `'workspace'` (regular user
    project) or `'app_source'` (creator studio draft). Excludes
    `'app_runtime'` (installed app runtime mounts, shown in /apps instead).
    """
    return Project.project_kind != PROJECT_KIND_APP_RUNTIME


def only_app_instances_clause() -> ColumnElement[bool]:
    """WHERE clause matching ONLY installed-app runtime projects."""
    return Project.project_kind == PROJECT_KIND_APP_RUNTIME
