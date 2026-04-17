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

    Matches projects whose `app_role` is NULL (legacy / user-authored) or
    `"app_source"` (canvas draft of an app the user is creating) — both of
    those belong in the Projects dashboard. Excludes `"app_instance"`.
    """
    return or_(Project.app_role.is_(None), Project.app_role == "app_source")


def only_app_instances_clause() -> ColumnElement[bool]:
    """WHERE clause matching ONLY AppInstance-backed projects."""
    return Project.app_role == "app_instance"
