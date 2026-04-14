"""
Shared helpers for public-facing API routers.

Reused by every router in this package for ownership checks, cache
headers, pagination, and sorting.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

from fastapi import Response

from ...models import User


def add_cache_headers(response: Response, etag_source: str, max_age: int = 300) -> None:
    """Set ETag and Cache-Control on the response."""
    response.headers["ETag"] = hashlib.sha256(etag_source.encode()).hexdigest()
    response.headers["Cache-Control"] = f"public, max-age={max_age}"


def ownership_filter(user: User, model_class: Any):
    """Return a SQLAlchemy filter for team or user ownership."""
    if user.default_team_id:
        return model_class.team_id == user.default_team_id
    return model_class.user_id == user.id


def apply_sort(stmt, model, sort: str):
    """Apply sort ordering to a query."""
    if sort == "popular":
        return stmt.order_by(model.downloads.desc())
    if sort == "newest":
        return stmt.order_by(model.created_at.desc())
    if sort == "rating":
        return stmt.order_by(model.rating.desc())
    return stmt.order_by(model.is_featured.desc(), model.downloads.desc())


def paginated_response(items: list, total: int, page: int, limit: int) -> dict:
    """Build a standard paginated response dict."""
    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": math.ceil(total / limit) if limit else 0,
    }
