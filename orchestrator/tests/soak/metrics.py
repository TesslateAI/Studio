"""Shared metrics collector for the soak test."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from datetime import UTC, datetime


class Metrics:
    """Thread/task-safe metrics aggregator with periodic dashboard output."""

    def __init__(self):
        self._lock = threading.Lock()
        self.passed = 0
        self.failed = 0
        self.errors: list[tuple[str, str, str]] = []  # (user, op, detail)
        self.op_counts: dict[str, int] = defaultdict(int)
        self.op_times: dict[str, list[float]] = defaultdict(list)
        self.active_projects = 0
        self.active_envs = 0
        self.start_time = time.monotonic()

    def record(self, user: str, op: str, success: bool, duration: float, detail: str = ""):
        with self._lock:
            self.op_counts[op] += 1
            self.op_times[op].append(duration)
            if success:
                self.passed += 1
            else:
                self.failed += 1
                self.errors.append((user, op, detail[:120]))

    def set_gauges(self, projects: int, envs: int):
        with self._lock:
            self.active_projects = projects
            self.active_envs = envs

    def dashboard(self):
        with self._lock:
            elapsed = time.monotonic() - self.start_time
            total = self.passed + self.failed
            rate = total / max(elapsed, 1) * 60
            err_pct = self.failed / max(total, 1) * 100

            lines = [
                "",
                "=" * 72,
                f"  SOAK DASHBOARD — {datetime.now(UTC).strftime('%H:%M:%S UTC')}",
                "=" * 72,
                f"  Uptime: {elapsed / 3600:.1f}h | Ops: {total} | Rate: {rate:.0f}/min | "
                f"Fail: {self.failed} ({err_pct:.1f}%)",
                f"  Active: {self.active_projects} projects, {self.active_envs} environments",
                "",
            ]

            # Op table sorted by count
            sorted_ops = sorted(self.op_counts.items(), key=lambda x: -x[1])
            for op, count in sorted_ops:
                times = self.op_times[op]
                avg = sum(times) / len(times) if times else 0
                p95_idx = int(len(times) * 0.95)
                p95 = sorted(times)[p95_idx] if len(times) >= 2 else avg
                lines.append(f"  {op:32s} n={count:5d}  avg={avg:5.1f}s  p95={p95:5.1f}s")

            if self.errors:
                lines.append("")
                lines.append(f"  Last 5 errors (of {len(self.errors)}):")
                for user, op, detail in self.errors[-5:]:
                    lines.append(f"    [{user}:{op}] {detail}")

            lines.append("=" * 72)
            lines.append("")
            print("\n".join(lines), flush=True)
