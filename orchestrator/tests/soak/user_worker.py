"""
Simulated user — owns projects and performs randomized actions each cycle.

Each UserWorker maintains a pool of long-lived projects and randomly
picks an action to perform each cycle: file I/O, env start/stop,
migrate, snapshot/restore, fork, or project churn (retire old + create new).
"""

from __future__ import annotations

import contextlib
import logging
import random
import time
import traceback

from .helpers import (
    create_project,
    delete_project,
    ensure_user,
    get_db,
    rand_str,
    start_env,
    stop_env,
    verify_test_files,
    wait_pods_running,
    write_test_files,
)
from .metrics import Metrics

logger = logging.getLogger("soak.user")


class ManagedProject:
    """A project owned by a simulated user, with tracked file state."""

    __slots__ = ("project", "container", "file_hashes", "env_running", "cycle_count")

    def __init__(self, project, container):
        self.project = project
        self.container = container
        self.file_hashes: dict[str, str] = {}
        self.env_running = False
        self.cycle_count = 0


class UserWorker:
    """Simulated user that runs continuous cycles of random actions."""

    def __init__(
        self,
        user_index: int,
        target_projects: int,
        worker_nodes: list[str],
        metrics: Metrics,
    ):
        self.index = user_index
        self.name = f"user-{user_index}"
        self.target_projects = target_projects
        self.worker_nodes = worker_nodes
        self.metrics = metrics
        self.db = None
        self.user = None
        self.projects: list[ManagedProject] = []

    # ── Lifecycle ────────────────────────────────────────────────

    async def setup(self):
        """Bootstrap DB session, user, and initial project pool."""
        self.db = await get_db()
        self.user = await ensure_user(self.db, self.index)
        logger.info("[%s] Bootstrapping %d projects...", self.name, self.target_projects)

        for _ in range(self.target_projects):
            try:
                mp = await self._create_managed_project()
                self.projects.append(mp)
            except Exception as e:
                logger.warning("[%s] Failed to create initial project: %s", self.name, e)

        self._update_gauges()
        logger.info("[%s] Ready with %d projects", self.name, len(self.projects))

    async def teardown(self):
        """Clean up all projects and close DB."""
        for mp in list(self.projects):
            with contextlib.suppress(Exception):
                await delete_project(self.db, mp.project)
        self.projects.clear()
        if self.db:
            await self.db.close()
            self.db = None
        self._update_gauges()

    # ── Main loop ────────────────────────────────────────────────

    async def run_cycle(self, cycle: int):
        """Pick a random action and execute it."""
        if not self.projects:
            # Re-create if we lost everything
            try:
                mp = await self._create_managed_project()
                self.projects.append(mp)
            except Exception:
                return

        action = self._pick_action()
        action_name = action.__name__

        t0 = time.monotonic()
        try:
            await action()
            dur = time.monotonic() - t0
            logger.info("[%s] cycle %d: %s OK (%.1fs)", self.name, cycle, action_name, dur)
        except Exception as e:
            dur = time.monotonic() - t0
            self.metrics.record(self.name, action_name, False, dur, str(e)[:120])
            logger.warning(
                "[%s] cycle %d: %s FAIL (%.1fs): %s", self.name, cycle, action_name, dur, e
            )
            traceback.print_exc()

        self._update_gauges()

    # ── Actions ──────────────────────────────────────────────────

    async def _action_write_and_verify(self):
        """Write new files to a random project and verify them."""
        mp = random.choice(self.projects)
        t0 = time.monotonic()
        hashes = await write_test_files(mp.project.volume_id, n=random.randint(3, 8))
        self.metrics.record(self.name, "write_files", True, time.monotonic() - t0)

        mp.file_hashes.update(hashes)

        t0 = time.monotonic()
        bad = await verify_test_files(mp.project.volume_id, mp.file_hashes)
        ok = len(bad) == 0
        self.metrics.record(
            self.name, "verify_files", ok, time.monotonic() - t0, f"bad={bad}" if bad else ""
        )

    async def _action_start_stop(self):
        """Start an env, verify files, stop it, verify again."""
        mp = random.choice(self.projects)

        if mp.env_running:
            # Stop first
            t0 = time.monotonic()
            await stop_env(mp.project, self.db)
            await self.db.refresh(mp.project)
            mp.env_running = False
            self.metrics.record(self.name, "stop_env", True, time.monotonic() - t0)
        else:
            # Start
            t0 = time.monotonic()
            await start_env(mp.project, mp.container, self.user.id, self.db)
            await self.db.refresh(mp.project)
            ok = await wait_pods_running(mp.project.id)
            mp.env_running = ok
            self.metrics.record(
                self.name, "start_env", ok, time.monotonic() - t0, "" if ok else "pods not running"
            )

        # Verify files regardless
        if mp.file_hashes:
            t0 = time.monotonic()
            bad = await verify_test_files(mp.project.volume_id, mp.file_hashes)
            ok = len(bad) == 0
            self.metrics.record(
                self.name,
                "verify_after_toggle",
                ok,
                time.monotonic() - t0,
                f"bad={bad}" if bad else "",
            )

    async def _action_migrate(self):
        """Sync + migrate a project to another node, verify files."""
        mp = random.choice(self.projects)
        from app.services.volume_manager import get_volume_manager

        vm = get_volume_manager()

        current = mp.project.cache_node
        targets = [n for n in self.worker_nodes if n != current]
        if not targets:
            return

        t0 = time.monotonic()
        await vm.trigger_sync(mp.project.volume_id)
        new_node = await vm.ensure_cached(mp.project.volume_id, candidate_nodes=targets)
        mp.project.cache_node = new_node
        await self.db.commit()
        self.metrics.record(self.name, "migrate", True, time.monotonic() - t0)

        if mp.file_hashes:
            t0 = time.monotonic()
            bad = await verify_test_files(mp.project.volume_id, mp.file_hashes)
            ok = len(bad) == 0
            self.metrics.record(
                self.name,
                "verify_after_migrate",
                ok,
                time.monotonic() - t0,
                f"bad={bad}" if bad else "",
            )

    async def _action_snapshot_restore(self):
        """Snapshot, corrupt files, restore, verify originals."""
        mp = random.choice(self.projects)
        if not mp.file_hashes:
            await self._action_write_and_verify()
            return

        from app.config import get_settings
        from app.services.hub_client import HubClient

        hub = HubClient(get_settings().volume_hub_address)

        try:
            t0 = time.monotonic()
            await hub.trigger_sync(mp.project.volume_id, timeout=120)
            snap = await hub.create_snapshot(
                mp.project.volume_id, f"soak-{rand_str()}", timeout=120
            )
            self.metrics.record(self.name, "snapshot", True, time.monotonic() - t0)

            # Write a canary file (NOT a tracked file) to verify restore reverts it
            from app.services.volume_manager import get_volume_manager

            client = await get_volume_manager().get_fileops_client(mp.project.volume_id)
            try:
                await client.write_file_text(
                    mp.project.volume_id, ".soak_canary", "SHOULD_BE_GONE\n"
                )
            finally:
                await client.close()

            # Restore
            t0 = time.monotonic()
            await hub._call(
                "RestoreToSnapshot",
                {"volume_id": mp.project.volume_id, "target_hash": snap},
                timeout=180,
            )
            self.metrics.record(self.name, "restore", True, time.monotonic() - t0)

            # Verify
            t0 = time.monotonic()
            bad = await verify_test_files(mp.project.volume_id, mp.file_hashes)
            ok = len(bad) == 0
            self.metrics.record(
                self.name,
                "verify_after_restore",
                ok,
                time.monotonic() - t0,
                f"bad={bad}" if bad else "",
            )
        finally:
            await hub.close()

    async def _action_double_restore(self):
        """Snapshot A, write, snapshot B, restore to A, write, restore to B, verify.

        Exercises the DAG branching model: after restoring to A and making
        changes, snapshot B must still be reachable (not truncated).
        """
        mp = random.choice(self.projects)
        if not mp.file_hashes:
            await self._action_write_and_verify()
            return

        from app.config import get_settings
        from app.services.hub_client import HubClient

        hub = HubClient(get_settings().volume_hub_address)

        try:
            # Snapshot A (captures current state with all tracked files).
            await hub.trigger_sync(mp.project.volume_id, timeout=120)
            snap_a = await hub.create_snapshot(
                mp.project.volume_id, f"branch-a-{rand_str()}", timeout=120
            )

            # Write new files, creating divergent state.
            hashes_b = await write_test_files(mp.project.volume_id, n=3)

            # Snapshot B (captures state with new files).
            await hub.trigger_sync(mp.project.volume_id, timeout=120)
            snap_b = await hub.create_snapshot(
                mp.project.volume_id, f"branch-b-{rand_str()}", timeout=120
            )

            # Restore to A — this forks the timeline. B must remain reachable.
            t0 = time.monotonic()
            await hub._call(
                "RestoreToSnapshot",
                {"volume_id": mp.project.volume_id, "target_hash": snap_a},
                timeout=180,
            )
            self.metrics.record(self.name, "restore", True, time.monotonic() - t0)

            # Verify original files are back (snapshot A state).
            bad = await verify_test_files(mp.project.volume_id, mp.file_hashes)
            ok_a = len(bad) == 0
            self.metrics.record(
                self.name, "verify_after_restore", ok_a, 0, f"bad={bad}" if bad else ""
            )

            # Now restore to B — the key test: B was NOT truncated.
            t0 = time.monotonic()
            await hub._call(
                "RestoreToSnapshot",
                {"volume_id": mp.project.volume_id, "target_hash": snap_b},
                timeout=180,
            )
            self.metrics.record(self.name, "restore", True, time.monotonic() - t0)

            # Verify B's files exist (includes both original + new files).
            combined = {**mp.file_hashes, **hashes_b}
            bad = await verify_test_files(mp.project.volume_id, combined)
            ok_b = len(bad) == 0
            self.metrics.record(
                self.name, "verify_after_restore", ok_b, 0, f"bad={bad}" if bad else ""
            )

            # Update tracked hashes to B's state (since we're now at B).
            mp.file_hashes.update(hashes_b)

        finally:
            await hub.close()

    async def _action_fork(self):
        """Fork a project's volume, verify the clone has the same files."""
        mp = random.choice(self.projects)
        if not mp.file_hashes:
            return

        from app.config import get_settings
        from app.services.hub_client import HubClient

        hub = HubClient(get_settings().volume_hub_address)

        try:
            t0 = time.monotonic()
            fork_id, _ = await hub.fork_volume(mp.project.volume_id, timeout=120)
            self.metrics.record(self.name, "fork", True, time.monotonic() - t0)

            # Verify files on the fork
            t0 = time.monotonic()
            bad = await verify_test_files(fork_id, mp.file_hashes)
            ok = len(bad) == 0
            self.metrics.record(
                self.name, "verify_fork", ok, time.monotonic() - t0, f"bad={bad}" if bad else ""
            )

            # Cleanup fork
            await hub.delete_volume(fork_id, timeout=60)
        finally:
            await hub.close()

    async def _action_churn_project(self):
        """Retire a random project, create a fresh one."""
        if len(self.projects) >= self.target_projects:
            victim = random.choice(self.projects)
            self.projects.remove(victim)
            t0 = time.monotonic()
            await delete_project(self.db, victim.project)
            self.metrics.record(self.name, "retire_project", True, time.monotonic() - t0)

        t0 = time.monotonic()
        mp = await self._create_managed_project()
        self.projects.append(mp)
        self.metrics.record(self.name, "create_project", True, time.monotonic() - t0)

    async def _action_full_lifecycle(self):
        """Create ephemeral project -> write -> start -> verify -> stop -> delete."""
        t0_all = time.monotonic()
        project, container = await create_project(self.db, self.user, f"life-{self.index}")
        try:
            hashes = await write_test_files(project.volume_id, n=random.randint(3, 6))

            await start_env(project, container, self.user.id, self.db)
            await self.db.refresh(project)
            await wait_pods_running(project.id, timeout=90)

            bad = await verify_test_files(project.volume_id, hashes)
            if bad:
                self.metrics.record(
                    self.name, "full_lifecycle", False, time.monotonic() - t0_all, f"bad={bad}"
                )
                return

            await stop_env(project, self.db)
            await self.db.refresh(project)

            bad = await verify_test_files(project.volume_id, hashes)
            ok = len(bad) == 0
            self.metrics.record(
                self.name,
                "full_lifecycle",
                ok,
                time.monotonic() - t0_all,
                f"bad={bad}" if bad else "",
            )
        finally:
            await delete_project(self.db, project)

    # ── Internals ────────────────────────────────────────────────

    async def _create_managed_project(self) -> ManagedProject:
        project, container = await create_project(self.db, self.user, f"s{self.index}")
        mp = ManagedProject(project, container)
        # Write initial files
        mp.file_hashes = await write_test_files(project.volume_id, n=5)
        return mp

    def _pick_action(self):
        """Weighted random action selection."""
        actions = [
            (self._action_write_and_verify, 25),
            (self._action_start_stop, 20),
            (self._action_migrate, 15),
            (self._action_snapshot_restore, 10),
            (self._action_fork, 10),
            (self._action_full_lifecycle, 10),
            (self._action_churn_project, 5),
            (self._action_double_restore, 5),
        ]
        total = sum(w for _, w in actions)
        r = random.randint(1, total)
        cum = 0
        for action, weight in actions:
            cum += weight
            if r <= cum:
                return action
        return actions[0][0]

    def _update_gauges(self):
        total_projects = len(self.projects)
        running_envs = sum(1 for mp in self.projects if mp.env_running)
        self.metrics.set_gauges(total_projects, running_envs)
