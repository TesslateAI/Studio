"""Dialect-agnostic UUID column type.

Postgres stores natively as ``UUID``; SQLite and other backends store as
``CHAR(36)``. Python values are always ``uuid.UUID`` regardless of dialect,
so application code is identical across deployments.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.types import CHAR, TypeDecorator, TypeEngine


class GUID(TypeDecorator):
    """Platform-independent UUID column.

    Uses Postgres ``UUID`` when available, otherwise ``CHAR(36)`` with
    canonical string form.
    """

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        if isinstance(value, uuid.UUID):
            return str(value)
        return str(uuid.UUID(str(value)))

    def process_result_value(self, value: Any, dialect: Any) -> uuid.UUID | None:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))
