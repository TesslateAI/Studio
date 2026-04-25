"""
Theme API endpoints.

Themes are stored in the database and served via API.
These endpoints are public (no auth required) so themes can load before login.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Theme
from ..schemas_theme import validate_theme_json

logger = logging.getLogger(__name__)

router = APIRouter()


class ThemeResponse(BaseModel):
    """Theme response matching the frontend ThemePreset interface."""

    id: str
    name: str
    mode: str  # "dark" or "light"
    author: str | None = None
    version: str | None = None
    description: str | None = None
    colors: dict
    typography: dict
    spacing: dict
    animation: dict
    # Top-level toggle: when true, the frontend forces every border CSS
    # variable to transparent for this theme. Defaults to False so any
    # theme that predates this field renders with its original borders.
    borderless: bool = False

    class Config:
        from_attributes = True


class ThemeListItem(BaseModel):
    """Lightweight theme info for listing."""

    id: str
    name: str
    mode: str
    author: str | None = None
    description: str | None = None

    class Config:
        from_attributes = True


@router.get("", response_model=list[ThemeListItem])
async def list_themes(db: AsyncSession = Depends(get_db)):
    """List all available themes (lightweight, no full JSON)."""
    result = await db.execute(
        select(Theme).where(Theme.is_active).order_by(Theme.sort_order, Theme.name)
    )
    themes = result.scalars().all()

    return [
        ThemeListItem(
            id=theme.id,
            name=theme.name,
            mode=theme.mode,
            author=theme.author,
            description=theme.description,
        )
        for theme in themes
    ]


@router.get("/full", response_model=list[ThemeResponse])
async def list_themes_full(db: AsyncSession = Depends(get_db)):
    """List all themes with full JSON (for theme picker preview)."""
    result = await db.execute(
        select(Theme).where(Theme.is_active).order_by(Theme.sort_order, Theme.name)
    )
    themes = result.scalars().all()

    responses = []
    for theme in themes:
        # Validate theme JSON and log any issues
        is_valid, error, _ = validate_theme_json(theme.theme_json)
        if not is_valid:
            logger.warning(f"Theme validation failed: theme_id={theme.id}, error={error}")

        responses.append(
            ThemeResponse(
                id=theme.id,
                name=theme.name,
                mode=theme.mode,
                author=theme.author,
                version=theme.version,
                description=theme.description,
                colors=theme.theme_json.get("colors", {}),
                typography=theme.theme_json.get("typography", {}),
                spacing=theme.theme_json.get("spacing", {}),
                animation=theme.theme_json.get("animation", {}),
                borderless=bool(theme.theme_json.get("borderless", False)),
            )
        )

    return responses


@router.get("/{theme_id}", response_model=ThemeResponse)
async def get_theme(theme_id: str, db: AsyncSession = Depends(get_db)):
    """Get a single theme by ID with full JSON."""
    result = await db.execute(select(Theme).where(Theme.id == theme_id, Theme.is_active))
    theme = result.scalar_one_or_none()

    if not theme:
        raise HTTPException(status_code=404, detail=f"Theme '{theme_id}' not found")

    # Validate theme JSON and log any issues (non-blocking)
    is_valid, error, _ = validate_theme_json(theme.theme_json)
    if not is_valid:
        logger.warning(f"Theme validation failed: theme_id={theme.id}, error={error}")

    return ThemeResponse(
        id=theme.id,
        name=theme.name,
        mode=theme.mode,
        author=theme.author,
        version=theme.version,
        description=theme.description,
        colors=theme.theme_json.get("colors", {}),
        typography=theme.theme_json.get("typography", {}),
        spacing=theme.theme_json.get("spacing", {}),
        animation=theme.theme_json.get("animation", {}),
        borderless=bool(theme.theme_json.get("borderless", False)),
    )


@router.get("/default/{mode}")
async def get_default_theme(mode: str, db: AsyncSession = Depends(get_db)):
    """Get the default theme for a given mode (dark/light)."""
    if mode not in ("dark", "light"):
        raise HTTPException(status_code=400, detail="Mode must be 'dark' or 'light'")

    # Try to find a default theme for the mode
    result = await db.execute(
        select(Theme).where(Theme.mode == mode, Theme.is_default, Theme.is_active).limit(1)
    )
    theme = result.scalar_one_or_none()

    # If no default, fall back to first theme of that mode
    if not theme:
        result = await db.execute(
            select(Theme)
            .where(Theme.mode == mode, Theme.is_active)
            .order_by(Theme.sort_order)
            .limit(1)
        )
        theme = result.scalar_one_or_none()

    if not theme:
        raise HTTPException(status_code=404, detail=f"No {mode} theme available")

    return ThemeResponse(
        id=theme.id,
        name=theme.name,
        mode=theme.mode,
        author=theme.author,
        version=theme.version,
        description=theme.description,
        colors=theme.theme_json.get("colors", {}),
        typography=theme.theme_json.get("typography", {}),
        spacing=theme.theme_json.get("spacing", {}),
        animation=theme.theme_json.get("animation", {}),
        borderless=bool(theme.theme_json.get("borderless", False)),
    )
