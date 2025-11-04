"""
Make a user an admin.

Usage: python scripts/make_user_admin.py <username>
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import User
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def make_admin(username: str):
    """Make a user an admin."""

    async with AsyncSessionLocal() as db:
        try:
            # Find user by username
            result = await db.execute(
                select(User).where(User.username == username)
            )
            user = result.scalar_one_or_none()

            if not user:
                logger.error(f"❌ User '{username}' not found!")
                return False

            if user.is_admin:
                logger.info(f"ℹ️ User '{username}' is already an admin!")
                return True

            # Make user admin
            user.is_admin = True
            await db.commit()

            logger.info(f"✅ User '{username}' is now an admin!")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to make user admin: {e}")
            await db.rollback()
            raise


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/make_user_admin.py <username>")
        sys.exit(1)

    username = sys.argv[1]
    asyncio.run(make_admin(username))
