"""
Multi-user soak test — long-running chaos simulation via the real SDK.

Spawns N simulated users, each managing a pool of long-lived projects.
Users perform randomized actions concurrently: write files, start/stop
environments, migrate volumes, snapshot/restore, fork projects. A
separate chaos agent periodically disrupts nodes (cordon/drain) and
restarts infrastructure (CSI, Hub).

Architecture:
  - Single runner process, asyncio concurrency
  - Each user = independent async worker with own DB session
  - Each user owns 2-4 projects that persist across cycles
  - Projects churn: old ones retire, new ones join
  - Shared metrics dashboard printed periodically

Usage (inside a backend pod or soak-test Job):
    python3 -u -m tests.soak.run                         # 4 hours, 6 users
    python3 -u -m tests.soak.run --hours 8 --users 10    # 8 hours, 10 users
    python3 -u -m tests.soak.run --cycles 100 --users 4  # 100 cycles per user
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import random
import sys
import time

from .chaos_agent import ChaosAgent
from .helpers import ensure_models, get_worker_nodes
from .metrics import Metrics
from .user_worker import UserWorker

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("soak")
logger.setLevel(logging.INFO)


async def run(
    num_users: int = 6,
    max_hours: float | None = None,
    max_cycles: int | None = None,
    projects_per_user: int = 3,
    chaos_interval: int = 600,
    chaos_enabled: bool = True,
):
    ensure_models()
    metrics = Metrics()
    workers_nodes = await get_worker_nodes()

    if len(workers_nodes) < 2:
        logger.error("Need >= 2 worker nodes, found %d. Aborting.", len(workers_nodes))
        return 1

    logger.info(
        "SOAK TEST — %d users, %d projects each, nodes=%s, hours=%s, cycles=%s, chaos=%s (interval=%ds)",
        num_users,
        projects_per_user,
        workers_nodes,
        max_hours or "unlimited",
        max_cycles or "unlimited",
        "ON" if chaos_enabled else "OFF",
        chaos_interval,
    )

    # Spawn user workers
    user_workers: list[UserWorker] = []
    for i in range(num_users):
        uw = UserWorker(
            user_index=i,
            target_projects=projects_per_user,
            worker_nodes=workers_nodes,
            metrics=metrics,
        )
        user_workers.append(uw)

    # Chaos agent (node disruptions, infra restarts)
    chaos = ChaosAgent(
        worker_nodes=workers_nodes,
        metrics=metrics,
        interval_seconds=chaos_interval,
        enabled=chaos_enabled,
    )

    # Dashboard printer
    async def dashboard_loop():
        while True:
            await asyncio.sleep(60)
            metrics.dashboard()

    # Deadline
    deadline = time.monotonic() + (max_hours * 3600) if max_hours else None

    async def user_loop(uw: UserWorker):
        await uw.setup()
        cycle = 0
        while True:
            cycle += 1
            if max_cycles and cycle > max_cycles:
                break
            if deadline and time.monotonic() > deadline:
                break
            await uw.run_cycle(cycle)
            await asyncio.sleep(random.uniform(0.5, 2.0))
        await uw.teardown()

    # Run everything concurrently
    tasks = [asyncio.create_task(user_loop(uw)) for uw in user_workers]
    tasks.append(asyncio.create_task(chaos.run(deadline=deadline, max_cycles=max_cycles)))
    tasks.append(asyncio.create_task(dashboard_loop()))

    try:
        # Wait for user workers to finish (dashboard and chaos run forever,
        # so we wait only for user tasks)
        user_tasks = tasks[:num_users]
        await asyncio.gather(*user_tasks)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Interrupted — shutting down")
    finally:
        # Cancel lingering tasks
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

        # Final teardown for any workers that didn't finish cleanly
        for uw in user_workers:
            with contextlib.suppress(Exception):
                await uw.teardown()

    metrics.dashboard()
    logger.info(
        "SOAK TEST COMPLETE — %d passed, %d failed",
        metrics.passed,
        metrics.failed,
    )
    return 0 if metrics.failed == 0 else 1


def main():
    parser = argparse.ArgumentParser(description="Multi-user soak test")
    parser.add_argument("--hours", type=float, default=4.0, help="Max hours (default: 4)")
    parser.add_argument("--cycles", type=int, default=None, help="Max cycles per user")
    parser.add_argument("--users", type=int, default=6, help="Simulated users (default: 6)")
    parser.add_argument("--projects", type=int, default=3, help="Projects per user (default: 3)")
    parser.add_argument(
        "--chaos-interval",
        type=int,
        default=600,
        help="Seconds between chaos events (default: 600)",
    )
    parser.add_argument("--no-chaos", action="store_true", help="Disable chaos agent entirely")
    args = parser.parse_args()

    sys.exit(
        asyncio.run(
            run(
                num_users=args.users,
                max_hours=args.hours,
                max_cycles=args.cycles,
                projects_per_user=args.projects,
                chaos_interval=args.chaos_interval,
                chaos_enabled=not args.no_chaos,
            )
        )
    )


if __name__ == "__main__":
    main()
