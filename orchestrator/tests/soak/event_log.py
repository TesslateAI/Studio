"""
Structured event log for soak test — captures every operation for failure replay.

Writes JSONL to /tmp/soak-events.jsonl and prints failure-related events to
stdout. At test end, generates a per-volume failure timeline so you can
1-1 replicate any error.

Each event is a dict with at minimum:
  ts, user, action, step, volume_id, success

Verify events additionally capture per-file detail:
  node_resolved, expected_hashes, file_results (per-file ok/mismatch/error)
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger("soak.events")

EVENTS_PATH = os.environ.get("SOAK_EVENTS_PATH", "/tmp/soak-events.jsonl")
REPORT_PATH = os.environ.get("SOAK_REPORT_PATH", "/tmp/soak-report.txt")


@dataclass
class FileResult:
    """Per-file verification result."""

    path: str
    status: str  # "ok", "mismatch", "read_error", "connect_error"
    expected_hash: str = ""
    actual_hash: str = ""
    actual_preview: str = ""  # first 120 chars of actual content
    error: str = ""


@dataclass
class VerifyDetail:
    """Rich verification result for a single verify_test_files call."""

    volume_id: str
    node_resolved: str  # which node the FileOps client connected to
    files: list[FileResult] = field(default_factory=list)
    bad_count: int = 0
    ok_count: int = 0
    connect_failed: bool = False
    connect_error: str = ""

    @property
    def bad_paths(self) -> list[str]:
        return [f.path for f in self.files if f.status != "ok"]


class EventLog:
    """Thread-safe JSONL event logger with per-volume indexing."""

    def __init__(self):
        self._lock = threading.Lock()
        self._events: list[dict] = []
        # Index: volume_id -> list of event indices for fast timeline lookup
        self._volume_index: dict[str, list[int]] = defaultdict(list)
        # Track which volumes had failures
        self._failed_volumes: set[str] = set()
        self._file = None
        try:
            self._file = Path(EVENTS_PATH).open("w", buffering=1)  # noqa: SIM115
        except OSError as e:
            logger.warning("Cannot open events file %s: %s", EVENTS_PATH, e)

    def log(
        self,
        user: str,
        action: str,
        step: str,
        volume_id: str,
        *,
        success: bool = True,
        node: str = "",
        duration_s: float = 0.0,
        file_hashes_before: dict[str, str] | None = None,
        file_hashes_after: dict[str, str] | None = None,
        files_written: dict[str, str] | None = None,
        verify_detail: VerifyDetail | None = None,
        snapshot_hash: str = "",
        restore_target: str = "",
        target_node: str = "",
        source_node: str = "",
        error: str = "",
        detail: str = "",
    ):
        """Log a single event. All fields optional except user/action/step/volume_id."""
        ts = datetime.now(UTC).isoformat()

        event = {
            "ts": ts,
            "t_mono": round(time.monotonic(), 3),
            "user": user,
            "action": action,
            "step": step,
            "volume_id": volume_id,
            "success": success,
        }

        # Only include non-empty optional fields to keep JSONL readable
        if node:
            event["node"] = node
        if duration_s:
            event["duration_s"] = round(duration_s, 3)
        if file_hashes_before is not None:
            event["file_hashes_before"] = file_hashes_before
        if file_hashes_after is not None:
            event["file_hashes_after"] = file_hashes_after
        if files_written is not None:
            event["files_written"] = files_written
        if verify_detail is not None:
            event["verify"] = {
                "node_resolved": verify_detail.node_resolved,
                "connect_failed": verify_detail.connect_failed,
                "connect_error": verify_detail.connect_error,
                "ok_count": verify_detail.ok_count,
                "bad_count": verify_detail.bad_count,
                "files": [asdict(f) for f in verify_detail.files],
            }
        if snapshot_hash:
            event["snapshot_hash"] = snapshot_hash
        if restore_target:
            event["restore_target"] = restore_target
        if target_node:
            event["target_node"] = target_node
        if source_node:
            event["source_node"] = source_node
        if error:
            event["error"] = error
        if detail:
            event["detail"] = detail

        with self._lock:
            idx = len(self._events)
            self._events.append(event)
            if volume_id:
                self._volume_index[volume_id].append(idx)
            if not success and volume_id:
                self._failed_volumes.add(volume_id)
            if self._file:
                with contextlib.suppress(OSError):
                    self._file.write(json.dumps(event) + "\n")

        # Print failures immediately to stdout for real-time visibility
        if not success:
            self._print_failure(event)

    def _print_failure(self, event: dict):
        """Print a human-readable failure summary to stdout."""
        parts = [
            f"\n{'!' * 60}",
            f"FAILURE: [{event['user']}] {event['action']}.{event['step']}",
            f"  volume: {event['volume_id']}",
        ]
        if event.get("node"):
            parts.append(f"  node: {event['node']}")
        if event.get("error"):
            parts.append(f"  error: {event['error']}")
        if "verify" in event:
            v = event["verify"]
            parts.append(
                f"  verify: {v['ok_count']} ok, {v['bad_count']} bad "
                f"(node={v['node_resolved']}, connect_failed={v['connect_failed']})"
            )
            for f in v["files"]:
                if f["status"] != "ok":
                    line = f"    {f['path']}: {f['status']}"
                    if f["expected_hash"]:
                        line += f" expected={f['expected_hash']}"
                    if f["actual_hash"]:
                        line += f" actual={f['actual_hash']}"
                    if f["error"]:
                        line += f" err={f['error']}"
                    if f["actual_preview"]:
                        line += f"\n      content: {f['actual_preview']}"
                    parts.append(line)
        parts.append(f"  ts: {event['ts']}")
        parts.append("!" * 60)
        print("\n".join(parts), flush=True)

    def get_volume_timeline(self, volume_id: str) -> list[dict]:
        """Return all events for a volume in chronological order."""
        with self._lock:
            indices = self._volume_index.get(volume_id, [])
            return [self._events[i] for i in indices]

    def generate_failure_report(self) -> str:
        """Generate a comprehensive report for all volumes that had failures."""
        with self._lock:
            failed_vols = sorted(self._failed_volumes)
            if not failed_vols:
                return "NO FAILURES — all verifications passed.\n"

            lines = [
                "=" * 80,
                "  SOAK TEST FAILURE REPORT",
                f"  Generated: {datetime.now(UTC).isoformat()}",
                f"  Total events: {len(self._events)}",
                f"  Volumes with failures: {len(failed_vols)}",
                "=" * 80,
                "",
            ]

            for vol_id in failed_vols:
                indices = self._volume_index.get(vol_id, [])
                events = [self._events[i] for i in indices]
                failure_events = [e for e in events if not e["success"]]

                lines.append(f"{'─' * 80}")
                lines.append(f"VOLUME: {vol_id}")
                lines.append(f"  Total ops: {len(events)}, Failures: {len(failure_events)}")
                lines.append("")

                # Print FULL timeline for this volume
                lines.append("  TIMELINE:")
                for e in events:
                    marker = "✗" if not e["success"] else "✓"
                    dur = f" ({e['duration_s']:.1f}s)" if e.get("duration_s") else ""
                    node_info = f" node={e['node']}" if e.get("node") else ""
                    line = (
                        f"  {marker} {e['ts']} [{e['user']}] "
                        f"{e['action']}.{e['step']}{node_info}{dur}"
                    )

                    # Add key details inline
                    if e.get("snapshot_hash"):
                        line += f" snap={e['snapshot_hash'][:12]}"
                    if e.get("restore_target"):
                        line += f" target={e['restore_target'][:12]}"
                    if e.get("target_node"):
                        line += f" → {e['target_node']}"
                    if e.get("files_written"):
                        line += f" wrote={list(e['files_written'].keys())}"
                    if e.get("error"):
                        line += f" ERR: {e['error'][:80]}"

                    lines.append(line)

                    # For failed verifies, print per-file detail
                    if not e["success"] and "verify" in e:
                        v = e["verify"]
                        lines.append(
                            f"      verify_node={v['node_resolved']} "
                            f"connect_failed={v['connect_failed']}"
                        )
                        if v.get("connect_error"):
                            lines.append(f"      connect_error: {v['connect_error']}")
                        for f in v["files"]:
                            if f["status"] != "ok":
                                lines.append(
                                    f"      {f['path']}: {f['status']} "
                                    f"expected={f['expected_hash']} "
                                    f"actual={f['actual_hash']} "
                                    f"err={f['error']}"
                                )
                                if f["actual_preview"]:
                                    lines.append(f"        content: {f['actual_preview']}")

                    # Show file_hashes state changes
                    if e.get("file_hashes_before") is not None:
                        lines.append(f"      hashes_before: {e['file_hashes_before']}")
                    if e.get("file_hashes_after") is not None:
                        lines.append(f"      hashes_after: {e['file_hashes_after']}")

                lines.append("")

            return "\n".join(lines)

    def dump_report(self):
        """Print failure report to stdout and write to file."""
        report = self.generate_failure_report()
        print(report, flush=True)
        try:
            with open(REPORT_PATH, "w") as f:
                f.write(report)
            logger.info("Failure report written to %s", REPORT_PATH)
        except OSError as e:
            logger.warning("Cannot write report to %s: %s", REPORT_PATH, e)

    def close(self):
        if self._file:
            with contextlib.suppress(OSError):
                self._file.close()
            self._file = None
