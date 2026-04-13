"""
Seed test scenarios for unified snapshots testing.

Creates a test user (ultra plan) with projects designed to exercise:
1. Timeline DAG with multiple checkpoints and auto-save layers
2. Branch creation and switching
3. Snapshot restore with file content refresh
4. Volume recovery and hibernation flows

HOW TO RUN (inside backend pod):
  python /tmp/seed_test_scenarios.py
"""

import asyncio
import logging
import os
import sys
import time

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
from app.models_team import Team, TeamMembership


async def create_test_user(db) -> User:
    """Create or get the test user with ultra plan and personal team."""
    result = await db.execute(select(User).where(User.email == "test@tesslate.dev"))
    user = result.scalar_one_or_none()
    if user:
        user.subscription_tier = "ultra"
        # Ensure personal team exists
        if not user.default_team_id:
            await _create_personal_team(db, user)
        else:
            # Update team tier too
            team_result = await db.execute(select(Team).where(Team.id == user.default_team_id))
            team = team_result.scalar_one_or_none()
            if team:
                team.subscription_tier = "ultra"
        await db.commit()
        await db.refresh(user)
        logger.info("Test user already exists (upgraded to ultra): %s", user.id)
        return user

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
        subscription_tier="ultra",
    )
    db.add(user)
    await db.flush()

    # Create personal team
    await _create_personal_team(db, user)

    await db.commit()
    await db.refresh(user)
    logger.info("Created test user (ultra plan): %s", user.id)
    return user


async def _create_personal_team(db, user: User):
    """Create a personal team for a user."""
    team_id = uuid4()
    team = Team(
        id=team_id,
        name=f"{user.name}'s Team",
        slug=f"{user.slug}-team",
        is_personal=True,
        created_by_id=user.id,
        subscription_tier="ultra",
    )
    db.add(team)
    await db.flush()

    membership = TeamMembership(
        team_id=team_id,
        user_id=user.id,
        role="admin",
    )
    db.add(membership)
    user.default_team_id = team_id
    logger.info("Created personal team %s for user %s", team_id, user.email)


async def create_project_with_volume(
    db, user: User, name: str, slug: str, template: str | None = None
) -> Project:
    """Create a project with a btrfs volume."""
    result = await db.execute(select(Project).where(Project.slug == slug))
    existing = result.scalar_one_or_none()
    if existing:
        logger.info("Project %s already exists", slug)
        return existing

    from app.services.volume_manager import get_volume_manager

    vm = get_volume_manager()

    if template:
        volume_id, node_name = await vm.create_volume(template=template)
    else:
        volume_id, node_name = await vm.create_volume()

    logger.info("Created volume %s on node %s (template=%s)", volume_id, node_name, template)

    project = Project(
        id=uuid4(),
        name=name,
        slug=slug,
        owner_id=user.id,
        team_id=user.default_team_id,
        volume_id=volume_id,
        cache_node=node_name,
        environment_status="stopped",
        compute_tier="environment",
    )
    db.add(project)
    await db.flush()

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


async def write_files(volume_id: str, files: dict[str, str]):
    """Write files to a volume via FileOps."""
    from app.services.volume_manager import get_volume_manager

    vm = get_volume_manager()
    try:
        client = await vm.get_fileops_client(volume_id)
        async with client:
            for path, content in files.items():
                await client.write_file(volume_id, path, content.encode())
        logger.info("Wrote %d files to volume %s", len(files), volume_id)
    except Exception as e:
        logger.warning("Could not write files to %s: %s", volume_id, e)


async def create_snapshot(volume_id: str, label: str) -> str | None:
    """Create a checkpoint snapshot and return its hash."""
    from app.services.volume_manager import get_volume_manager

    vm = get_volume_manager()
    try:
        hash_val = await vm.create_snapshot(volume_id, label=label)
        logger.info("Created snapshot '%s' → %s", label, hash_val[:16] if hash_val else "?")
        return hash_val
    except Exception as e:
        logger.warning("Could not create snapshot for %s: %s", volume_id, e)
        return None


