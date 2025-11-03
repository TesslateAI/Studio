#!/usr/bin/env python3
"""
Make an existing user an admin/superuser.

Usage:
    python make_admin.py <email>

Or inside Docker container:
    docker exec tesslate-orchestrator python /app/make_admin.py <email>
"""
import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models_auth import User
# Import all models to ensure relationships are properly resolved
import app.models


async def make_admin(email: str):
    """Make a user an admin by their email address."""
    print("=" * 60)
    print("Make User Admin - Tesslate Studio")
    print("=" * 60)
    print()

    async with AsyncSessionLocal() as session:
        try:
            # Find user by email
            result = await session.execute(
                select(User).where(User.email == email)
            )
            user = result.scalar_one_or_none()

            if not user:
                print(f"❌ Error: User with email '{email}' not found")
                sys.exit(1)

            # Check if already admin
            if user.is_superuser:
                print(f"ℹ️  User '{email}' is already an admin")
                print()
                print("Account Details:")
                print(f"  Email:        {user.email}")
                print(f"  Username:     {user.username}")
                print(f"  Name:         {user.name}")
                print(f"  Is Superuser: {user.is_superuser}")
                print(f"  Is Verified:  {user.is_verified}")
                print()
                return

            # Make user admin
            user.is_superuser = True
            user.is_verified = True  # Also verify the user

            await session.commit()
            await session.refresh(user)

            print(f"✅ User '{email}' has been granted admin privileges!")
            print()
            print("Account Details:")
            print(f"  Email:        {user.email}")
            print(f"  Username:     {user.username}")
            print(f"  Name:         {user.name}")
            print(f"  Is Superuser: {user.is_superuser}")
            print(f"  Is Verified:  {user.is_verified}")
            print()

        except Exception as e:
            print(f"❌ Error making user admin: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)


async def revoke_admin(email: str):
    """Revoke admin privileges from a user."""
    print("=" * 60)
    print("Revoke Admin Privileges - Tesslate Studio")
    print("=" * 60)
    print()

    async with AsyncSessionLocal() as session:
        try:
            # Find user by email
            result = await session.execute(
                select(User).where(User.email == email)
            )
            user = result.scalar_one_or_none()

            if not user:
                print(f"❌ Error: User with email '{email}' not found")
                sys.exit(1)

            # Check if not admin
            if not user.is_superuser:
                print(f"ℹ️  User '{email}' is not an admin")
                return

            # Revoke admin
            user.is_superuser = False

            await session.commit()
            await session.refresh(user)

            print(f"✅ Admin privileges revoked from '{email}'")
            print()

        except Exception as e:
            print(f"❌ Error revoking admin: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)


async def list_admins():
    """List all admin users."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.is_superuser == True)
        )
        admins = result.scalars().all()

        if not admins:
            print("No admin users found in the database.")
            return

        print(f"\nFound {len(admins)} admin user(s):\n")
        for user in admins:
            print(f"  - {user.email} ({user.username}) - {user.name}")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Manage admin privileges")
    parser.add_argument(
        "email",
        nargs="?",
        help="Email address of the user to make admin",
    )
    parser.add_argument(
        "--revoke",
        action="store_true",
        help="Revoke admin privileges instead of granting them",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all admin users",
    )
    args = parser.parse_args()

    if args.list:
        asyncio.run(list_admins())
    elif args.email:
        if args.revoke:
            asyncio.run(revoke_admin(args.email))
        else:
            asyncio.run(make_admin(args.email))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
