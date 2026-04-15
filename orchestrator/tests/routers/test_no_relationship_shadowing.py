"""Lint test: Pydantic response models must not shadow SQLAlchemy
``relationship()`` attributes on the ORM class they wrap.

Motivation: when a Pydantic model with ``from_attributes=True`` has a field
name that matches a SQLAlchemy ``relationship`` name on the target ORM row,
``model_validate`` will trigger an implicit lazy-load on the relationship.
In async sessions without ``selectinload``, this raises
``MissingGreenlet`` / ``asyncio_is_in_the_middle_of_another_task`` and
crashes the response serialization path — exactly the
``AppInstance.app_version`` trap we hit before.

This test is deliberately hand-maintained: we keep a small registry mapping
response-model class → ORM class. When a new response model is added that
mirrors an ORM row, register it here and the lint will catch future
field-name collisions automatically.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

# Each entry: ``(pydantic_class, orm_class)``. Only response-like models
# (``from_attributes=True``) that read from a single ORM class belong here.
#
# Tests skip gracefully if any import fails — e.g. when a router has been
# renamed — so the lint never blocks an unrelated rename.


def _load_registry() -> list[tuple[type[BaseModel], type]]:
    registry: list[tuple[type[BaseModel], type]] = []
    try:
        from app.models import AppInstance, AppVersion, MarketplaceApp
        from app.routers.app_installs import AppInstanceSummary
        from app.routers.marketplace_apps import (
            AppVersionSummary,
            MarketplaceAppResponse,
        )

        registry.extend(
            [
                (AppInstanceSummary, AppInstance),
                (MarketplaceAppResponse, MarketplaceApp),
                (AppVersionSummary, AppVersion),
            ]
        )
    except Exception:  # pragma: no cover — import-time breakage is its own failure
        pass
    return registry


REGISTRY = _load_registry()


def _has_from_attributes(pyd_cls: type[BaseModel]) -> bool:
    cfg = getattr(pyd_cls, "model_config", None)
    if isinstance(cfg, dict):
        return bool(cfg.get("from_attributes"))
    return bool(getattr(cfg, "from_attributes", False))


@pytest.mark.parametrize(("pyd_cls", "orm_cls"), REGISTRY)
def test_response_model_does_not_shadow_relationships(
    pyd_cls: type[BaseModel], orm_cls: type
) -> None:
    if not _has_from_attributes(pyd_cls):
        pytest.skip(f"{pyd_cls.__name__} is not from_attributes=True")

    pyd_fields = set(pyd_cls.model_fields.keys())
    rel_names = set(orm_cls.__mapper__.relationships.keys())

    collisions = pyd_fields & rel_names
    assert not collisions, (
        f"{pyd_cls.__name__} shadows {orm_cls.__name__} relationships: "
        + ", ".join(sorted(f"{pyd_cls.__name__}.{name} ↔ {orm_cls.__name__}.{name}"
                           for name in collisions))
        + ". Rename the Pydantic field to break the shadow (this triggers "
          "implicit lazy-load and MissingGreenlet under async)."
    )


def test_registry_not_empty() -> None:
    assert REGISTRY, (
        "relationship-shadow registry is empty — either the response-model "
        "imports broke or nothing has been registered yet. Add entries in "
        "_load_registry()."
    )
