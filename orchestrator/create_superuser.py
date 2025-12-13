#!/usr/bin/env python3
"""
Create a superuser account for Tesslate Studio.

This script creates a superuser (admin) account with full access to the system.
Run this script after setting up the database and running migrations.

Usage:
    python create_superuser.py

Or inside Docker container:
    docker exec tesslate-orchestrator python /app/create_superuser.py
"""
import asyncio
import sys
from getpass import getpass

from nanoid import generate
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models_auth import User
from app.users import UserManager, get_user_db


async def create_superuser():
    """Create a superuser interactively."""
    print("=" * 60)
    print("Create Superuser Account for Tesslate Studio")
    print("=" * 60)
    print()

    # Collect user information
    email = input("Email address: ").strip()
    if not email:
        print("❌ Error: Email is required")
        sys.exit(1)

    name = input("Full name: ").strip()
    if not name:
        print("❌ Error: Name is required")
        sys.exit(1)

    username = input("Username: ").strip()
    if not username:
        print("❌ Error: Username is required")
        sys.exit(1)

    # Password with confirmation
    while True:
        password = getpass("Password (min 6 characters): ")
        if len(password) < 6:
            print("❌ Password must be at least 6 characters long")
            continue

        password_confirm = getpass("Confirm password: ")
        if password != password_confirm:
            print("❌ Passwords do not match. Try again.")
            continue

        break

    print()
    print("Creating superuser...")

    async with AsyncSessionLocal() as session:
        try:
            # Check if email already exists
            result = await session.execute(
                select(User).where(User.email == email)
            )
            existing_user = result.scalar_one_or_none()

            if existing_user:
                print(f"❌ Error: User with email '{email}' already exists")
                sys.exit(1)

            # Check if username already exists
            result = await session.execute(
                select(User).where(User.username == username)
            )
            existing_user = result.scalar_one_or_none()

            if existing_user:
                print(f"❌ Error: Username '{username}' is already taken")
                sys.exit(1)

            # Create user manager to handle password hashing
            user_db = get_user_db.__wrapped__(session)  # Get the actual function
            user_manager = UserManager(user_db)

            # Hash the password
            hashed_password = user_manager.password_helper.hash(password)

            # Generate slug and referral code
            slug = f"{username.lower().replace('_', '-').replace(' ', '-')}-{generate(size=6)}"
            referral_code = generate(size=8).upper()

            # Create superuser
            superuser = User(
                email=email,
                hashed_password=hashed_password,
                name=name,
                username=username,
                slug=slug,
                referral_code=referral_code,
                is_active=True,
                is_superuser=True,
                is_verified=True,
                subscription_tier="free",
                total_spend=0,
                credits_balance=0,
            )

            session.add(superuser)
            await session.commit()
            await session.refresh(superuser)

            print()
            print("✅ Superuser created successfully!")
            print()
            print("Account Details:")
            print(f"  Email:          {superuser.email}")
            print(f"  Username:       {superuser.username}")
            print(f"  Name:           {superuser.name}")
            print(f"  Slug:           {superuser.slug}")
            print(f"  Referral Code:  {superuser.referral_code}")
            print(f"  Is Superuser:   {superuser.is_superuser}")
            print(f"  Is Verified:    {superuser.is_verified}")
            print()
            print("You can now log in with your email and password!")
            print()

        except Exception as e:
            print(f"❌ Error creating superuser: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)


async def list_superusers():
    """List all existing superusers."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.is_superuser == True)
        )
        superusers = result.scalars().all()

        if not superusers:
            print("No superusers found in the database.")
            return

        print(f"\nFound {len(superusers)} superuser(s):\n")
        for user in superusers:
            print(f"  - {user.email} ({user.username}) - {user.name}")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Manage superuser accounts")
    parser.add_argument(
        "--list",
        action="store_true",
        help="List existing superusers instead of creating one",
    )
    args = parser.parse_args()

    if args.list:
        asyncio.run(list_superusers())
    else:
        asyncio.run(create_superuser())


if __name__ == "__main__":
    main()
