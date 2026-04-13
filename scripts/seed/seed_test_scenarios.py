"""
Seed test scenarios for volume recovery testing.

Creates a test user with multiple projects in different states:
1. "Working App" — healthy project with volume, files written
2. "Hibernated App" — project that was stopped/hibernated
3. "Forked App" — forked from Working App
4. "Empty App" — project with no template, minimal files

After running, you can test recovery by:
- Cordoning nodes to simulate node death
- Restarting CSI pods
- Using the volume/status and volume/recover endpoints

HOW TO RUN (inside backend pod):
  python /tmp/seed_test_scenarios.py
"""

import asyncio
import logging
import os
import sys

if os.path.exists("/app/app"):
    sys.path.insert(0, "/app")
else:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "orchestrator"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

from uuid import uuid4

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Container, Project, User


async def create_test_user(db) -> User:
    """Create or get the test user."""
    result = await db.execute(select(User).where(User.email == "test@tesslate.dev"))
    user = result.scalar_one_or_none()
    if user:
        logger.info("Test user already exists: %s", user.id)
        return user

    # Hash password using pwdlib (same as fastapi-users)
    from pwdlib import PasswordHash
    from pwdlib.hashers.bcrypt import BcryptHasher

    hasher = PasswordHash((BcryptHasher(),))
    hashed = hasher.hash("testtest123")

    user = User(
        id=uuid4(),
        email="test@tesslate.dev",
        hashed_password=hashed,
        name="Test User",
        username="testuser",
        slug="testuser",
        is_active=True,
        is_verified=True,
        is_superuser=False,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info("Created test user: %s", user.id)
    return user


async def create_project_with_volume(
    db, user: User, name: str, slug: str, template: str | None = None
) -> Project:
    """Create a project with a btrfs volume."""
    # Check if project already exists
    result = await db.execute(select(Project).where(Project.slug == slug))
    existing = result.scalar_one_or_none()
    if existing:
        logger.info("Project %s already exists", slug)
        return existing

    # Create volume via Hub
    from app.services.volume_manager import get_volume_manager

    vm = get_volume_manager()

    if template:
        volume_id, node_name = await vm.create_volume(template=template)
    else:
        volume_id, node_name = await vm.create_volume()

    logger.info("Created volume %s on node %s (template=%s)", volume_id, node_name, template)

    # Create project record
    project = Project(
        id=uuid4(),
        name=name,
        slug=slug,
        owner_id=user.id,
        volume_id=volume_id,
        cache_node=node_name,
        environment_status="stopped",
        compute_tier="environment",
    )
    db.add(project)
    await db.flush()

    # Add a default container
    container = Container(
        id=uuid4(),
        project_id=project.id,
        name="frontend",
        container_name=f"{slug}-frontend",
        internal_port=3000,
        startup_command="npm run dev",
        directory="/app",
    )
    db.add(container)
    await db.commit()

    logger.info("Created project %s (volume=%s, node=%s)", slug, volume_id, node_name)
    return project


async def write_test_files(volume_id: str, project_name: str):
    """Write some test files to a volume via FileOps."""
    from app.services.volume_manager import get_volume_manager

    vm = get_volume_manager()
    try:
        client = await vm.get_fileops_client(volume_id)
        async with client:
            # Write a simple index.html
            html = f"""<!DOCTYPE html>
<html>
<head><title>{project_name}</title></head>
<body>
<h1>{project_name}</h1>
<p>This is a test project created for volume recovery testing.</p>
<p>Volume ID: {volume_id}</p>
</body>
</html>""".encode()
            await client.write_file(volume_id, "/index.html", html)

            # Write a package.json
            pkg = f'{{"name": "{project_name.lower().replace(" ", "-")}", "version": "1.0.0"}}'.encode()
            await client.write_file(volume_id, "/package.json", pkg)

            # Write a README
            readme = f"# {project_name}\n\nTest project for volume recovery.\n".encode()
            await client.write_file(volume_id, "/README.md", readme)

        logger.info("Wrote test files to volume %s", volume_id)
    except Exception as e:
        logger.warning("Could not write test files to %s: %s", volume_id, e)


async def main():
    logger.info("=== Seeding Test Scenarios ===")

    async with AsyncSessionLocal() as db:
        # 1. Create test user
        user = await create_test_user(db)

        # 2. Create "Working App" — healthy project with files
        working = await create_project_with_volume(
            db, user, "Working App", "working-app", template=None
        )
        if working.volume_id:
            await write_test_files(working.volume_id, "Working App")
            # Trigger sync so there's CAS data for recovery
            from app.services.volume_manager import get_volume_manager
            vm = get_volume_manager()
            try:
                await vm.trigger_sync(working.volume_id)
                logger.info("Triggered sync for Working App")
            except Exception as e:
                logger.warning("Sync trigger failed: %s", e)

        # 3. Create "Hibernated App" — simulate hibernated state
        hibernated = await create_project_with_volume(
            db, user, "Hibernated App", "hibernated-app", template=None
        )
        if hibernated.volume_id:
            await write_test_files(hibernated.volume_id, "Hibernated App")
            # Mark as hibernated
            hibernated.environment_status = "hibernated"
            await db.commit()
            logger.info("Marked Hibernated App as hibernated")

        # 4. Create "Forked App" — fork from Working App
        if working.volume_id:
            result = await db.execute(select(Project).where(Project.slug == "forked-app"))
            existing_fork = result.scalar_one_or_none()
            if not existing_fork:
                vm = get_volume_manager()
                try:
                    fork_vol_id, fork_node = await vm.fork_volume(working.volume_id)
                    fork_project = Project(
                        id=uuid4(),
                        name="Forked App",
                        slug="forked-app",
                        owner_id=user.id,
                        volume_id=fork_vol_id,
                        cache_node=fork_node,
                        environment_status="stopped",
                        compute_tier="environment",
                    )
                    db.add(fork_project)
                    fork_container = Container(
                        id=uuid4(),
                        project_id=fork_project.id,
                        name="frontend",
                        container_name="forked-app-frontend",
                        internal_port=3000,
                        startup_command="npm run dev",
                        directory="/app",
                    )
                    db.add(fork_container)
                    await db.commit()
                    logger.info("Created Forked App (volume=%s, node=%s)", fork_vol_id, fork_node)
                except Exception as e:
                    logger.warning("Could not fork: %s", e)
            else:
                logger.info("Forked App already exists")

        # 5. Create "Empty App" — no template, minimal
        await create_project_with_volume(
            db, user, "Empty App", "empty-app", template=None
        )

    logger.info("")
    logger.info("=== Test Scenarios Ready ===")
    logger.info("")
    logger.info("Login credentials:")
    logger.info("  Email:    test@tesslate.dev")
    logger.info("  Password: testtest123")
    logger.info("")
    logger.info("Projects created:")
    logger.info("  1. Working App    — has files, synced to CAS")
    logger.info("  2. Hibernated App — has files, status=hibernated")
    logger.info("  3. Forked App     — forked from Working App (CoW clone)")
    logger.info("  4. Empty App      — empty volume, no files")
    logger.info("")
    logger.info("To test recovery:")
    logger.info("  1. Start a project via UI")
    logger.info("  2. Cordon the node or restart CSI to simulate failure")
    logger.info("  3. Try file operations — auto-recovery should kick in")
    logger.info("  4. Or use the 'Recover Storage' button if container start fails")


if __name__ == "__main__":
    asyncio.run(main())
