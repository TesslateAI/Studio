"""
Seed UI themes from bundled JSON files.

Loads 7 theme definitions (default-dark, default-light, midnight, ocean,
forest, rose, sunset) and upserts them into the themes table.

Can be run standalone or called from the startup seeder.
"""

import json
import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

SORT_ORDERS = {
    "default-dark": 0,
    "default-light": 1,
    "midnight": 2,
    "ocean": 3,
    "forest": 4,
    "rose": 5,
    "sunset": 6,
}


async def seed_themes(db: AsyncSession, themes_dir: Path | None = None) -> int:
    """Seed themes from JSON files. Uses upsert so it's safe to re-run.

    Args:
        db: Async database session.
        themes_dir: Path to directory containing theme JSON files.
                    Defaults to the bundled themes/ directory.

    Returns:
        Number of themes processed.
    """
    if themes_dir is None:
        themes_dir = Path(__file__).parent / "themes"

    if not themes_dir.exists():
        logger.error("Themes directory not found at %s", themes_dir)
        return 0

    theme_files = list(themes_dir.glob("*.json"))
    if not theme_files:
        logger.warning("No theme files found in %s", themes_dir)
        return 0

    # Verify the themes table exists
    try:
        await db.execute(text("SELECT 1 FROM themes LIMIT 1"))
    except Exception:
        logger.error("themes table doesn't exist — run migrations first")
        await db.rollback()
        return 0

    seeded = 0

    for theme_file in theme_files:
        try:
            with open(theme_file, encoding="utf-8") as f:
                theme_data = json.load(f)

            theme_id = theme_data.get("id")
            if not theme_id:
                logger.warning("Skipping %s: missing 'id' field", theme_file.name)
                continue

            sort_order = SORT_ORDERS.get(theme_id, 99)

            theme_json = {
                "colors": theme_data.get("colors", {}),
                "typography": theme_data.get("typography", {}),
                "spacing": theme_data.get("spacing", {}),
                "animation": theme_data.get("animation", {}),
            }

            await db.execute(
                text("""
                    INSERT INTO themes (id, name, mode, author, version, description, theme_json, sort_order, is_default, is_active)
                    VALUES (:id, :name, :mode, :author, :version, :description, :theme_json, :sort_order, :is_default, true)
                    ON CONFLICT (id) DO UPDATE SET
                        name = EXCLUDED.name,
                        mode = EXCLUDED.mode,
                        author = EXCLUDED.author,
                        version = EXCLUDED.version,
                        description = EXCLUDED.description,
                        theme_json = EXCLUDED.theme_json,
                        sort_order = EXCLUDED.sort_order,
                        is_default = EXCLUDED.is_default,
                        updated_at = NOW()
                """),
                {
                    "id": theme_id,
                    "name": theme_data.get("name", theme_id),
                    "mode": theme_data.get("mode", "dark"),
                    "author": theme_data.get("author", "Tesslate"),
                    "version": theme_data.get("version", "1.0.0"),
                    "description": theme_data.get("description"),
                    "theme_json": json.dumps(theme_json),
                    "sort_order": sort_order,
                    "is_default": theme_id in ("default-dark", "default-light"),
                },
            )
            seeded += 1
            logger.info("Seeded theme: %s", theme_id)

        except json.JSONDecodeError as e:
            logger.error("Error parsing %s: %s", theme_file.name, e)
        except Exception as e:
            logger.error("Error processing %s: %s", theme_file.name, e)

    if seeded:
        await db.commit()

    logger.info("Themes: %d processed", seeded)
    return seeded
