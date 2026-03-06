#!/usr/bin/env python3
"""
Fix containers that were created but never initialized (volume_name is None).

This script finds all containers where volume_name is NULL and runs
the initialization task for them manually.
"""
import asyncio
import sys
import os

# Add parent directory to path so we can import from orchestrator
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'orchestrator'))

from app.database import AsyncSessionLocal
from app.models import Container, Project, MarketplaceBase
from app.services.container_initializer import initialize_container_async
from app.services.task_manager import Task, TaskStatus
from sqlalchemy import select
from datetime import datetime


async def fix_uninitialized_containers():
    """Find and initialize all containers with NULL volume_name."""
    async with AsyncSessionLocal() as db:
        # Find all containers with no volume_name
        result = await db.execute(
            select(Container, Project, MarketplaceBase).join(
                Project, Container.project_id == Project.id
            ).outerjoin(
                MarketplaceBase, Container.base_id == MarketplaceBase.id
            ).where(
                Container.volume_name.is_(None)
            )
        )

        containers_to_fix = []
        for container, project, base in result:
            containers_to_fix.append((container, project, base))

        if not containers_to_fix:
            print("✅ No uninitialized containers found!")
            return

        print(f"Found {len(containers_to_fix)} container(s) to initialize:\n")

        for container, project, base in containers_to_fix:
            print(f"  - {container.name} in project '{project.name}' ({project.slug})")

        print(f"\nInitializing...")

        # Initialize each container
        for container, project, base in containers_to_fix:
            try:
                print(f"\n🔧 Initializing {container.name}...")

                # Create a dummy task for progress tracking
                task = Task(
                    id=f'manual-init-{container.id}',
                    user_id=project.owner_id,
                    type='manual_initialization',
                    status=TaskStatus.QUEUED,
                    created_at=datetime.utcnow()
                )

                # Run initialization
                await initialize_container_async(
                    container_id=container.id,
                    project_id=project.id,
                    user_id=project.owner_id,
                    base_slug=base.slug if base else 'main',
                    git_repo_url=base.git_repo_url if base else '',
                    task=task
                )

                print(f"   ✅ Successfully initialized {container.name}")

            except Exception as e:
                print(f"   ❌ Failed to initialize {container.name}: {e}")

        print(f"\n✅ Done! Initialized {len(containers_to_fix)} container(s)")


if __name__ == "__main__":
    print("=" * 60)
    print("Container Initialization Fix Script")
    print("=" * 60)
    print()

    asyncio.run(fix_uninitialized_containers())
