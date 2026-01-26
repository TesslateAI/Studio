#!/usr/bin/env python3
"""
Seed themes from scripts/themes/*.json into the database.

Usage (from project root):
    # Connect to Docker postgres directly:
    python scripts/seed/seed_themes.py

    # Or with custom DATABASE_URL:
    DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/db" python scripts/seed/seed_themes.py
"""
import asyncio
import json
import os
import sys
from pathlib import Path

# Add orchestrator to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "orchestrator"))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text


# Default database URL - connects to Docker postgres via exposed port
# Note: Uses 'localhost' since we're running from the host machine
DEFAULT_DB_URL = "postgresql+asyncpg://tesslate_user:dev_password_change_me@localhost:5432/tesslate_dev"


async def seed_themes(database_url: str = None, themes_dir: Path = None):
    """Load all theme JSON files and insert/update in database.

    Args:
        database_url: Database connection URL. If None, uses DATABASE_URL env var or default.
        themes_dir: Path to themes directory. If None, auto-detects from script location.
    """
    # Get database URL
    if database_url is None:
        database_url = os.environ.get("DATABASE_URL", DEFAULT_DB_URL)

    # Convert postgres:// to postgresql+asyncpg://
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif database_url.startswith("postgresql://") and "+asyncpg" not in database_url:
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    print(f"Connecting to database...")
    engine = create_async_engine(database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Find themes directory
    if themes_dir is None:
        script_dir = Path(__file__).parent.parent
        themes_dir = script_dir / "themes"

    if not themes_dir.exists():
        print(f"Error: Themes directory not found at {themes_dir}")
        return False

    # Load all theme JSON files
    theme_files = list(themes_dir.glob("*.json"))
    print(f"Found {len(theme_files)} theme files in {themes_dir}")

    if not theme_files:
        print("No theme files found!")
        return False

    async with async_session() as session:
        # Check if themes table exists
        try:
            await session.execute(text("SELECT 1 FROM themes LIMIT 1"))
        except Exception:
            print("Error: themes table doesn't exist. Run database migrations first:")
            print("  docker exec tesslate-orchestrator alembic upgrade head")
            return False

        # Sort order for themes
        sort_orders = {
            "default-dark": 0,
            "default-light": 1,
            "midnight": 2,
            "ocean": 3,
            "forest": 4,
            "rose": 5,
            "sunset": 6,
        }

        seeded_count = 0

        for theme_file in theme_files:
            try:
                with open(theme_file, "r", encoding="utf-8") as f:
                    theme_data = json.load(f)

                theme_id = theme_data.get("id")
                if not theme_id:
                    print(f"  Skipping {theme_file.name}: missing 'id' field")
                    continue

                # Determine sort order
                base_name = theme_id.replace("-dark", "").replace("-light", "")
                sort_order = sort_orders.get(base_name, 99)

                # Prepare theme JSON (everything except top-level metadata)
                theme_json = {
                    "colors": theme_data.get("colors", {}),
                    "typography": theme_data.get("typography", {}),
                    "spacing": theme_data.get("spacing", {}),
                    "animation": theme_data.get("animation", {}),
                }

                # Use upsert pattern
                await session.execute(
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
                    }
                )
                print(f"  Seeded: {theme_id}")
                seeded_count += 1

            except json.JSONDecodeError as e:
                print(f"  Error parsing {theme_file.name}: {e}")
            except Exception as e:
                print(f"  Error processing {theme_file.name}: {e}")

        await session.commit()

        # Get final count
        result = await session.execute(text("SELECT count(*) FROM themes WHERE is_active = true"))
        total = result.scalar()
        print(f"\nDone! Processed {seeded_count} themes. Total active themes: {total}")

    await engine.dispose()
    return True


if __name__ == "__main__":
    asyncio.run(seed_themes())
