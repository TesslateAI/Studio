"""Shared helpers for soak test — DB bootstrap, node discovery, project CRUD."""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import random
import string
import time
import uuid

from .event_log import FileResult, VerifyDetail

logger = logging.getLogger("soak.helpers")

_models_loaded = False


def ensure_models():
    """Import all SQLAlchemy models so relationships resolve."""
    global _models_loaded
    if not _models_loaded:
        import app.models  # noqa: F401
        import app.models_auth  # noqa: F401

        _models_loaded = True


async def get_db():
    from app.database import AsyncSessionLocal

    return AsyncSessionLocal()


async def get_worker_nodes() -> list[str]:
    import kubernetes

    kubernetes.config.load_incluster_config()
    v1 = kubernetes.client.CoreV1Api()
    nodes = v1.list_node()
    workers = []
    for n in nodes.items:
        labels = n.metadata.labels or {}
        if "node-role.kubernetes.io/control-plane" in labels:
            continue
        for c in n.status.conditions or []:
            if c.type == "Ready" and c.status == "True":
                workers.append(n.metadata.name)
    return workers


def rand_str(n: int = 6) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# ── User bootstrap ──────────────────────────────────────────────────


async def ensure_user(db, index: int):
    """Get or create a soak test user by index."""
    from sqlalchemy import select

    from app.models_auth import User

    email = f"soak-user-{index}@tesslate.test"
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user:
        return user

    uid = uuid.uuid4()
    user = User(
        id=uid,
        email=email,
        hashed_password="soak-test-hash",
        name=f"Soak User {index}",
        username=f"soak-{index}-{uid.hex[:6]}",
        slug=f"soak-{index}-{uid.hex[:6]}",
        is_active=True,
        is_verified=True,
        is_superuser=False,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


# ── Project lifecycle ───────────────────────────────────────────────


async def create_project(db, user, prefix: str = "soak"):
    """Create a real project with a btrfs volume via the SDK."""
    from app.models import Container, Project
    from app.services.volume_manager import get_volume_manager
    from app.utils.slug_generator import generate_project_slug

    vm = get_volume_manager()
    volume_id, cache_node = await vm.create_volume()
    slug = generate_project_slug(f"{prefix}-{rand_str()}")

    project = Project(
        id=uuid.uuid4(),
        name=f"{prefix}-{rand_str(4)}",
        slug=slug,
        owner_id=user.id,
        volume_id=volume_id,
        cache_node=cache_node,
        environment_status="active",
        compute_tier="none",
    )
    db.add(project)

    container = Container(
        id=uuid.uuid4(),
        project_id=project.id,
        name="frontend",
        directory=".",
        container_name=f"dev-{slug}",
        port=3000,
        internal_port=3000,
        startup_command="echo 'soak dev server' && sleep infinity",
        container_type="base",
    )
    db.add(container)
    await db.commit()
    await db.refresh(project)
    return project, container


async def delete_project(db, project):
    """Full cleanup: stop env, delete volume, remove from DB."""
    from app.services.compute_manager import get_compute_manager
    from app.services.volume_manager import get_volume_manager

    with contextlib.suppress(Exception):
        await get_compute_manager().stop_environment(project, db)
    with contextlib.suppress(Exception):
        await get_volume_manager().delete_volume(project.volume_id)
    try:
        await db.delete(project)
        await db.commit()
    except Exception:
        await db.rollback()


# ── File I/O via FileOps ───────────────────────────────────────────


async def resolve_volume_node(volume_id: str) -> str:
    """Return the node name that the Hub resolves this volume to."""
    from app.services.volume_manager import get_volume_manager

    try:
        resp = await get_volume_manager().resolve_volume(volume_id)
        return resp.get("node_name", "unknown")
    except Exception:
        return "resolve_failed"


async def write_test_files(volume_id: str, n: int = 5) -> tuple[dict[str, str], str]:
    """Write n unique files to a volume.

    Returns (hashes, node) where hashes is {path: content_hash} and node
    is the node the writes were routed to.
    """
    from app.services.volume_manager import get_volume_manager

    vm = get_volume_manager()
    resp = await vm.resolve_volume(volume_id)
    node = resp.get("node_name", "unknown")
    client = await vm.get_fileops_client(volume_id)
    hashes: dict[str, str] = {}
    try:
        for i in range(n):
            marker = f"{volume_id}-{rand_str(8)}-{i}"
            path = f"src/mod_{i}.js" if i > 0 else "index.js"
            content = f"// {marker}\nexport const id = '{marker}';\n"
            parent = os.path.dirname(path)
            if parent:
                await client.mkdir_all(volume_id, parent)
            await client.write_file_text(volume_id, path, content)
            hashes[path] = content_hash(content)
    finally:
        await client.close()
    return hashes, node


async def verify_test_files(volume_id: str, expected: dict[str, str]) -> list[str]:
    """Read files back and return list of paths that don't match.

    Retries once after 3s on failure to tolerate transient Hub/gRPC
    disruptions during chaos events.
    """
    for attempt in range(2):
        detail = await _verify_once_detailed(volume_id, expected)
        if detail.bad_count == 0 or attempt == 1:
            # Stash detail on the function for caller to retrieve
            verify_test_files._last_detail = detail  # type: ignore[attr-defined]
            return detail.bad_paths
        await asyncio.sleep(3)
    verify_test_files._last_detail = detail  # type: ignore[attr-defined]
    return detail.bad_paths


def get_last_verify_detail() -> VerifyDetail | None:
    """Retrieve the VerifyDetail from the most recent verify_test_files call."""
    return getattr(verify_test_files, "_last_detail", None)


async def _verify_once_detailed(volume_id: str, expected: dict[str, str]) -> VerifyDetail:
    """Verify files and return rich per-file results."""
    from app.services.volume_manager import get_volume_manager

    vm = get_volume_manager()

    # Resolve which node we'll read from
    node = "unknown"
    try:
        resp = await vm.resolve_volume(volume_id)
        node = resp.get("node_name", "unknown")
    except Exception as e:
        return VerifyDetail(
            volume_id=volume_id,
            node_resolved="resolve_failed",
            connect_failed=True,
            connect_error=f"resolve: {type(e).__name__}: {e}",
            bad_count=len(expected),
            files=[
                FileResult(
                    path=p,
                    status="connect_error",
                    expected_hash=h,
                    error=f"resolve: {type(e).__name__}: {e}",
                )
                for p, h in expected.items()
            ],
        )

    try:
        client = await vm.get_fileops_client(volume_id)
    except Exception as e:
        err_msg = f"connect: {type(e).__name__}: {e}"
        return VerifyDetail(
            volume_id=volume_id,
            node_resolved=node,
            connect_failed=True,
            connect_error=err_msg,
            bad_count=len(expected),
            files=[
                FileResult(path=p, status="connect_error", expected_hash=h, error=err_msg)
                for p, h in expected.items()
            ],
        )

    results: list[FileResult] = []
    ok_count = 0
    bad_count = 0
    try:
        for path, exp_hash in expected.items():
            try:
                text = await client.read_file_text(volume_id, path)
                actual = content_hash(text)
                if actual == exp_hash:
                    results.append(
                        FileResult(
                            path=path,
                            status="ok",
                            expected_hash=exp_hash,
                            actual_hash=actual,
                        )
                    )
                    ok_count += 1
                else:
                    results.append(
                        FileResult(
                            path=path,
                            status="mismatch",
                            expected_hash=exp_hash,
                            actual_hash=actual,
                            actual_preview=text[:120],
                        )
                    )
                    bad_count += 1
            except Exception as e:
                results.append(
                    FileResult(
                        path=path,
                        status="read_error",
                        expected_hash=exp_hash,
                        error=f"{type(e).__name__}: {e}",
                    )
                )
                bad_count += 1
    finally:
        await client.close()

    return VerifyDetail(
        volume_id=volume_id,
        node_resolved=node,
        files=results,
        ok_count=ok_count,
        bad_count=bad_count,
    )


# ── Environment lifecycle ──────────────────────────────────────────


async def start_env(project, container, user_id, db) -> dict:
    from app.services.compute_manager import get_compute_manager

    return await get_compute_manager().start_environment(
        project,
        [container],
        [],
        user_id,
        db,
    )


async def stop_env(project, db):
    from app.services.compute_manager import get_compute_manager

    await get_compute_manager().stop_environment(project, db)


async def wait_pods_running(project_id, timeout: int = 90) -> bool:
    """Wait until all pods in a project namespace are Running (not waiting)."""
    import kubernetes

    kubernetes.config.load_incluster_config()
    v1 = kubernetes.client.CoreV1Api()
    ns = f"proj-{project_id}"
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        try:
            pods = v1.list_namespaced_pod(namespace=ns)
            if pods.items and all(
                p.status.phase in ("Running", "Succeeded")
                and not any(
                    cs.state and cs.state.waiting for cs in (p.status.container_statuses or [])
                )
                for p in pods.items
            ):
                return True
        except Exception:
            pass
        await asyncio.sleep(2)
    return False


# Needed for await inside wait_pods_running
import asyncio  # noqa: E402
