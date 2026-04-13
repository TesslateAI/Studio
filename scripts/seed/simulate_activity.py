"""
Simulate realistic user activity on test projects.

Runs random operations (file writes, reads, snapshots, syncs, forks)
across the test user's projects to populate them with real data and
CAS snapshot history for UI testing.

HOW TO RUN (inside backend pod):
  python /tmp/simulate_activity.py
"""

import asyncio
import hashlib
import logging
import os
import random
import string
import sys
import time

if os.path.exists("/app/app"):
    sys.path.insert(0, "/app")
else:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "orchestrator"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

from uuid import uuid4

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Container, Project, User


def rand_str(n=6):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def rand_content(kind="code"):
    """Generate realistic-looking file content."""
    if kind == "html":
        title = random.choice(["Dashboard", "Settings", "Profile", "Home", "About"])
        return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>{title}</title></head>
<body>
  <div id="app">
    <h1>{title}</h1>
    <p>Last updated: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>
    <p>Build: {rand_str(8)}</p>
  </div>
  <script src="/main.js"></script>
</body>
</html>"""
    elif kind == "css":
        color = random.choice(["#3b82f6", "#ef4444", "#22c55e", "#a855f7", "#f59e0b"])
        return f"""/* Generated styles — {rand_str(4)} */
:root {{
  --primary: {color};
  --bg: #0f172a;
  --text: #e2e8f0;
}}
body {{ margin: 0; font-family: system-ui; background: var(--bg); color: var(--text); }}
.container {{ max-width: 1200px; margin: 0 auto; padding: 2rem; }}
.btn {{ background: var(--primary); color: white; padding: 0.5rem 1rem; border-radius: 0.5rem; }}
"""
    elif kind == "json":
        return f'{{"name": "project-{rand_str(4)}", "version": "1.{random.randint(0,9)}.{random.randint(0,99)}", "private": true}}'
    elif kind == "js":
        fn = random.choice(["fetchData", "handleSubmit", "loadConfig", "processQueue", "validateInput"])
        return f"""// {fn}.js — {rand_str(4)}
