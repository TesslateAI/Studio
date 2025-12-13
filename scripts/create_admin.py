#!/usr/bin/env python3
"""
Create or update admin user for Tesslate Studio.

Usage:
    python scripts/create_admin.py

This will create user 'a' with password 'aaaaaa' as an admin.
"""

import sys
import asyncio
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "orchestrator"))

from app.database import get_db
from app.models import User
import bcrypt
from sqlalchemy import select


async def create_admin_user():
    """Create or update admin user 'a' with password 'aaaaaa'."""

    username = "a"
    password = "aaaaaa"

    # Hash the password
    password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    async for session in get_db():
        # Check if user exists
        result = await session.execute(select(User).where(User.username == username))
        existing = result.scalar_one_or_none()

        if existing:
            # Update existing user to be admin
            existing.hashed_password = password_hash
            existing.is_admin = True
            await session.commit()
            print(f"✓ User '{username}' updated to admin")
            print(f"  Password: {password}")
        else:
            # Create new admin user
            admin = User(
                name="Admin",
                username=username,
                slug=username,
                email=f"{username}@tesslate.local",
                hashed_password=password_hash,
                is_admin=True,
                is_active=True
            )
            session.add(admin)
            await session.commit()
            print(f"✓ Admin user created")
            print(f"  Username: {username}")
            print(f"  Password: {password}")

        break


if __name__ == "__main__":
    print("Creating admin user...")
    asyncio.run(create_admin_user())
