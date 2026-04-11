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

from .event_log import EventLog
from .helpers import (
    create_project,
    delete_project,
    ensure_user,
    get_db,
    get_last_verify_detail,
    rand_str,
    resolve_volume_node,
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
        event_log: EventLog,
    ):
        self.index = user_index
        self.name = f"user-{user_index}"
        self.target_projects = target_projects
        self.worker_nodes = worker_nodes
        self.metrics = metrics
        self.events = event_log
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

    # ── Logging helpers ─────────────────────────────────────────

    def _log_verify(
        self,
        mp: ManagedProject,
        action: str,
        step: str,
        bad: list[str],
        duration: float,
    ):
        """Log a verify result with full detail from get_last_verify_detail()."""
        ok = len(bad) == 0
        detail = get_last_verify_detail()
        self.events.log(
            self.name,
            action,
            step,
            mp.project.volume_id,
            success=ok,
            node=detail.node_resolved if detail else "",
            duration_s=duration,
            verify_detail=detail,
        )
        self.metrics.record(self.name, step, ok, duration, f"bad={bad}" if bad else "")

    # ── Actions ──────────────────────────────────────────────────

    async def _action_write_and_verify(self):
        """Write new files to a random project and verify them."""
        mp = random.choice(self.projects)
        vol = mp.project.volume_id

        # Log pre-state
        self.events.log(
            self.name,
            "write_and_verify",
            "begin",
            vol,
            file_hashes_before=dict(mp.file_hashes),
        )

        # Write
        t0 = time.monotonic()
        n = random.randint(3, 8)
        hashes, write_node = await write_test_files(vol, n=n)
        dur = time.monotonic() - t0
        self.metrics.record(self.name, "write_files", True, dur)
        self.events.log(
            self.name,
            "write_and_verify",
            "write",
            vol,
            node=write_node,
            duration_s=dur,
            files_written=hashes,
        )

        # Replace file_hashes entirely — only track what we just wrote.
        mp.file_hashes = hashes
        self.events.log(
            self.name,
            "write_and_verify",
            "set_hashes",
            vol,
            file_hashes_after=dict(mp.file_hashes),
        )

        # Verify
        t0 = time.monotonic()
        bad = await verify_test_files(vol, mp.file_hashes)
        dur = time.monotonic() - t0
        self._log_verify(mp, "write_and_verify", "verify_files", bad, dur)

    async def _action_start_stop(self):
        """Start an env, verify files, stop it, verify again."""
        mp = random.choice(self.projects)
        vol = mp.project.volume_id

        self.events.log(
            self.name,
            "start_stop",
            "begin",
            vol,
            file_hashes_before=dict(mp.file_hashes),
            detail=f"env_running={mp.env_running}",
        )

        if mp.env_running:
            # Stop first
            t0 = time.monotonic()
            await stop_env(mp.project, self.db)
            await self.db.refresh(mp.project)
            mp.env_running = False
            dur = time.monotonic() - t0
            self.metrics.record(self.name, "stop_env", True, dur)
            self.events.log(
                self.name,
                "start_stop",
                "stop_env",
                vol,
                duration_s=dur,
            )
        else:
            # Start
            t0 = time.monotonic()
            await start_env(mp.project, mp.container, self.user.id, self.db)
            await self.db.refresh(mp.project)
            ok = await wait_pods_running(mp.project.id)
            mp.env_running = ok
            dur = time.monotonic() - t0
            self.metrics.record(self.name, "start_env", ok, dur, "" if ok else "pods not running")
            self.events.log(
                self.name,
                "start_stop",
                "start_env",
                vol,
                success=ok,
                duration_s=dur,
                error="" if ok else "pods not running",
            )

        # Verify files regardless
        if mp.file_hashes:
            t0 = time.monotonic()
            bad = await verify_test_files(vol, mp.file_hashes)
            dur = time.monotonic() - t0
            self._log_verify(mp, "start_stop", "verify_after_toggle", bad, dur)

    async def _action_migrate(self):
        """Sync + migrate a project to another node, verify files."""
        mp = random.choice(self.projects)
        vol = mp.project.volume_id
        from app.services.volume_manager import get_volume_manager

        vm = get_volume_manager()

        current = mp.project.cache_node
        targets = [n for n in self.worker_nodes if n != current]
        if not targets:
            return

        self.events.log(
            self.name,
            "migrate",
            "begin",
            vol,
            file_hashes_before=dict(mp.file_hashes),
            source_node=current,
            detail=f"targets={targets}",
        )

        # Sync
        t0_sync = time.monotonic()
        await vm.trigger_sync(vol)
        dur_sync = time.monotonic() - t0_sync
        self.events.log(
            self.name,
            "migrate",
            "trigger_sync",
            vol,
            source_node=current,
            duration_s=dur_sync,
        )

        # EnsureCached on target
        t0 = time.monotonic()
        new_node = await vm.ensure_cached(vol, candidate_nodes=targets)
        dur = time.monotonic() - t0
        mp.project.cache_node = new_node
        await self.db.commit()
        self.metrics.record(self.name, "migrate", True, dur_sync + dur)
        self.events.log(
            self.name,
            "migrate",
            "ensure_cached",
            vol,
            source_node=current,
            target_node=new_node,
            duration_s=dur,
        )

        if mp.file_hashes:
            t0 = time.monotonic()
            bad = await verify_test_files(vol, mp.file_hashes)
            dur = time.monotonic() - t0
            self._log_verify(mp, "migrate", "verify_after_migrate", bad, dur)

    async def _action_snapshot_restore(self):
        """Snapshot, write canary, restore, verify originals."""
        mp = random.choice(self.projects)
        vol = mp.project.volume_id
        if not mp.file_hashes:
            await self._action_write_and_verify()
            return

        from app.config import get_settings
        from app.services.hub_client import HubClient

        hub = HubClient(get_settings().volume_hub_address)

        # Clear hashes upfront — the action modifies the volume (canary write,
        # restore). If anything fails mid-action, the volume state is unknown.
        # Setting to empty makes future verifies skip safely. On success we
        # restore hashes to the snapshot-time state.
        saved_hashes = dict(mp.file_hashes)
        mp.file_hashes = {}

        try:
            snapshot_hashes = saved_hashes
            node = await resolve_volume_node(vol)

            self.events.log(
                self.name,
                "snapshot_restore",
                "begin",
                vol,
                node=node,
                file_hashes_before=dict(mp.file_hashes),
            )

            # Sync + Snapshot
            t0 = time.monotonic()
            await hub.trigger_sync(vol, timeout=120)
            snap = await hub.create_snapshot(vol, f"soak-{rand_str()}", timeout=120)
            dur = time.monotonic() - t0
            self.metrics.record(self.name, "snapshot", True, dur)
            self.events.log(
                self.name,
                "snapshot_restore",
                "snapshot",
                vol,
                node=node,
                duration_s=dur,
                snapshot_hash=snap,
                detail=f"frozen_hashes={list(snapshot_hashes.keys())}",
            )

            # Write canary
            from app.services.volume_manager import get_volume_manager

            client = await get_volume_manager().get_fileops_client(vol)
            try:
                await client.write_file_text(vol, ".soak_canary", "SHOULD_BE_GONE\n")
            finally:
                await client.close()
            self.events.log(
                self.name,
                "snapshot_restore",
                "write_canary",
                vol,
                node=node,
            )

            # Restore
            t0 = time.monotonic()
            await hub._call(
                "RestoreToSnapshot",
                {"volume_id": vol, "target_hash": snap},
                timeout=180,
            )
            dur = time.monotonic() - t0
            self.metrics.record(self.name, "restore", True, dur)

            # Check which node after restore (could change)
            node_after = await resolve_volume_node(vol)
            self.events.log(
                self.name,
                "snapshot_restore",
                "restore",
                vol,
                node=node_after,
                duration_s=dur,
                restore_target=snap,
                detail=f"node_before={node} node_after={node_after}",
            )

            # Reset file_hashes to snapshot state
            mp.file_hashes = snapshot_hashes
            self.events.log(
                self.name,
                "snapshot_restore",
                "set_hashes",
                vol,
                file_hashes_after=dict(mp.file_hashes),
            )

            # Verify
            t0 = time.monotonic()
            bad = await verify_test_files(vol, snapshot_hashes)
            dur = time.monotonic() - t0
            self._log_verify(mp, "snapshot_restore", "verify_after_restore", bad, dur)

        finally:
            await hub.close()

    async def _action_double_restore(self):
        """Snapshot A, write, snapshot B, restore to A, restore to B, verify.

        Exercises the DAG branching model: after restoring to A and making
        changes, snapshot B must still be reachable (not truncated).
        """
        mp = random.choice(self.projects)
        vol = mp.project.volume_id
        if not mp.file_hashes:
            await self._action_write_and_verify()
            return

        from app.config import get_settings
        from app.services.hub_client import HubClient

        hub = HubClient(get_settings().volume_hub_address)

        # Clear hashes upfront — the action writes divergent files and restores
        # between two snapshots. If anything fails mid-action, volume state is
        # unknown. Empty hashes = future verifies skip safely. On success we
        # set hashes to the final snapshot B state.
        saved_hashes = dict(mp.file_hashes)
        mp.file_hashes = {}

        try:
            hashes_a = saved_hashes
            node = await resolve_volume_node(vol)

            self.events.log(
                self.name,
                "double_restore",
                "begin",
                vol,
                node=node,
                file_hashes_before=dict(mp.file_hashes),
            )

            # Snapshot A
            await hub.trigger_sync(vol, timeout=120)
            snap_a = await hub.create_snapshot(vol, f"branch-a-{rand_str()}", timeout=120)
            self.events.log(
                self.name,
                "double_restore",
                "snapshot_a",
                vol,
                node=node,
                snapshot_hash=snap_a,
                detail=f"hashes_a={list(hashes_a.keys())}",
            )

            # Write new files (divergent state)
            hashes_b_new, write_node = await write_test_files(vol, n=3)
            self.events.log(
                self.name,
                "double_restore",
                "write_divergent",
                vol,
                node=write_node,
                files_written=hashes_b_new,
            )

            # Snapshot B
            hashes_b = {**hashes_a, **hashes_b_new}
            await hub.trigger_sync(vol, timeout=120)
            snap_b = await hub.create_snapshot(vol, f"branch-b-{rand_str()}", timeout=120)
            self.events.log(
                self.name,
                "double_restore",
                "snapshot_b",
                vol,
                node=node,
                snapshot_hash=snap_b,
                detail=f"hashes_b={list(hashes_b.keys())}",
            )

            # Restore to A
            t0 = time.monotonic()
            await hub._call(
                "RestoreToSnapshot",
                {"volume_id": vol, "target_hash": snap_a},
                timeout=180,
            )
            dur = time.monotonic() - t0
            self.metrics.record(self.name, "restore", True, dur)
            node_after_a = await resolve_volume_node(vol)
            self.events.log(
                self.name,
                "double_restore",
                "restore_to_a",
                vol,
                node=node_after_a,
                duration_s=dur,
                restore_target=snap_a,
            )

            # Verify A
            bad = await verify_test_files(vol, hashes_a)
            ok_a = len(bad) == 0
            detail_a = get_last_verify_detail()
            self.events.log(
                self.name,
                "double_restore",
                "verify_after_restore_a",
                vol,
                success=ok_a,
                node=detail_a.node_resolved if detail_a else "",
                verify_detail=detail_a,
            )
            self.metrics.record(
                self.name, "verify_after_restore", ok_a, 0, f"bad={bad}" if bad else ""
            )

            # Restore to B
            t0 = time.monotonic()
            await hub._call(
                "RestoreToSnapshot",
                {"volume_id": vol, "target_hash": snap_b},
                timeout=180,
            )
            dur = time.monotonic() - t0
            self.metrics.record(self.name, "restore", True, dur)
            node_after_b = await resolve_volume_node(vol)
            self.events.log(
                self.name,
                "double_restore",
                "restore_to_b",
                vol,
                node=node_after_b,
                duration_s=dur,
                restore_target=snap_b,
            )

            # Verify B
            bad = await verify_test_files(vol, hashes_b)
            ok_b = len(bad) == 0
            detail_b = get_last_verify_detail()
            self.events.log(
                self.name,
                "double_restore",
                "verify_after_restore_b",
                vol,
                success=ok_b,
                node=detail_b.node_resolved if detail_b else "",
                verify_detail=detail_b,
            )
            self.metrics.record(
                self.name, "verify_after_restore", ok_b, 0, f"bad={bad}" if bad else ""
            )

            # Final state
            mp.file_hashes = hashes_b
            self.events.log(
                self.name,
                "double_restore",
                "set_hashes",
                vol,
                file_hashes_after=dict(mp.file_hashes),
            )

        finally:
            await hub.close()

    async def _action_fork(self):
        """Fork a project's volume, verify the clone has the same files."""
        mp = random.choice(self.projects)
        vol = mp.project.volume_id
        if not mp.file_hashes:
            return

        from app.config import get_settings
        from app.services.hub_client import HubClient

        hub = HubClient(get_settings().volume_hub_address)

        try:
            self.events.log(
                self.name,
                "fork",
                "begin",
                vol,
                file_hashes_before=dict(mp.file_hashes),
            )

            t0 = time.monotonic()
            fork_id, _ = await hub.fork_volume(vol, timeout=120)
            dur = time.monotonic() - t0
            self.metrics.record(self.name, "fork", True, dur)
            fork_node = await resolve_volume_node(fork_id)
            self.events.log(
                self.name,
                "fork",
                "fork_created",
                vol,
                duration_s=dur,
                target_node=fork_node,
                detail=f"fork_id={fork_id}",
            )

            # Verify files on the fork
            t0 = time.monotonic()
            bad = await verify_test_files(fork_id, mp.file_hashes)
            dur = time.monotonic() - t0
            ok = len(bad) == 0
            detail = get_last_verify_detail()
            self.events.log(
                self.name,
                "fork",
                "verify_fork",
                fork_id,
                success=ok,
                node=detail.node_resolved if detail else "",
                duration_s=dur,
                verify_detail=detail,
                detail=f"source_vol={vol}",
            )
            self.metrics.record(self.name, "verify_fork", ok, dur, f"bad={bad}" if bad else "")

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
            dur = time.monotonic() - t0
            self.metrics.record(self.name, "retire_project", True, dur)
            self.events.log(
                self.name,
                "churn",
                "retire",
                victim.project.volume_id,
                duration_s=dur,
            )

        t0 = time.monotonic()
        mp = await self._create_managed_project()
        self.projects.append(mp)
        dur = time.monotonic() - t0
        self.metrics.record(self.name, "create_project", True, dur)
        self.events.log(
            self.name,
            "churn",
            "create",
            mp.project.volume_id,
            duration_s=dur,
            node=mp.project.cache_node or "",
            files_written=dict(mp.file_hashes),
        )

    async def _action_full_lifecycle(self):
        """Create ephemeral project -> write -> start -> verify -> stop -> delete."""
        t0_all = time.monotonic()
        project, container = await create_project(self.db, self.user, f"life-{self.index}")
        vol = project.volume_id
        try:
            self.events.log(
                self.name,
                "full_lifecycle",
                "create",
                vol,
                node=project.cache_node or "",
            )

            hashes, write_node = await write_test_files(vol, n=random.randint(3, 6))
            self.events.log(
                self.name,
                "full_lifecycle",
                "write",
                vol,
                node=write_node,
                files_written=hashes,
            )

            await start_env(project, container, self.user.id, self.db)
            await self.db.refresh(project)
            await wait_pods_running(project.id, timeout=90)
            self.events.log(
                self.name,
                "full_lifecycle",
                "start_env",
                vol,
            )

            bad = await verify_test_files(vol, hashes)
            dur_v1 = time.monotonic() - t0_all
            if bad:
                detail = get_last_verify_detail()
                self.events.log(
                    self.name,
                    "full_lifecycle",
                    "verify_running",
                    vol,
                    success=False,
                    duration_s=dur_v1,
                    verify_detail=detail,
                )
                self.metrics.record(self.name, "full_lifecycle", False, dur_v1, f"bad={bad}")
                return

            self.events.log(
                self.name,
                "full_lifecycle",
                "verify_running",
                vol,
                success=True,
            )

            await stop_env(project, self.db)
            await self.db.refresh(project)
            self.events.log(
                self.name,
                "full_lifecycle",
                "stop_env",
                vol,
            )

            bad = await verify_test_files(vol, hashes)
            dur_total = time.monotonic() - t0_all
            ok = len(bad) == 0
            detail = get_last_verify_detail()
            self.events.log(
                self.name,
                "full_lifecycle",
                "verify_stopped",
                vol,
                success=ok,
                duration_s=dur_total,
                verify_detail=detail,
            )
            self.metrics.record(
                self.name,
                "full_lifecycle",
                ok,
                dur_total,
                f"bad={bad}" if bad else "",
            )
        finally:
            await delete_project(self.db, project)

    # ── Internals ────────────────────────────────────────────────

    async def _create_managed_project(self) -> ManagedProject:
        project, container = await create_project(self.db, self.user, f"s{self.index}")
        mp = ManagedProject(project, container)
        # Write initial files
        hashes, _ = await write_test_files(project.volume_id, n=5)
        mp.file_hashes = hashes
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
