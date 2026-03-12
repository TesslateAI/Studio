"""
End-to-end timing test for Next.js 16 project creation and startup.
Run inside the backend pod: python /tmp/timing_test.py
"""
import asyncio
import time
import json
import httpx
import uuid

# Config
BASE_URL = "http://localhost:8000"
USERNAME = "manav_0bcnWM"  # manav@tesslate.com
USER_ID = "5f53faa3-e96b-49d1-9536-a746d8b765b9"
BASE_ID = "47fd81d4-e74c-4399-894b-6bfde31c6d17"  # Next.js 16
PROJECT_NAME = f"timing-test-{uuid.uuid4().hex[:6]}"

timings = []

def mark(label):
    t = time.time()
    timings.append((label, t))
    elapsed = 0 if len(timings) == 1 else t - timings[-2][1]
    total = t - timings[0][1]
    print(f"[{total:7.2f}s] (+{elapsed:6.2f}s) {label}", flush=True)
    return t


async def generate_token():
    """Generate a JWT for the test user using fastapi-users format."""
    from datetime import datetime, timedelta, UTC
    from jose import jwt as jose_jwt
    from app.config import get_settings
    settings = get_settings()

    data = {
        "sub": USER_ID,
        "aud": "fastapi-users:auth",
        "exp": datetime.now(UTC) + timedelta(hours=1),
    }
    token = jose_jwt.encode(data, settings.secret_key, algorithm=settings.algorithm)
    return token


async def poll_task(client, task_id, headers, label_prefix, poll_interval=0.5):
    """Poll a task until completion, reporting progress."""
    last_progress = -1
    last_message = ""
    attempts = 0
    max_attempts = 600  # 5 minutes at 0.5s interval
    while attempts < max_attempts:
        attempts += 1
        try:
            resp = await client.get(f"{BASE_URL}/api/tasks/{task_id}/status", headers=headers)
            if resp.status_code == 404:
                # Task might be on the other pod, wait a bit
                if attempts <= 5:
                    await asyncio.sleep(poll_interval)
                    continue
                mark(f"{label_prefix}: task {task_id} not found after {attempts} attempts")
                return {"status": "not_found"}
            if resp.status_code != 200:
                mark(f"{label_prefix}: poll error {resp.status_code} - {resp.text[:100]}")
                await asyncio.sleep(poll_interval)
                continue

            data = resp.json()
            status = data.get("status", "unknown")
            progress = data.get("progress", 0)
            message = data.get("message", "")

            if progress != last_progress or message != last_message:
                mark(f"{label_prefix}: [{status}] {progress}% - {message}")
                last_progress = progress
                last_message = message

            if status in ("completed", "failed", "error", "cancelled"):
                return data

        except Exception as e:
            mark(f"{label_prefix}: poll exception: {type(e).__name__}: {str(e)[:80]}")

        await asyncio.sleep(poll_interval)

    mark(f"{label_prefix}: TIMEOUT after {max_attempts} attempts")
    return {"status": "timeout"}


