#!/usr/bin/env python3
"""
Container Return Timing Diagnostic Script

Measures exactly how long it takes for a preview URL to appear when a user
returns to a project page with an already-running container. Replicates the
exact API calls made by the frontend's useEffect hooks in Project.tsx.

Usage:
    python scripts/diagnose_container_return.py                          # Interactive: list bases, pick one
    python scripts/diagnose_container_return.py --base nextjs-16         # Test specific base by slug
    python scripts/diagnose_container_return.py --base all               # Test ALL bases sequentially
    python scripts/diagnose_container_return.py --base nextjs-16 --runs 5  # 5 "return" simulations
    python scripts/diagnose_container_return.py --slug my-existing-proj  # Skip create, use existing project

Environment variables:
    API_BASE_URL   - Backend API URL (default: http://localhost:8000)
    TEST_EMAIL     - Test user email (default: test@tesslate.com)
    TEST_PASSWORD  - Test user password (default: testpassword123)
"""

import argparse
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

import requests

# Fix Windows console encoding
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
TEST_EMAIL = os.environ.get("TEST_EMAIL", "test@tesslate.com")
TEST_PASSWORD = os.environ.get("TEST_PASSWORD", "testpassword123")
TEST_USERNAME = os.environ.get("TEST_USERNAME", "testuser")

CONTAINER_READY_TIMEOUT = 120  # seconds
TASK_POLL_INTERVAL = 2  # seconds
HEALTH_POLL_INTERVAL = 2  # seconds


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class TimingResult:
    """Timing data from a single diagnostic run."""
    # Parallel block (useEffect #1)
    load_project_ms: float = 0
    load_dev_server_url_ms: float = 0
    load_settings_ms: float = 0
    load_agents_ms: float = 0
    parallel_total_ms: float = 0

    # Sequential block (useEffect #2 — loadContainer)
    get_containers_ms: float = 0
    get_containers_status_ms: float = 0
    fast_path: bool = False

    # Slow path (only if fast_path=False)
    start_container_ms: float = 0
    task_poll_ms: float = 0
    task_poll_count: int = 0
    health_poll_ms: float = 0
    health_poll_count: int = 0

    # Comparison checks
    direct_health_ms: float = 0
    direct_preview_ms: float = 0

    # Computed
    total_to_url_ms: float = 0

    # Metadata
    dev_server_url_status: str = ""
    containers_status_response: dict = field(default_factory=dict)
    error: str = ""