async def trigger_sync(volume_id: str):
    """Trigger a background sync for a volume."""
    from app.services.volume_manager import get_volume_manager

    vm = get_volume_manager()
    try:
        await vm.trigger_sync(volume_id)
        logger.info("Triggered sync for %s", volume_id)
    except Exception as e:
        logger.warning("Sync trigger failed for %s: %s", volume_id, e)


async def setup_timeline_project(db, user: User):
    """Create a project with rich timeline history.

    This builds up a realistic DAG:
      init → checkpoint "Initial setup" → auto-saves → checkpoint "Add styles"
      → auto-saves → checkpoint "Add interactivity"
    """
    project = await create_project_with_volume(db, user, "Timeline Demo", "timeline-demo")
    if not project.volume_id:
        return project

    vid = project.volume_id

    # Step 1: Initial files
    await write_files(vid, {
        "/app/index.html": """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Timeline Demo</title>
</head>
<body>
  <h1>Hello World</h1>
  <p>This is the initial version.</p>
</body>
</html>""",
        "/app/package.json": '{"name": "timeline-demo", "version": "1.0.0", "scripts": {"dev": "npx serve ."}}',
        "/app/README.md": "# Timeline Demo\n\nA project to test the snapshot timeline UI.\n",
    })

    # Trigger sync (creates auto-save layer)
    await trigger_sync(vid)
    await asyncio.sleep(2)

    # Checkpoint 1
    await create_snapshot(vid, "Initial setup")
    await asyncio.sleep(1)

    # Step 2: Add styles
    await write_files(vid, {
        "/app/styles.css": """body {
  font-family: 'Inter', sans-serif;
  max-width: 800px;
  margin: 0 auto;
  padding: 2rem;
  background: #f8f9fa;
  color: #212529;
}

h1 { color: #6c5ce7; }
""",
        "/app/index.html": """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Timeline Demo</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <h1>Hello World</h1>
  <p>Now with styles!</p>
  <div class="card">
    <h2>Features</h2>
    <ul>
      <li>Snapshot timeline</li>
      <li>Branch support</li>
      <li>Instant restore</li>
    </ul>
  </div>
</body>
</html>""",
    })

    await trigger_sync(vid)
    await asyncio.sleep(2)

    # Checkpoint 2
    await create_snapshot(vid, "Add styles")
    await asyncio.sleep(1)

    # Step 3: Add interactivity
    await write_files(vid, {
        "/app/app.js": """document.addEventListener('DOMContentLoaded', () => {
  const btn = document.createElement('button');
  btn.textContent = 'Click me!';
  btn.style.cssText = 'padding: 12px 24px; background: #6c5ce7; color: white; border: none; border-radius: 8px; cursor: pointer; font-size: 16px;';
  btn.addEventListener('click', () => {
    btn.textContent = 'Clicked! 🎉';
    setTimeout(() => { btn.textContent = 'Click me!'; }, 2000);
  });
  document.body.appendChild(btn);
});
""",
        "/app/index.html": """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Timeline Demo</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <h1>Timeline Demo</h1>
  <p>Interactive version with JavaScript!</p>
  <div class="card">
    <h2>Features</h2>
    <ul>
      <li>Snapshot timeline</li>
      <li>Branch support</li>
      <li>Instant restore</li>
      <li>Interactive elements</li>
    </ul>
  </div>
  <script src="app.js"></script>
</body>
</html>""",
    })

    await trigger_sync(vid)
    await asyncio.sleep(2)

    # Checkpoint 3
    await create_snapshot(vid, "Add interactivity")

    logger.info("Timeline Demo: 3 checkpoints + auto-save layers created")
    return project


