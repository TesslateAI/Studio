"""Contract templates router — reusable starter contracts for automations.

Phase 5 polish endpoint set:

* ``GET    /api/contract-templates`` — list published templates, optionally
  filter by ``category``.
* ``GET    /api/contract-templates/{id}`` — fetch a single template.
* ``POST   /api/contract-templates`` — authenticated users create a new
  template (defaults to ``is_published=True`` so the user sees it in the
  marketplace immediately; an admin can later un-publish bad rows).
* ``DELETE /api/contract-templates/{id}`` — owner or superuser only.
* ``POST   /api/contract-templates/{id}/apply`` — returns the contract JSON
  ready to drop into a new automation. The frontend calls this and
  prefills :class:`AutomationCreatePage`'s ``ContractEditor``. The endpoint
  *does not* create an automation — the caller still goes through the
  normal ``POST /api/automations`` flow with the user-edited contract.

Auth model
----------
Read endpoints accept any authenticated user. Write endpoints require the
session user. ``DELETE`` enforces owner OR superuser. ``apply`` is a read
operation under the hood so we mirror the read auth.

Validation
----------
``contract_json`` MUST be a non-empty JSON object — same rule the
:class:`AutomationDefinitionIn` schema applies to the contract on a real
automation. We enforce here so a template that would create an invalid
automation is rejected at template-create time, not later.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import ContractTemplate, User
from ..users import current_active_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/contract-templates", tags=["contract-templates"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ContractTemplateOut(BaseModel):
    id: UUID
    name: str
    description: str | None
    category: str
    contract_json: dict[str, Any]
    created_by_user_id: UUID | None
    is_published: bool

    model_config = {"from_attributes": True}


class ContractTemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    category: str = Field(default="general", max_length=48)
    contract_json: dict[str, Any]
    is_published: bool = True

    @field_validator("contract_json")
    @classmethod
    def _non_empty_contract(cls, v: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(v, dict):
            raise ValueError("contract_json must be a JSON object")
        if not v:
            raise ValueError("contract_json must contain at least one key")
        return v


class ContractApplyOut(BaseModel):
    """Response from ``POST /{id}/apply`` — the contract the form should
    prefill, plus a few hints the form can render alongside.
    """

    template_id: UUID
    template_name: str
    contract: dict[str, Any]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=list[ContractTemplateOut])
async def list_templates(
    category: str | None = Query(default=None, max_length=48),
    include_unpublished: bool = Query(default=False),
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> list[ContractTemplate]:
    """Browse published contract templates.

    ``include_unpublished=true`` is honored only for superusers — regular
    users always see the published catalog so a draft row can't leak via
    a query-string flag.
    """
    stmt = select(ContractTemplate).order_by(ContractTemplate.created_at.desc())
    if not (include_unpublished and getattr(user, "is_superuser", False)):
        stmt = stmt.where(ContractTemplate.is_published.is_(True))
    if category:
        stmt = stmt.where(ContractTemplate.category == category)
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows)


@router.get("/{template_id}", response_model=ContractTemplateOut)
async def get_template(
    template_id: UUID,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ContractTemplate:
    row = await db.get(ContractTemplate, template_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Contract template not found")
    if not row.is_published and not (
        getattr(user, "is_superuser", False)
        or row.created_by_user_id == user.id
    ):
        # Hide unpublished templates from non-owners — same 404 trick as
        # the automations router uses for owner gating.
        raise HTTPException(status_code=404, detail="Contract template not found")
    return row


@router.post("", response_model=ContractTemplateOut, status_code=201)
async def create_template(
    payload: ContractTemplateIn,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ContractTemplate:
    row = ContractTemplate(
        name=payload.name,
        description=payload.description,
        category=payload.category or "general",
        contract_json=payload.contract_json,
        created_by_user_id=user.id,
        is_published=payload.is_published,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/{template_id}", status_code=204, response_class=Response)
async def delete_template(
    template_id: UUID,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    row = await db.get(ContractTemplate, template_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Contract template not found")
    if row.created_by_user_id != user.id and not getattr(user, "is_superuser", False):
        raise HTTPException(status_code=403, detail="Not the template owner")
    await db.delete(row)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{template_id}/apply", response_model=ContractApplyOut)
async def apply_template(
    template_id: UUID,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ContractApplyOut:
    """Return a contract dict ready for the AutomationCreatePage form.

    No DB writes — the frontend calls ``POST /api/automations`` with the
    user-edited contract afterwards.
    """
    row = await db.get(ContractTemplate, template_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Contract template not found")
    if not row.is_published and not (
        getattr(user, "is_superuser", False)
        or row.created_by_user_id == user.id
    ):
        raise HTTPException(status_code=404, detail="Contract template not found")

    # Defensive copy so the caller can't mutate the cached SA dict.
    contract = dict(row.contract_json or {})
    return ContractApplyOut(
        template_id=row.id,
        template_name=row.name,
        contract=contract,
    )
