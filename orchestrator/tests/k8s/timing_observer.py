"""
Timing capture and reporting utilities for container startup tests.

This module provides classes to capture timing data at each phase of
container startup, track HTTP probe results (404/502 errors), and
generate detailed timing reports.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any


@dataclass
class TimingPoint:
    """A single timing measurement point."""
    phase: str
    timestamp: datetime
    elapsed_from_start_ms: float
    elapsed_from_previous_ms: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HttpProbeResult:
    """Result of an HTTP probe to the container URL."""
    timestamp: datetime
    status_code: int
    response_time_ms: float
    is_html: bool = False
    has_next_js_markers: bool = False
    error: Optional[str] = None


class StartupTimingObserver:
    """
    Captures timing for container startup phases.

    Usage:
        observer = StartupTimingObserver()
        observer.start()

        # ... do auth ...
        observer.record("auth_complete")

        # ... create project ...
        observer.record("project_created", {"slug": "my-project"})

        # ... poll container ...
        observer.record_http_probe(HttpProbeResult(...))

        # Get report
        report = observer.generate_report()
        observer.print_report()
    """

    def __init__(self):
        self.start_time: Optional[datetime] = None
        self.timing_points: List[TimingPoint] = []
        self.http_probes: List[HttpProbeResult] = []
        self._last_timestamp: Optional[datetime] = None

    def start(self):
        """Start the timer. Call this at the beginning of the test."""
        self.start_time = datetime.now(timezone.utc)
        self._last_timestamp = self.start_time
        self.record("test_start")

    def record(self, phase: str, metadata: Dict = None):
        """Record a timing point for a phase."""
        now = datetime.now(timezone.utc)

        if self.start_time is None:
            self.start_time = now
            self._last_timestamp = now

        elapsed_start = (now - self.start_time).total_seconds() * 1000
        elapsed_prev = (now - self._last_timestamp).total_seconds() * 1000

        self.timing_points.append(TimingPoint(
            phase=phase,
            timestamp=now,
            elapsed_from_start_ms=elapsed_start,
            elapsed_from_previous_ms=elapsed_prev,
            metadata=metadata or {}
        ))
        self._last_timestamp = now

    def record_http_probe(self, result: HttpProbeResult):
        """Record an HTTP probe result."""
        self.http_probes.append(result)

    def get_404_502_count(self) -> Dict[str, int]:
        """Get counts of 404 and 502 errors from HTTP probes."""
        counts = {"404": 0, "502": 0, "503": 0, "other_errors": 0, "connection_errors": 0}
        for probe in self.http_probes:
            if probe.status_code == 0:
                counts["connection_errors"] += 1
            elif probe.status_code == 404:
                counts["404"] += 1
            elif probe.status_code == 502:
                counts["502"] += 1
            elif probe.status_code == 503:
                counts["503"] += 1
            elif probe.status_code >= 400:
                counts["other_errors"] += 1
        return counts

    def get_first_success_time_ms(self) -> Optional[float]:
        """Get the time in ms when the first successful HTML response was received."""
        if self.start_time is None:
            return None

        for probe in self.http_probes:
            if probe.status_code == 200 and probe.has_next_js_markers:
                return (probe.timestamp - self.start_time).total_seconds() * 1000
        return None

    def generate_report(self) -> Dict[str, Any]:
        """Generate a timing report dictionary."""
        total_time = self.timing_points[-1].elapsed_from_start_ms if self.timing_points else 0

        return {
            "total_startup_time_ms": total_time,
            "total_startup_time_human": self._format_duration(total_time),
            "phases": [
                {
                    "phase": tp.phase,
                    "elapsed_from_start_ms": tp.elapsed_from_start_ms,
                    "elapsed_from_previous_ms": tp.elapsed_from_previous_ms,
                    "metadata": tp.metadata
                }
                for tp in self.timing_points
            ],
            "http_probes_count": len(self.http_probes),
            "error_counts": self.get_404_502_count(),
            "first_successful_response_ms": self.get_first_success_time_ms()
        }

    def _format_duration(self, ms: float) -> str:
        """Format milliseconds as human-readable duration."""
        if ms < 1000:
            return f"{ms:.0f}ms"
        elif ms < 60000:
            return f"{ms/1000:.1f}s"
        else:
            minutes = int(ms / 60000)
            seconds = (ms % 60000) / 1000
            return f"{minutes}m {seconds:.0f}s"

    def print_report(self):
        """Print a formatted timing report to stdout."""
        report = self.generate_report()

        print("\n" + "=" * 70)
        print("CONTAINER STARTUP TIMING REPORT")
        print("=" * 70)
        print(f"Total startup time: {report['total_startup_time_ms']:.0f}ms ({report['total_startup_time_human']})")
        print(f"Total HTTP probes: {report['http_probes_count']}")
        print(f"Error counts: {report['error_counts']}")

        first_success = report['first_successful_response_ms']
        if first_success:
            print(f"First HTML response at: {first_success:.0f}ms ({self._format_duration(first_success)})")
        else:
            print("First HTML response at: N/A (no successful response)")

        print("\nPhase Breakdown:")
        print("-" * 70)

        for phase in report["phases"]:
            phase_name = phase["phase"]
            elapsed_prev = phase["elapsed_from_previous_ms"]
            elapsed_total = phase["elapsed_from_start_ms"]
            metadata = phase.get("metadata", {})

            # Format metadata if present
            meta_str = ""
            if metadata:
                meta_items = [f"{k}={v}" for k, v in metadata.items()]
                meta_str = f" [{', '.join(meta_items)}]"

            print(f"  {phase_name}: +{elapsed_prev:.0f}ms (total: {elapsed_total:.0f}ms){meta_str}")

        print("=" * 70 + "\n")

    def get_phase_duration(self, phase_name: str) -> Optional[float]:
        """Get the duration of a specific phase in milliseconds."""
        for i, tp in enumerate(self.timing_points):
            if tp.phase == phase_name:
                return tp.elapsed_from_previous_ms
        return None

    def get_slowest_phases(self, n: int = 5) -> List[Dict[str, Any]]:
        """Get the N slowest phases."""
        phases = [
            {
                "phase": tp.phase,
                "duration_ms": tp.elapsed_from_previous_ms
            }
            for tp in self.timing_points
        ]
        return sorted(phases, key=lambda x: x["duration_ms"], reverse=True)[:n]