async def setup_restore_project(db, user: User):
    """Create a project for testing restore flows.

    Has 2 clearly different checkpoints so restore visually changes files.
    """
    project = await create_project_with_volume(db, user, "Restore Test", "restore-test")
    if not project.volume_id:
        return project

    vid = project.volume_id

    # Version A: Blue theme
    await write_files(vid, {
        "/app/index.html": """<!DOCTYPE html>
<html><head><title>Restore Test</title>
<style>body { background: #2196F3; color: white; font-family: sans-serif; text-align: center; padding: 4rem; }</style>
</head><body>
<h1>Version A - Blue</h1>
<p>If you see this after restore, it worked!</p>
</body></html>""",
        "/app/package.json": '{"name": "restore-test", "version": "1.0.0", "scripts": {"dev": "npx serve ."}}',
    })

    await trigger_sync(vid)
    await asyncio.sleep(2)
    hash_a = await create_snapshot(vid, "Version A - Blue")
    await asyncio.sleep(1)

    # Version B: Green theme (current state)
    await write_files(vid, {
        "/app/index.html": """<!DOCTYPE html>
<html><head><title>Restore Test</title>
<style>body { background: #4CAF50; color: white; font-family: sans-serif; text-align: center; padding: 4rem; }</style>
</head><body>
<h1>Version B - Green</h1>
<p>This is the current version. Restore to go back to Blue.</p>
</body></html>""",
    })

    await trigger_sync(vid)
    await asyncio.sleep(2)
    await create_snapshot(vid, "Version B - Green")

    logger.info("Restore Test: 2 checkpoints (Blue → Green), restore Blue to verify")
    return project


async def setup_hibernation_project(db, user: User):
    """Create a hibernated project for testing wake-up flow."""
    project = await create_project_with_volume(db, user, "Hibernated App", "hibernated-app")
    if not project.volume_id:
        return project

    vid = project.volume_id

    await write_files(vid, {
        "/app/index.html": """<!DOCTYPE html>
<html><head><title>Hibernated App</title></head>
<body><h1>Wake me up!</h1><p>This project was hibernated.</p></body></html>""",
        "/app/package.json": '{"name": "hibernated-app", "version": "1.0.0", "scripts": {"dev": "npx serve ."}}',
    })

    await trigger_sync(vid)
    await asyncio.sleep(2)
    await create_snapshot(vid, "Before hibernation")

    # Mark as hibernated
    project.environment_status = "hibernated"
    await db.commit()

    logger.info("Hibernated App: ready for wake-up testing")
    return project


async def setup_empty_project(db, user: User):
    """Create an empty project (no files, no snapshots)."""
    project = await create_project_with_volume(db, user, "Empty Project", "empty-project")
    logger.info("Empty Project: no files, no snapshots — tests empty timeline state")
    return project


async def main():
    logger.info("=== Seeding Unified Snapshots Test Scenarios ===")

    async with AsyncSessionLocal() as db:
        # 1. Create test user with ultra plan
        user = await create_test_user(db)

        # 2. Timeline Demo — rich history with multiple checkpoints
        await setup_timeline_project(db, user)

        # 3. Restore Test — two clearly different checkpoints
        await setup_restore_project(db, user)

        # 4. Hibernated App — for wake-up flow
        await setup_hibernation_project(db, user)

        # 5. Empty Project — tests empty state
        await setup_empty_project(db, user)

    logger.info("")
    logger.info("=== Test Scenarios Ready ===")
    logger.info("")
    logger.info("Login credentials:")
    logger.info("  Email:    test@tesslate.dev")
    logger.info("  Password: testtest123")
    logger.info("  Plan:     ultra")
    logger.info("")
    logger.info("Projects:")
    logger.info("  1. Timeline Demo   — 3 checkpoints + auto-saves (test timeline UI, branching)")
    logger.info("  2. Restore Test    — Blue→Green checkpoints (test restore with visual diff)")
    logger.info("  3. Hibernated App  — hibernated state (test wake-up flow)")
    logger.info("  4. Empty Project   — no files/snapshots (test empty timeline)")
    logger.info("")
    logger.info("Test plan:")
    logger.info("  - Timeline Demo: open timeline panel, verify DAG, create branch, switch branches")
    logger.info("  - Restore Test: restore to 'Version A - Blue', verify files + preview change")
    logger.info("  - Hibernated App: open project, verify hibernation UI, click Start")
    logger.info("  - Empty Project: open timeline, verify empty state message")


if __name__ == "__main__":
    asyncio.run(main())