# ---------------------------------------------------------------------------
# Auth helper (from test_container_e2e.py)
# ---------------------------------------------------------------------------
def login_or_register() -> str:
    """Login with existing user or register a new one. Returns JWT token."""
    print(f"\n--- Authenticating as {TEST_EMAIL} ---")
    resp = requests.post(
        f"{API_BASE_URL}/api/auth/jwt/login",
        data={"username": TEST_EMAIL, "password": TEST_PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if resp.status_code == 200:
        token = resp.json().get("access_token")
        print(f"  Logged in successfully")
        return token

    # Try register
    print(f"  Login failed ({resp.status_code}), attempting registration...")
    resp2 = requests.post(
        f"{API_BASE_URL}/api/auth/register",
        json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD,
            "name": "Test User",
            "username": TEST_USERNAME,
        },
    )
    if resp2.status_code not in (200, 201):
        print(f"  Registration failed: {resp2.text}")
        sys.exit(1)

    resp3 = requests.post(
        f"{API_BASE_URL}/api/auth/jwt/login",
        data={"username": TEST_EMAIL, "password": TEST_PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if resp3.status_code == 200:
        print(f"  Registered and logged in")
        return resp3.json().get("access_token")

    print(f"  Failed to login after registration: {resp3.text}")
    sys.exit(1)


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Marketplace bases
# ---------------------------------------------------------------------------
def fetch_marketplace_bases(token: str) -> list:
    """Fetch all available marketplace bases."""
    resp = requests.get(
        f"{API_BASE_URL}/api/marketplace/bases",
        headers=auth_headers(token),
        params={"limit": 50},
    )
    if resp.status_code != 200:
        print(f"  Failed to fetch bases: {resp.status_code} - {resp.text}")
        return []
    return resp.json().get("bases", [])


def find_base_by_slug(bases: list, slug: str) -> dict | None:
    return next((b for b in bases if b.get("slug") == slug), None)


# ---------------------------------------------------------------------------
# Task polling
# ---------------------------------------------------------------------------
def wait_for_task(token: str, task_id: str, timeout: int = 120) -> bool:
    """Wait for a background task to complete."""
    start = time.time()
    while time.time() - start < timeout:
        resp = requests.get(
            f"{API_BASE_URL}/api/tasks/{task_id}/status",
            headers=auth_headers(token),
        )
        if resp.status_code == 200:
            data = resp.json()
            status = data.get("status")
            pct = 0
            progress = data.get("progress", {})
            if isinstance(progress, dict):
                pct = progress.get("percentage", 0)
            print(f"    Task {status} ({pct}%)")
            if status == "completed":
                return True
            if status == "failed":
                print(f"    Task failed: {data.get('error')}")
                return False
        time.sleep(TASK_POLL_INTERVAL)
    return False


# ---------------------------------------------------------------------------
# Project setup (Phase 1)
# ---------------------------------------------------------------------------
def add_base_to_library(token: str, base_id: str) -> bool:
    """Add a marketplace base to the user's library (purchase/add free)."""
    print(f"  Adding base {base_id} to library...")
    resp = requests.post(
        f"{API_BASE_URL}/api/marketplace/bases/{base_id}/purchase",
        headers=auth_headers(token),
    )
    if resp.status_code in (200, 201):
        print(f"  Base added to library")
        return True
    print(f"  Failed to add base to library: {resp.status_code} - {resp.text}")
    return False


def create_project(token: str, base: dict) -> dict:
    """Create a project from a marketplace base. Container is auto-created."""
    name = f"diag-{uuid.uuid4().hex[:6]}"
    base_id = base.get("id")
    print(f"\n--- Creating project: {name} (base: {base.get('slug')}) ---")

    # Ensure base is in user's library
    add_base_to_library(token, base_id)

    resp = requests.post(
        f"{API_BASE_URL}/api/projects/",
        json={
            "name": name,
            "description": "Timing diagnostic",
            "source_type": "base",
            "base_id": base_id,
        },
        headers={**auth_headers(token), "Content-Type": "application/json"},
    )
    if resp.status_code not in (200, 201):
        print(f"  Failed: {resp.status_code} - {resp.text}")
        return {}
    data = resp.json()
    project = data.get("project", data)
    task_id = data.get("task_id")
    print(f"  Created: {project.get('slug')}")
    if task_id:
        print(f"  Waiting for setup task...")
        if not wait_for_task(token, task_id, timeout=120):
            print(f"  Setup task failed or timed out")
            return {}
    return project


def get_project_container(token: str, project_slug: str) -> dict:
    """Get the auto-created container from a project."""
    resp = requests.get(
        f"{API_BASE_URL}/api/projects/{project_slug}/containers",
        headers=auth_headers(token),
    )
    if resp.status_code == 200:
        containers = resp.json()
        if containers:
            return containers[0]
    return {}


def start_and_wait(token: str, project_slug: str, container_id: str) -> str | None:
    """Start a container and wait for it to be healthy. Returns preview URL or None."""
    print(f"\n--- Starting container {container_id} ---")
    resp = requests.post(
        f"{API_BASE_URL}/api/projects/{project_slug}/containers/{container_id}/start",
        headers=auth_headers(token),
    )
    if resp.status_code not in (200, 202):
        print(f"  Start failed: {resp.status_code} - {resp.text}")
        return None

    data = resp.json()
    if data.get("already_running"):
        print(f"  Already running at {data.get('url')}")
        return data.get("url")

    task_id = data.get("task_id")
    if task_id:
        print(f"  Waiting for start task...")
        if not wait_for_task(token, task_id, timeout=CONTAINER_READY_TIMEOUT):
            print(f"  Start task failed or timed out")
            return None

    # Poll health
    print(f"  Polling health...")
    start_time = time.time()
    while time.time() - start_time < CONTAINER_READY_TIMEOUT:
        hr = requests.get(
            f"{API_BASE_URL}/api/projects/{project_slug}/containers/{container_id}/health",
            headers=auth_headers(token),
        )
        if hr.status_code == 200:
            hdata = hr.json()
            if hdata.get("healthy"):
                url = hdata.get("url")
                print(f"  Healthy at {url}")
                return url
        time.sleep(HEALTH_POLL_INTERVAL)

    print(f"  Health check timed out")
    return None


def delete_project(token: str, project_slug: str):
    """Delete a project."""
    print(f"\n--- Deleting project: {project_slug} ---")
    resp = requests.delete(
        f"{API_BASE_URL}/api/projects/{project_slug}",
        headers=auth_headers(token),
    )
    if resp.status_code in (200, 204):
        print(f"  Deleted")
    else:
        print(f"  Delete failed: {resp.status_code} - {resp.text}")


# ---------------------------------------------------------------------------
# Timed HTTP call helper
# ---------------------------------------------------------------------------
def timed_get(url: str, headers: dict, timeout: float = 30.0, label: str = "") -> tuple[float, requests.Response | None]:
    """GET request returning (elapsed_ms, response). Never raises."""
    t0 = time.perf_counter()
    try:
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        elapsed = (time.perf_counter() - t0) * 1000
        return elapsed, resp
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        if label:
            print(f"    {label}: request failed ({e})")
        return elapsed, None


# ---------------------------------------------------------------------------
# Phase 2: Diagnostic run (simulates returning to project page)
# ---------------------------------------------------------------------------
def run_diagnostic(
    token: str,
    project_slug: str,
    container_id: str,
    run_number: int,
    total_runs: int,
) -> TimingResult:
    """Simulate the frontend loading a project page and measure each step."""
    result = TimingResult()
    hdrs = auth_headers(token)
    overall_start = time.perf_counter()

    print(f"\n--- Run {run_number} / {total_runs} ---")

    # -----------------------------------------------------------------------
    # Step 1: Parallel block (useEffect #1)
    # The frontend fires these concurrently. We use a thread pool to replicate.
    # -----------------------------------------------------------------------
    parallel_calls = {
        "load_project": f"{API_BASE_URL}/api/projects/{project_slug}",
        "load_dev_server_url": f"{API_BASE_URL}/api/projects/{project_slug}/dev-server-url",
        "load_settings": f"{API_BASE_URL}/api/projects/{project_slug}/settings",
        "load_agents": f"{API_BASE_URL}/api/marketplace/my-agents",
    }

    parallel_results = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(timed_get, url, hdrs, 30.0, name): name
            for name, url in parallel_calls.items()
        }
        for future in as_completed(futures):
            name = futures[future]
            ms, resp = future.result()
            parallel_results[name] = (ms, resp)

    result.load_project_ms = parallel_results["load_project"][0]
    result.load_dev_server_url_ms = parallel_results["load_dev_server_url"][0]
    result.load_settings_ms = parallel_results["load_settings"][0]
    result.load_agents_ms = parallel_results["load_agents"][0]
    result.parallel_total_ms = max(
        result.load_project_ms,
        result.load_dev_server_url_ms,
        result.load_settings_ms,
        result.load_agents_ms,
    )

    # Check dev-server-url response
    dev_resp = parallel_results["load_dev_server_url"][1]
    if dev_resp and dev_resp.status_code == 200:
        result.dev_server_url_status = dev_resp.json().get("status", "unknown")
    else:
        result.dev_server_url_status = f"error({dev_resp.status_code if dev_resp else 'N/A'})"

    print(f"  [Parallel Block - useEffect #1]")
    print(f"    load_project:           {result.load_project_ms:,.0f}ms")
    print(f"    load_dev_server_url:    {result.load_dev_server_url_ms:,.0f}ms  -> {result.dev_server_url_status}")
    print(f"    load_settings:          {result.load_settings_ms:,.0f}ms")
    print(f"    load_agents:            {result.load_agents_ms:,.0f}ms")
    print(f"    parallel_total:         {result.parallel_total_ms:,.0f}ms  (max of above)")

    # -----------------------------------------------------------------------
    # Step 2: Sequential block (useEffect #2 — loadContainer)
    # -----------------------------------------------------------------------
    print(f"\n  [Sequential Block - useEffect #2 (loadContainer)]")

    # 2a. GET containers
    ms_containers, resp_containers = timed_get(
        f"{API_BASE_URL}/api/projects/{project_slug}/containers", hdrs
    )
    result.get_containers_ms = ms_containers
    print(f"    get_containers:         {ms_containers:,.0f}ms")

    # 2b. GET containers/status — suspected bottleneck
    ms_status, resp_status = timed_get(
        f"{API_BASE_URL}/api/projects/{project_slug}/containers/status", hdrs
    )
    result.get_containers_status_ms = ms_status
    print(f"    get_containers_status:  {ms_status:,.0f}ms", end="")
    if ms_status > 1000:
        print(f"  <<< BOTTLENECK")
    else:
        print()

    # 2c. Check fast path: is container running with URL?
    preview_url = None
    if resp_status and resp_status.status_code == 200:
        status_data = resp_status.json()
        result.containers_status_response = status_data
        containers_map = status_data.get("containers", {})
        # Look through all containers for one that's running with a URL
        for _dir_name, cinfo in containers_map.items():
            if cinfo.get("running") and cinfo.get("url"):
                result.fast_path = True
                preview_url = cinfo["url"]
                break

    print(f"    fast_path:              {'YES' if result.fast_path else 'NO'}", end="")
    if result.fast_path:
        print(f" (container running, URL: {preview_url})")
    else:
        print(f" (container NOT detected as running)")

    # 2d. Slow path — start container if not running
    if not result.fast_path:
        print(f"\n  [Slow Path - Starting container]")
        t0 = time.perf_counter()
        start_resp = requests.post(
            f"{API_BASE_URL}/api/projects/{project_slug}/containers/{container_id}/start",
            headers=hdrs,
        )
        result.start_container_ms = (time.perf_counter() - t0) * 1000
        print(f"    start_container POST:   {result.start_container_ms:,.0f}ms")

        if start_resp.status_code in (200, 202):
            start_data = start_resp.json()

            if start_data.get("already_running"):
                preview_url = start_data.get("url")
                print(f"    Server says already running at {preview_url}")
            else:
                task_id = start_data.get("task_id")
                if task_id:
                    # Poll task
                    t0_task = time.perf_counter()
                    poll_count = 0
                    while True:
                        poll_count += 1
                        task_resp = requests.get(
                            f"{API_BASE_URL}/api/tasks/{task_id}/status",
                            headers=hdrs,
                        )
                        if task_resp.status_code == 200:
                            td = task_resp.json()
                            if td.get("status") == "completed":
                                break
                            if td.get("status") == "failed":
                                result.error = f"Task failed: {td.get('error')}"
                                break
                        if time.perf_counter() - t0_task > CONTAINER_READY_TIMEOUT:
                            result.error = "Task poll timed out"
                            break
                        time.sleep(1)

                    result.task_poll_ms = (time.perf_counter() - t0_task) * 1000
                    result.task_poll_count = poll_count
                    print(f"    task_poll:              {result.task_poll_ms:,.0f}ms ({poll_count} polls)")

                # Poll health
                t0_health = time.perf_counter()
                health_count = 0
                while time.perf_counter() - t0_health < CONTAINER_READY_TIMEOUT:
                    health_count += 1
                    hr = requests.get(
                        f"{API_BASE_URL}/api/projects/{project_slug}/containers/{container_id}/health",
                        headers=hdrs,
                    )
                    if hr.status_code == 200 and hr.json().get("healthy"):
                        preview_url = hr.json().get("url")
                        break
                    time.sleep(HEALTH_POLL_INTERVAL)

                result.health_poll_ms = (time.perf_counter() - t0_health) * 1000
                result.health_poll_count = health_count
                print(f"    health_poll:            {result.health_poll_ms:,.0f}ms ({health_count} polls)")

    # -----------------------------------------------------------------------
    # Step 3: Comparison checks
    # -----------------------------------------------------------------------
    print(f"\n  [Comparison Checks]")

    ms_health, _ = timed_get(
        f"{API_BASE_URL}/api/projects/{project_slug}/containers/{container_id}/health",
        hdrs,
    )
    result.direct_health_ms = ms_health
    print(f"    direct_health_check:    {ms_health:,.0f}ms")

    if preview_url:
        ms_preview, _ = timed_get(preview_url, {}, timeout=10.0)
        result.direct_preview_ms = ms_preview
        print(f"    direct_preview_fetch:   {ms_preview:,.0f}ms")
    else:
        print(f"    direct_preview_fetch:   SKIPPED (no URL)")

    # -----------------------------------------------------------------------
    # Total
    # -----------------------------------------------------------------------
    if result.fast_path:
        result.total_to_url_ms = result.parallel_total_ms + result.get_containers_ms + result.get_containers_status_ms
    else:
        result.total_to_url_ms = (time.perf_counter() - overall_start) * 1000

    print(f"\n  TOTAL to preview URL:     {result.total_to_url_ms:,.0f}ms")

    return result


# ---------------------------------------------------------------------------
# Phase 3: Report
# ---------------------------------------------------------------------------
def print_summary(base_name: str, base_slug: str, project_slug: str, container_id: str, runs: list[TimingResult]):
    """Print aggregate summary for all runs."""
    n = len(runs)
    if n == 0:
        return

    def stats(values: list[float]) -> tuple[float, float, float]:
        avg = sum(values) / len(values)
        return avg, min(values), max(values)

    def fmt_row(label: str, values: list[float], flag_threshold: float = 0):
        avg, mn, mx = stats(values)
        line = f"  {label:<28s} {avg:>8,.0f}ms   {mn:>8,.0f}ms   {mx:>8,.0f}ms"
        if flag_threshold and avg > flag_threshold:
            line += "  <<< BOTTLENECK"
        print(line)

    sep = "=" * 72
    print(f"\n{sep}")
    print(f"SUMMARY: {base_name} ({base_slug})")
    print(f"{sep}")
    print(f"  Project: {project_slug}")
    print(f"  Container: {container_id}")
    print(f"  API: {API_BASE_URL}")
    print(f"  Runs: {n}")
    print()
    print(f"  {'Metric':<28s} {'Avg':>10s}   {'Min':>10s}   {'Max':>10s}")
    print(f"  {'-'*28} {'-'*10}   {'-'*10}   {'-'*10}")

    fmt_row("load_project", [r.load_project_ms for r in runs])
    fmt_row("load_dev_server_url", [r.load_dev_server_url_ms for r in runs])
    fmt_row("load_settings", [r.load_settings_ms for r in runs])
    fmt_row("load_agents", [r.load_agents_ms for r in runs])
    fmt_row("get_containers", [r.get_containers_ms for r in runs])
    fmt_row("get_containers_status", [r.get_containers_status_ms for r in runs], flag_threshold=500)
    fmt_row("direct_health_check", [r.direct_health_ms for r in runs])
    fmt_row("direct_preview_fetch", [r.direct_preview_ms for r in runs])
    print()

    avg_total, min_total, max_total = stats([r.total_to_url_ms for r in runs])
    print(f"  Total to preview URL:     {avg_total:,.0f}ms avg ({min_total:,.0f}ms - {max_total:,.0f}ms)")

    fast_count = sum(1 for r in runs if r.fast_path)
    print(f"  Fast path taken:          {fast_count}/{n} runs ({fast_count * 100 // n}%)")

    # Race condition warning
    multi_count = sum(1 for r in runs if r.dev_server_url_status == "multi_container")
    if multi_count > 0:
        print(f"\n  RACE CONDITION: loadDevServerUrl returned 'multi_container' in {multi_count}/{n} runs.")
        print(f"    In frontend, this returns url=null and status='multi_container'.")
        print(f"    The frontend's setDevServerUrl(null) could overwrite the URL set by")
        print(f"    loadContainer, depending on timing. Currently works because the parallel")
        print(f"    block completes before get_containers_status returns.")

    # Slow path details
    slow_runs = [r for r in runs if not r.fast_path]
    if slow_runs:
        print(f"\n  SLOW PATH DETAILS ({len(slow_runs)} runs took the slow path):")
        if any(r.task_poll_ms for r in slow_runs):
            fmt_row("  start_container POST", [r.start_container_ms for r in slow_runs])
            fmt_row("  task_poll", [r.task_poll_ms for r in slow_runs])
            fmt_row("  health_poll", [r.health_poll_ms for r in slow_runs])

    # Top bottlenecks
    print(f"\n  TOP BOTTLENECKS:")
    bottlenecks = [
        ("load_project", stats([r.load_project_ms for r in runs])[0]),
        ("load_dev_server_url", stats([r.load_dev_server_url_ms for r in runs])[0]),
        ("load_settings", stats([r.load_settings_ms for r in runs])[0]),
        ("load_agents", stats([r.load_agents_ms for r in runs])[0]),
        ("get_containers", stats([r.get_containers_ms for r in runs])[0]),
        ("get_containers_status", stats([r.get_containers_status_ms for r in runs])[0]),
        ("direct_health_check", stats([r.direct_health_ms for r in runs])[0]),
    ]
    bottlenecks.sort(key=lambda x: x[1], reverse=True)
    for i, (name, avg) in enumerate(bottlenecks[:3], 1):
        note = ""
        if name == "get_containers_status":
            note = " -- docker compose ps subprocess"
        elif name == "load_agents":
            note = " -- marketplace library query"
        elif name == "direct_health_check":
            note = " -- HTTP through Traefik (5s timeout)"
        print(f"    {i}. {name}: {avg:,.0f}ms avg{note}")

    print(sep)


# ---------------------------------------------------------------------------
# Resolve existing project info (for --slug mode)
# ---------------------------------------------------------------------------
def get_existing_project_info(token: str, slug: str) -> tuple[str, str, str]:
    """
    For an existing project, returns (project_id, container_id, base_display).
    Exits on failure.
    """
    hdrs = auth_headers(token)

    resp = requests.get(f"{API_BASE_URL}/api/projects/{slug}", headers=hdrs)
    if resp.status_code != 200:
        print(f"  Failed to fetch project '{slug}': {resp.status_code} - {resp.text}")
        sys.exit(1)
    project = resp.json()
    project_id = project.get("id")

    resp2 = requests.get(f"{API_BASE_URL}/api/projects/{slug}/containers", headers=hdrs)
    if resp2.status_code != 200 or not resp2.json():
        print(f"  Failed to fetch containers for '{slug}': {resp2.status_code}")
        sys.exit(1)
    containers = resp2.json()
    container = containers[0]
    container_id = container.get("id")
    base_display = container.get("name", "unknown")

    return project_id, container_id, base_display


# ---------------------------------------------------------------------------
# Main orchestration: run diagnostic for a single base
# ---------------------------------------------------------------------------
def diagnose_base(
    token: str,
    base: dict | None,
    num_runs: int,
    existing_slug: str | None = None,
    keep: bool = False,
):
    """Run the full diagnostic for one base (or existing project)."""
    project_slug = None
    container_id = None
    base_name = "unknown"
    base_slug = "unknown"
    created_project = False

    try:
        if existing_slug:
            # --slug mode: use existing project
            project_slug = existing_slug
            _pid, container_id, base_name = get_existing_project_info(token, existing_slug)
            base_slug = existing_slug
            print(f"\n  Using existing project: {project_slug}, container: {container_id}")

            # Verify container is running
            resp = requests.get(
                f"{API_BASE_URL}/api/projects/{project_slug}/containers/status",
                headers=auth_headers(token),
            )
            if resp.status_code == 200:
                status_data = resp.json()
                any_running = any(
                    c.get("running") for c in status_data.get("containers", {}).values()
                )
                if not any_running:
                    print(f"  WARNING: No containers appear to be running. Starting...")
                    url = start_and_wait(token, project_slug, container_id)
                    if not url:
                        print(f"  Failed to start container. Aborting.")
                        return
        else:
            # Full setup: create project from base (container auto-created), start it
            base_name = base.get("name", "unknown")
            base_slug = base.get("slug", "unknown")

            project = create_project(token, base)
            if not project:
                return
            project_slug = project.get("slug")
            created_project = True

            container = get_project_container(token, project_slug)
            if not container:
                print(f"  No container found after project creation")
                return
            container_id = container.get("id")

            print(f"\n--- Starting container for first time (baseline) ---")
            url = start_and_wait(token, project_slug, container_id)
            if not url:
                print(f"  Failed to start container. Aborting diagnostic.")
                return
            print(f"\n  Container is running at: {url}")
            print(f"  Baseline established. Starting diagnostic runs...\n")

        # Phase 2: Run diagnostics
        results = []
        for i in range(1, num_runs + 1):
            r = run_diagnostic(token, project_slug, container_id, i, num_runs)
            results.append(r)

            # Small pause between runs to avoid request pileup
            if i < num_runs:
                time.sleep(1)

        # Phase 3: Summary
        print_summary(base_name, base_slug, project_slug, container_id, results)

    finally:
        # Phase 4: Cleanup
        if created_project and project_slug and not keep:
            delete_project(token, project_slug)
        elif created_project and keep:
            print(f"\n  --keep flag: project '{project_slug}' NOT deleted")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Container return timing diagnostic",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--base",
        help="Marketplace base slug to test, or 'all' for all bases. "
             "Omit for interactive selection.",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Number of 'return to page' simulations per base (default: 3)",
    )
    parser.add_argument(
        "--slug",
        help="Use an existing project slug (skip create/cleanup)",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Don't delete test projects after running",
    )
    args = parser.parse_args()

    print("=" * 72)
    print("CONTAINER RETURN TIMING DIAGNOSTIC")
    print("=" * 72)
    print(f"API: {API_BASE_URL}")
    print(f"User: {TEST_EMAIL}")
    print(f"Runs per base: {args.runs}")

    token = login_or_register()

    # --slug mode: skip base selection
    if args.slug:
        print(f"\nUsing existing project: {args.slug}")
        diagnose_base(token, None, args.runs, existing_slug=args.slug, keep=True)
        return

    # Fetch bases
    bases = fetch_marketplace_bases(token)
    if not bases:
        print("No marketplace bases found. Did you run the seed scripts?")
        sys.exit(1)

    print(f"\nAvailable bases ({len(bases)}):")
    for i, b in enumerate(bases, 1):
        print(f"  {i}. {b.get('name')} ({b.get('slug')})")

    # Determine which bases to test
    if args.base == "all":
        targets = bases
        print(f"\nTesting ALL {len(targets)} bases...")
    elif args.base:
        target = find_base_by_slug(bases, args.base)
        if not target:
            print(f"\nBase '{args.base}' not found. Available slugs:")
            for b in bases:
                print(f"  - {b.get('slug')}")
            sys.exit(1)
        targets = [target]
    else:
        # Interactive selection
        try:
            choice = input(f"\nSelect base (1-{len(bases)}) or 'all': ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(0)

        if choice.lower() == "all":
            targets = bases
        else:
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(bases):
                    targets = [bases[idx]]
                else:
                    print("Invalid selection.")
                    sys.exit(1)
            except ValueError:
                # Try as slug
                target = find_base_by_slug(bases, choice)
                if target:
                    targets = [target]
                else:
                    print(f"Invalid selection: '{choice}'")
                    sys.exit(1)

    # Run diagnostics
    for base in targets:
        diagnose_base(token, base, args.runs, keep=args.keep)


if __name__ == "__main__":
    main()
