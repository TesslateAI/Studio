"""Project-vs-App boundary helpers.

Installed apps (`Project.app_role == "app_instance"`) must never appear in the
Projects dashboard — they live in the Apps Dashboard (`/apps/installed`).
Every query that returns a collection of Projects to a user MUST route through
`exclude_app_instances(...)` to preserve that invariant.

Lookups by Project.id / Project.slug are fine as-is; those are scoped by a
specific identifier, not by collection.
"""

from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.sql import ColumnElement

from ...models import Project


def exclude_app_instances_clause() -> ColumnElement[bool]:
    """Return a WHERE clause that filters out AppInstance-backed projects.

    Keeps projects whose `app_role` is NULL (legacy), `"none"` (regular
    user project), or `"app_source"` (creator studio draft). Excludes
    `"app_instance"` (installed app runtime mounts, shown in /apps instead).
    """
    return or_(Project.app_role.is_(None), Project.app_role != "app_instance")


def only_app_instances_clause() -> ColumnElement[bool]:
    """WHERE clause matching ONLY AppInstance-backed projects."""
    return Project.app_role == "app_instance"