export async function {fn}(params) {{
  const response = await fetch('/api/{fn.lower()}', {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify(params),
  }});
  if (!response.ok) throw new Error(`${{response.status}}`);
  return response.json();
}}
"""
    else:
        return f"# Config {rand_str(4)}\n{rand_str(20)}\n"


FILE_TEMPLATES = [
    ("index.html", "html"),
    ("styles.css", "css"),
    ("package.json", "json"),
    ("src/main.js", "js"),
    ("src/utils.js", "js"),
    ("src/api.js", "js"),
    ("src/components/App.js", "js"),
    ("src/components/Header.js", "js"),
    ("public/index.html", "html"),
    ("config.json", "json"),
    (".env", "config"),
    ("README.md", "config"),
]


async def write_files(vm, volume_id, n=5):
    """Write random files to a volume."""
    client = await vm.get_fileops_client(volume_id)
    files_written = []
    selected = random.sample(FILE_TEMPLATES, min(n, len(FILE_TEMPLATES)))
    async with client:
        for path, kind in selected:
            content = rand_content(kind)
            # Ensure parent dirs exist
            if "/" in path:
                dir_path = "/".join(path.split("/")[:-1])
                try:
                    await client.mkdir(volume_id, f"/{dir_path}")
                except Exception:
                    pass
            await client.write_file(volume_id, f"/{path}", content.encode())
            files_written.append(path)
    return files_written


async def read_files(vm, volume_id, paths):
    """Read files back to verify they exist."""
    client = await vm.get_fileops_client(volume_id)
    results = {}
    async with client:
        for path in paths:
            try:
                data = await client.read_file(volume_id, f"/{path}")
                results[path] = hashlib.sha256(data).hexdigest()[:12]
            except Exception as e:
                results[path] = f"error:{e}"
    return results


async def simulate_project_activity(db, vm, project, cycles=8):
    """Run random operations on a single project."""
    vol = project.volume_id
    if not vol:
        logger.warning("  Skipping %s — no volume", project.slug)
        return

    written_files = []
    snapshot_hashes = []

    for cycle in range(1, cycles + 1):
        action = random.choice(["write", "write", "write", "read", "snapshot", "sync"])
        try:
            if action == "write":
                n = random.randint(2, 6)
                files = await write_files(vm, vol, n)
                written_files.extend(files)
                written_files = list(set(written_files))  # dedupe
                logger.info("  [%s] cycle %d: wrote %d files (%s)", project.slug, cycle, n, ", ".join(files[:3]))

            elif action == "read" and written_files:
                sample = random.sample(written_files, min(3, len(written_files)))
                results = await read_files(vm, vol, sample)
                ok = sum(1 for v in results.values() if not v.startswith("error"))
                logger.info("  [%s] cycle %d: read %d files, %d ok", project.slug, cycle, len(sample), ok)

            elif action == "snapshot":
                labels = ["Before refactor", "Working state", "After deploy fix", "Clean build", "Feature complete", "Bug fix applied"]
                label = random.choice(labels)
                h = await vm.create_snapshot(vol, label=label)
                snapshot_hashes.append(h)
                logger.info("  [%s] cycle %d: snapshot '%s' → %s", project.slug, cycle, label, h[:12])

            elif action == "sync":
                await vm.trigger_sync(vol)
                logger.info("  [%s] cycle %d: sync triggered", project.slug, cycle)
                await asyncio.sleep(2)  # let sync upload

        except Exception as e:
            logger.warning("  [%s] cycle %d: %s failed — %s", project.slug, cycle, action, e)

        await asyncio.sleep(0.5)

    # Final sync + snapshot to ensure CAS data exists
    try:
        await vm.trigger_sync(vol)
        await asyncio.sleep(3)
        h = await vm.create_snapshot(vol, label="Latest state")
        snapshot_hashes.append(h)
        logger.info("  [%s] final snapshot → %s", project.slug, h[:12])
    except Exception as e:
        logger.warning("  [%s] final snapshot failed: %s", project.slug, e)

    return {"files": len(written_files), "snapshots": len(snapshot_hashes)}


async def create_extra_project(db, user, vm, name, slug):
    """Create an additional project with files and snapshots."""
    existing = (await db.execute(select(Project).where(Project.slug == slug))).scalar_one_or_none()
    if existing:
        return existing

    vol_id, node = await vm.create_volume()
    p = Project(
        id=uuid4(), name=name, slug=slug, owner_id=user.id,
        volume_id=vol_id, cache_node=node,
        environment_status="stopped", compute_tier="environment",
    )
    db.add(p)
    c = Container(
        id=uuid4(), project_id=p.id, name="frontend",
        container_name=f"{slug}-frontend", internal_port=3000,
        startup_command="npm run dev", directory="/app",
    )
    db.add(c)
    await db.commit()
    await db.refresh(p)
    logger.info("Created project %s (vol=%s, node=%s)", slug, vol_id, node)
    return p


async def main():
    from app.services.volume_manager import get_volume_manager

    logger.info("=== Simulating User Activity ===")
    vm = get_volume_manager()

    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == "test@tesslate.dev"))).scalar_one_or_none()
        if not user:
            logger.error("Test user not found. Run seed_test_scenarios.py first.")
            return

        # Get existing projects
        result = await db.execute(select(Project).where(Project.owner_id == user.id))
        projects = list(result.scalars().all())
        logger.info("Found %d existing projects for %s", len(projects), user.email)

        # Create a couple more projects if we don't have enough
        if len(projects) < 4:
            for name, slug in [("Blog App", "blog-app"), ("API Server", "api-server"), ("Landing Page", "landing-page")]:
                try:
                    p = await create_extra_project(db, user, vm, name, slug)
                    if p not in projects:
                        projects.append(p)
                except Exception as e:
                    logger.warning("Failed to create %s: %s", slug, e)

        # Run activity on each project
        total_files = 0
        total_snapshots = 0
        for project in projects:
            logger.info("--- %s (%s) ---", project.name, project.slug)
            try:
                stats = await simulate_project_activity(db, vm, project, cycles=random.randint(6, 12))
                if stats:
                    total_files += stats["files"]
                    total_snapshots += stats["snapshots"]
            except Exception as e:
                logger.error("  %s failed: %s", project.slug, e)

        logger.info("")
        logger.info("=== Activity Simulation Complete ===")
        logger.info("  Projects: %d", len(projects))
        logger.info("  Total files written: %d", total_files)
        logger.info("  Total snapshots: %d", total_snapshots)
        logger.info("")
        logger.info("Open the Timeline panel in the UI to see snapshots and test restore.")


if __name__ == "__main__":
    asyncio.run(main())