async def run():
    mark("START: Generating JWT token")
    token = await generate_token()
    headers = {"Authorization": f"Bearer {token}"}
    mark("JWT token generated")

    async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
        # ========== PHASE 1: CREATE PROJECT ==========
        mark("PHASE 1: Creating project via POST /api/projects/")
        create_payload = {
            "name": PROJECT_NAME,
            "base_id": BASE_ID,
        }
        resp = await client.post(
            f"{BASE_URL}/api/projects/",
            json=create_payload,
            headers=headers,
        )
        mark(f"POST /api/projects/ returned {resp.status_code}")

        if resp.status_code not in (200, 201):
            print(f"ERROR: {resp.status_code} - {resp.text[:500]}")
            return

        create_data = resp.json()

        # Parse response - project might be nested or flat
        if "project" in create_data and isinstance(create_data["project"], dict):
            project_obj = create_data["project"]
        else:
            project_obj = create_data

        project_slug = project_obj.get("slug", create_data.get("slug"))
        project_id = project_obj.get("id", create_data.get("id"))
        task_id = create_data.get("task_id")

        print(f"  Project name: {PROJECT_NAME}")
        print(f"  Project slug: {project_slug}")
        print(f"  Project ID:   {project_id}")
        print(f"  Task ID:      {task_id}")

        # Poll project creation task
        if task_id:
            mark("Polling project creation task...")
            result = await poll_task(client, task_id, headers, "CREATE", poll_interval=0.5)
            mark(f"PHASE 1 DONE: creation task finished (status={result.get('status')})")
            if result.get("status") == "failed":
                print(f"  Error: {result.get('error', 'unknown')}")
                return
        else:
            mark("No task_id - project created synchronously")
            await asyncio.sleep(1)

        # ========== Get project details + containers ==========
        mark("Fetching project details...")
        resp = await client.get(f"{BASE_URL}/api/projects/{project_slug}", headers=headers)
        project = resp.json()
        mark(f"GET /api/projects/{project_slug} returned {resp.status_code}")

        containers = project.get("containers", [])
        print(f"  Containers: {len(containers)}")

        if not containers:
            mark("No containers found, trying /containers endpoint...")
            resp = await client.get(f"{BASE_URL}/api/projects/{project_slug}/containers", headers=headers)
            if resp.status_code == 200:
                containers = resp.json()
            mark(f"Found {len(containers)} containers via separate endpoint")

        if not containers:
            print("ERROR: No containers found!")
            print(json.dumps(project, indent=2, default=str)[:2000])
            return

        container = containers[0]
        container_id = container.get("id")
        container_name = container.get("name", container.get("directory", "unknown"))
        container_status = container.get("status", "unknown")
        print(f"  Container ID:     {container_id}")
        print(f"  Container name:   {container_name}")
        print(f"  Container status: {container_status}")

        # ========== PHASE 2: START CONTAINER ==========
        mark("PHASE 2: Starting container via POST start")
        resp = await client.post(
            f"{BASE_URL}/api/projects/{project_slug}/containers/{container_id}/start",
            headers=headers,
        )
        mark(f"POST start returned {resp.status_code}")

        if resp.status_code not in (200, 201, 202):
            print(f"ERROR: {resp.status_code} - {resp.text[:500]}")
            return

        start_data = resp.json()
        start_task_id = start_data.get("task_id")
        print(f"  Start task ID: {start_task_id}")

        if start_task_id:
            mark("Polling container start task...")
            result = await poll_task(client, start_task_id, headers, "START", poll_interval=1.0)
            mark(f"PHASE 2 DONE: start task finished (status={result.get('status')})")
            if result.get("status") == "failed":
                print(f"  Error: {result.get('error', 'unknown')}")
        else:
            mark("No task_id for start - may have started synchronously")

        # ========== PHASE 3: VERIFY CONTAINER IS RUNNING ==========
        mark("PHASE 3: Verifying container is running...")
        resp = await client.get(f"{BASE_URL}/api/projects/{project_slug}", headers=headers)
        if resp.status_code == 200:
            project = resp.json()
            for c in project.get("containers", []):
                if str(c.get("id")) == str(container_id):
                    status = c.get("status")
                    url = c.get("url") or c.get("preview_url")
                    mark(f"Container status: {status}")
                    print(f"  Preview URL: {url}")
                    break

        # ========== PHASE 4: CHECK PREVIEW ACCESSIBILITY ==========
        mark("PHASE 4: Checking preview URL accessibility...")

        # Get the URL from container details
        resp = await client.get(f"{BASE_URL}/api/projects/{project_slug}/containers", headers=headers)
        preview_url = None
        if resp.status_code == 200:
            for c in resp.json():
                if str(c.get("id")) == str(container_id):
                    preview_url = c.get("url") or c.get("preview_url")
                    break

        if preview_url:
            print(f"  Testing URL: {preview_url}")
            for attempt in range(60):  # up to 2 minutes
                try:
                    preview_resp = await client.get(preview_url, timeout=5, follow_redirects=True)
                    code = preview_resp.status_code
                    size = len(preview_resp.content)
                    if code in (200, 304):
                        mark(f"PREVIEW LIVE! HTTP {code} ({size} bytes) on attempt {attempt+1}")
                        break
                    elif attempt % 5 == 0:
                        mark(f"Preview attempt {attempt+1}: HTTP {code} ({size} bytes)")
                except httpx.ConnectError:
                    if attempt % 10 == 0:
                        mark(f"Preview attempt {attempt+1}: connection refused (not ready)")
                except httpx.ReadTimeout:
                    if attempt % 5 == 0:
                        mark(f"Preview attempt {attempt+1}: read timeout")
                except Exception as e:
                    if attempt % 5 == 0:
                        mark(f"Preview attempt {attempt+1}: {type(e).__name__}")
                await asyncio.sleep(2)
            else:
                mark("Preview did not become accessible after 60 attempts (2 min)")
        else:
            mark("No preview URL found on container")
            # Check if we can construct it
            from app.config import settings
            domain = settings.app_domain
            if domain:
                constructed_url = f"https://{project_slug}-{container_name}.{domain}"
                print(f"  Constructed URL: {constructed_url}")
                mark(f"Trying constructed URL: {constructed_url}")
                for attempt in range(60):
                    try:
                        preview_resp = await client.get(constructed_url, timeout=5, follow_redirects=True)
                        if preview_resp.status_code in (200, 304):
                            mark(f"PREVIEW LIVE! HTTP {preview_resp.status_code} on attempt {attempt+1}")
                            break
                        elif attempt % 5 == 0:
                            mark(f"Constructed URL attempt {attempt+1}: HTTP {preview_resp.status_code}")
                    except Exception as e:
                        if attempt % 10 == 0:
                            mark(f"Constructed URL attempt {attempt+1}: {type(e).__name__}")
                    await asyncio.sleep(2)

        # ========== SUMMARY ==========
        total_time = time.time() - timings[0][1]
        print("\n" + "="*80)
        print(f"TOTAL END-TO-END TIME: {total_time:.2f} seconds")
        print("="*80)
        print(f"\n{'Step':<65} {'Delta':>8} {'Total':>8}")
        print("-"*83)
        for i, (label, t) in enumerate(timings):
            delta = 0 if i == 0 else t - timings[i-1][1]
            total = t - timings[0][1]
            print(f"{label:<65} {delta:>7.2f}s {total:>7.2f}s")

        # Phase summaries
        print("\n" + "="*80)
        print("PHASE SUMMARIES:")
        phases = {}
        current_phase = None
        phase_start = None
        for label, t in timings:
            if label.startswith("PHASE"):
                if current_phase and phase_start:
                    phases[current_phase] = t - phase_start
                current_phase = label
                phase_start = t
            elif "DONE" in label or "LIVE" in label:
                if current_phase and phase_start:
                    phases[current_phase] = t - phase_start
                    current_phase = None

        for phase, duration in phases.items():
            print(f"  {phase}: {duration:.2f}s")


if __name__ == "__main__":
    asyncio.run(run())
