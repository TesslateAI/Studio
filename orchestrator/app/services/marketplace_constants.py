"""Stable identifiers for the federated marketplace.

These two UUIDs are seeded by alembic 0088 with the literal values below
and never rotate. Callers reference them by constant — never by handle
lookup at hot paths — so the application can construct ``source_id`` FKs
without a round-trip to ``marketplace_sources``.

``TESSLATE_OFFICIAL_ID``
    The canonical Tesslate-hosted hub. Every system seed assigns
    ``source_id`` to this constant. The corresponding ``trust_level`` is
    ``official`` and the ``base_url`` points at marketplace.tesslate.com.

``LOCAL_SOURCE_ID``
    Sentinel "filesystem / draft" source. User-authored creates (custom
    agents, theme drafts, project-derived bases, app forks pre-publish)
    set ``source_id`` to this constant. ``trust_level`` is ``local`` and
    the ``base_url`` is the sentinel ``local://filesystem``.
"""

from __future__ import annotations

import uuid

TESSLATE_OFFICIAL_ID: uuid.UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")
LOCAL_SOURCE_ID: uuid.UUID = uuid.UUID("00000000-0000-0000-0000-000000000002")
