#!/usr/bin/env python3
"""
End-to-End Container Test Script

Tests the complete flow of:
1. Login (or register) a user
2. Create a new blank project
3. Add a Next.js container (simulates drag to grid)
4. Start the container
5. Wait for container to be ready (max 60 seconds)
6. Check if the dev server URL loads
7. Clean up (delete project)

Usage:
    python scripts/test_container_e2e.py

Environment variables:
    API_BASE_URL - Backend API URL (default: http://localhost:8000)
    TEST_EMAIL - Test user email (default: test@tesslate.com)
    TEST_PASSWORD - Test user password (default: testpassword123)
"""

import requests
import time
import sys
import os
import uuid
from datetime import datetime

# Fix Windows console encoding
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Configuration
API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
TEST_EMAIL = os.environ.get("TEST_EMAIL", "test@tesslate.com")
TEST_PASSWORD = os.environ.get("TEST_PASSWORD", "testpassword123")
TEST_USERNAME = os.environ.get("TEST_USERNAME", "testuser")

# Timeouts
CONTAINER_READY_TIMEOUT = 60  # 1 minute for container to be ready
CONTAINER_POLL_INTERVAL = 3  # Poll every 3 seconds
HTTP_LOAD_TIMEOUT = 30  # 30 seconds for HTTP check


class TestResult:
    """Track test results"""
    def __init__(self):
        self.steps = []
        self.project_slug = None
        self.project_id = None
        self.token = None
        self.success = True

    def log(self, step: str, success: bool, message: str):
        status = "[OK]" if success else "[FAIL]"
        print(f"{status} {step}: {message}")
        self.steps.append({
            "step": step,
            "success": success,
            "message": message,
            "timestamp": datetime.now().isoformat()
        })
        if not success:
            self.success = False


def login_or_register(result: TestResult) -> str:
    """Login with existing user or register a new one. Returns JWT token."""

    # Try to login first
    print(f"\n--- Attempting login as {TEST_EMAIL} ---")
    login_response = requests.post(
        f"{API_BASE_URL}/api/auth/jwt/login",
        data={
            "username": TEST_EMAIL,
            "password": TEST_PASSWORD
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )

    if login_response.status_code == 200:
        token = login_response.json().get("access_token")
        result.log("Login", True, f"Logged in as {TEST_EMAIL}")
        return token

    # Login failed, try to register
    print(f"Login failed (status {login_response.status_code}), attempting registration...")

    register_response = requests.post(
        f"{API_BASE_URL}/api/auth/register",
        json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD,
            "name": "Test User",
            "username": TEST_USERNAME
        }
    )

    if register_response.status_code in [200, 201]:
        result.log("Register", True, f"Registered new user {TEST_EMAIL}")

        # Now login
        login_response = requests.post(
            f"{API_BASE_URL}/api/auth/jwt/login",
            data={
                "username": TEST_EMAIL,
                "password": TEST_PASSWORD
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

        if login_response.status_code == 200:
            token = login_response.json().get("access_token")
            result.log("Login", True, f"Logged in as {TEST_EMAIL}")
            return token
        else:
            result.log("Login", False, f"Failed to login after registration: {login_response.text}")
            return None
    else:
        result.log("Register", False, f"Registration failed: {register_response.text}")
        result.log("Login", False, f"Login also failed: {login_response.text}")
        return None


def create_project(result: TestResult, token: str, base_id: str) -> dict:
    """Create a new project from a marketplace base. Returns project dict with container auto-created."""

    project_name = f"test-e2e-{uuid.uuid4().hex[:6]}"

    print(f"\n--- Creating project: {project_name} ---")

    response = requests.post(
        f"{API_BASE_URL}/api/projects/",
        json={
            "name": project_name,
            "description": "E2E Test Project",
            "source_type": "base",
            "base_id": base_id,
        },
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
    )

    if response.status_code in [200, 201]:
        data = response.json()
        project = data.get("project", data)
        task_id = data.get("task_id")

        result.project_slug = project.get("slug")
        result.project_id = project.get("id")
        result.log("Create Project", True, f"Project created: {result.project_slug}")

        # Wait for project setup task to complete
        if task_id:
            print(f"Waiting for project setup task {task_id}...")
            if wait_for_task(token, task_id, timeout=120):
                result.log("Project Setup", True, "Project setup completed")
            else:
                result.log("Project Setup", False, "Project setup timed out or failed")
                return None

        return project
    else:
        result.log("Create Project", False, f"Failed: {response.status_code} - {response.text}")
        return None


def wait_for_task(token: str, task_id: str, timeout: int = 60) -> bool:
    """Wait for a background task to complete."""
    start_time = time.time()

    while time.time() - start_time < timeout:
        response = requests.get(
            f"{API_BASE_URL}/api/tasks/{task_id}/status",
            headers={"Authorization": f"Bearer {token}"}
        )

        if response.status_code == 200:
            task = response.json()
            status = task.get("status")
            progress = task.get("progress", {})
            pct = progress.get("percentage", 0) if isinstance(progress, dict) else 0

            print(f"  Task status: {status} ({pct}%)")

            if status == "completed":
                return True
            elif status == "failed":
                print(f"  Task failed: {task.get('error')}")
                return False
        else:
            print(f"  Failed to get task status: {response.status_code}")

        time.sleep(2)

    return False


def get_nextjs_marketplace_base(token: str) -> dict:
    """Get the Next.js marketplace base with git repo."""

    print(f"\n--- Fetching marketplace bases ---")

    response = requests.get(
        f"{API_BASE_URL}/api/marketplace/bases",
        headers={"Authorization": f"Bearer {token}"}
    )

    if response.status_code != 200:
        print(f"Failed to get bases: {response.status_code} - {response.text}")
        return None

    data = response.json()
    bases = data.get("bases", [])  # API returns {"bases": [...], "page": ..., ...}
    nextjs_base = next((b for b in bases if "next" in b.get("name", "").lower()), None)

    if nextjs_base:
        print(f"Found Next.js base: {nextjs_base.get('name')} (id: {nextjs_base.get('id')})")
        print(f"  Git URL: {nextjs_base.get('git_repo_url', 'N/A')}")
        print(f"  Slug: {nextjs_base.get('slug', 'N/A')}")
    else:
        print(f"Next.js base not found in {len(bases)} bases")
        for b in bases:
            print(f"  - {b.get('name')} ({b.get('slug')})")

    return nextjs_base


def add_base_to_library(token: str, base_id: str) -> bool:
    """Add a marketplace base to the user's library (purchase/add free)."""
    print(f"\n--- Adding base {base_id} to library ---")
    response = requests.post(
        f"{API_BASE_URL}/api/marketplace/bases/{base_id}/purchase",
        headers={"Authorization": f"Bearer {token}"},
    )
    if response.status_code in [200, 201]:
        print(f"  Base added to library")
        return True
    else:
        print(f"  Failed: {response.status_code} - {response.text}")
        return False


def get_project_container(result: TestResult, token: str) -> dict:
    """Get the auto-created container from a project created with source_type='base'."""
    print(f"\n--- Getting project container ---")
    response = requests.get(
        f"{API_BASE_URL}/api/projects/{result.project_slug}/containers",
        headers={"Authorization": f"Bearer {token}"},
    )
    if response.status_code == 200:
        containers = response.json()
        if containers:
            container = containers[0]
            result.log("Get Container", True, f"Found container: {container.get('id')}")
            return container
    result.log("Get Container", False, f"No containers found for project")
    return None


def start_container(result: TestResult, token: str, container_id: str) -> bool:
    """Start a specific container."""

    print(f"\n--- Starting container {container_id} ---")

    response = requests.post(
        f"{API_BASE_URL}/api/projects/{result.project_slug}/containers/{container_id}/start",
        headers={"Authorization": f"Bearer {token}"}
    )

    if response.status_code in [200, 202]:
        data = response.json()
        task_id = data.get("task_id")
        result.log("Start Container", True, f"Container start initiated (task: {task_id})")
        return True
    else:
        result.log("Start Container", False, f"Failed: {response.status_code} - {response.text}")
        return False


def wait_for_container_ready(result: TestResult, token: str) -> dict:
    """Wait for the container to become ready."""

    print(f"\n--- Waiting for container to be ready (max {CONTAINER_READY_TIMEOUT}s) ---")
    start_time = time.time()

    while time.time() - start_time < CONTAINER_READY_TIMEOUT:
        response = requests.get(
            f"{API_BASE_URL}/api/projects/{result.project_slug}/container-status",
            headers={"Authorization": f"Bearer {token}"}
        )

        if response.status_code == 200:
            status = response.json()
            ready = status.get("ready", False)
            phase = status.get("phase", "Unknown")
            message = status.get("message", "")
            url = status.get("url")

            elapsed = int(time.time() - start_time)
            print(f"  [{elapsed}s] Phase: {phase}, Ready: {ready}, URL: {url}")
            if message:
                print(f"         Message: {message}")

            if ready:
                result.log("Container Ready", True, f"Container is ready at {url}")
                return status
        else:
            print(f"  Status check failed: {response.status_code}")

        time.sleep(CONTAINER_POLL_INTERVAL)

    result.log("Container Ready", False, f"Timed out after {CONTAINER_READY_TIMEOUT}s")
    return None


def verify_files_on_pvc(result: TestResult, container_dir: str) -> bool:
    """Verify that Next.js files exist on the PVC using kubectl exec."""
    import subprocess

    print(f"\n--- Verifying files in container directory: {container_dir} ---")

    namespace = f"proj-{result.project_id}"

    try:
        # Get file-manager pod name
        cmd = ["kubectl", "get", "pods", "-n", namespace, "-l", "app=file-manager", "-o", "jsonpath={.items[0].metadata.name}"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if proc.returncode != 0 or not proc.stdout.strip():
            result.log("Verify Files", False, f"Could not find file-manager pod: {proc.stderr}")
            return False

        pod_name = proc.stdout.strip()
        print(f"  Found file-manager pod: {pod_name}")

        # List files in container directory
        env = {**os.environ, "MSYS_NO_PATHCONV": "1"}  # Fix Windows path conversion
        cmd = ["kubectl", "exec", "-n", namespace, pod_name, "--", "ls", "-la", f"/app/{container_dir}/"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)

        if proc.returncode != 0:
            result.log("Verify Files", False, f"Failed to list files: {proc.stderr}")
            return False

        print(f"  Files in /app/{container_dir}/:")
        for line in proc.stdout.strip().split('\n')[:15]:
            print(f"    {line}")

        # Check for package.json
        if "package.json" not in proc.stdout:
            result.log("Verify Files", False, "package.json not found - git clone likely failed")
            return False

        # Check for node_modules
        if "node_modules" not in proc.stdout:
            result.log("Verify Files", False, "node_modules not found - npm install likely failed")
            return False

        # Check for node_modules/.bin/next (symlink verification)
        cmd = ["kubectl", "exec", "-n", namespace, pod_name, "--", "ls", "-la", f"/app/{container_dir}/node_modules/.bin/"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)

        if proc.returncode == 0 and "next" in proc.stdout:
            print(f"  node_modules/.bin/next found - symlinks preserved!")
            result.log("Verify Files", True, "All files present including node_modules/.bin symlinks")
        else:
            print(f"  WARNING: node_modules/.bin/next not found (symlinks may be broken)")
            result.log("Verify Files", True, "Files present but symlinks may be missing")

        return True

    except subprocess.TimeoutExpired:
        result.log("Verify Files", False, "kubectl command timed out")
        return False
    except Exception as e:
        result.log("Verify Files", False, f"Error: {e}")
        return False


def check_dev_server_url(result: TestResult, url: str) -> bool:
    """Check if the dev server URL is accessible."""

    if not url:
        result.log("Check URL", False, "No URL provided")
        return False

    print(f"\n--- Checking dev server URL: {url} ---")

    # Try multiple times with retries
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.get(url, timeout=HTTP_LOAD_TIMEOUT, allow_redirects=True)

            if response.status_code == 200:
                content_length = len(response.content)
                has_html = b"<html" in response.content.lower() or b"<!doctype" in response.content.lower()

                if has_html and content_length > 100:
                    result.log("Check URL", True, f"URL loads successfully ({content_length} bytes)")
                    return True
                else:
                    print(f"  Attempt {attempt + 1}: Got response but content seems invalid")
            else:
                print(f"  Attempt {attempt + 1}: Status {response.status_code}")

        except requests.exceptions.RequestException as e:
            print(f"  Attempt {attempt + 1}: Request failed - {e}")

        if attempt < max_retries - 1:
            time.sleep(3)

    result.log("Check URL", False, f"URL check failed after {max_retries} attempts")
    return False


def delete_project(result: TestResult, token: str) -> bool:
    """Delete the test project."""

    if not result.project_slug:
        return False

    print(f"\n--- Deleting project: {result.project_slug} ---")

    response = requests.delete(
        f"{API_BASE_URL}/api/projects/{result.project_slug}",
        headers={"Authorization": f"Bearer {token}"}
    )

    if response.status_code in [200, 204]:
        result.log("Delete Project", True, f"Project deleted: {result.project_slug}")
        return True
    else:
        result.log("Delete Project", False, f"Failed: {response.status_code} - {response.text}")
        return False


def run_test():
    """Run the end-to-end container test."""

    print("=" * 60)
    print("End-to-End Container Test")
    print(f"API: {API_BASE_URL}")
    print(f"User: {TEST_EMAIL}")
    print("=" * 60)

    result = TestResult()

    try:
        # Step 1: Login
        token = login_or_register(result)
        if not token:
            print("\n[FAIL] TEST FAILED: Could not authenticate")
            return False

        result.token = token

        # Step 2: Get marketplace base and add to library
        nextjs_base = get_nextjs_marketplace_base(token)
        if not nextjs_base:
            result.log("Get Base", False, "Could not find Next.js marketplace base")
            print("\n[FAIL] TEST FAILED: No Next.js base found")
            return False
        result.log("Get Base", True, f"Found base: {nextjs_base.get('name')}")

        base_id = nextjs_base.get("id")
        if not add_base_to_library(token, base_id):
            result.log("Add to Library", False, "Could not add base to library")
            print("\n[FAIL] TEST FAILED: Could not add base to library")
            return False
        result.log("Add to Library", True, "Base added to library")

        # Step 3: Create project from base (container auto-created)
        project = create_project(result, token, base_id)
        if not project:
            print("\n[FAIL] TEST FAILED: Could not create project")
            return False

        # Step 3b: Get the auto-created container
        container = get_project_container(result, token)
        if not container:
            print("\n[FAIL] TEST FAILED: No container found after project creation")
            delete_project(result, token)
            return False

        container_id = container.get("id")

        # Step 4: Start the container
        if not start_container(result, token, container_id):
            print("\n[FAIL] TEST FAILED: Could not start container")
            delete_project(result, token)
            return False

        # Step 5: Wait for container to be ready (max 60s)
        status = wait_for_container_ready(result, token)
        if not status:
            print("\n[FAIL] TEST FAILED: Container did not become ready within 60s")
            delete_project(result, token)
            return False

        # Step 5.5: Verify files exist on PVC (critical test!)
        container_dir = container.get("directory", "next-js-15")
        if not verify_files_on_pvc(result, container_dir):
            print("\n[FAIL] TEST FAILED: Files not found on PVC")
            delete_project(result, token)
            return False

        # Step 6: Check if URL loads
        url = status.get("url")
        if not check_dev_server_url(result, url):
            print("\n[FAIL] TEST FAILED: Dev server URL not accessible")
            delete_project(result, token)
            return False

        # Success! Clean up
        print("\n" + "=" * 60)
        print("[OK] ALL TESTS PASSED!")
        print("=" * 60)

        # Clean up
        print("\nCleaning up test project...")
        delete_project(result, token)

        return True

    except Exception as e:
        result.log("Unexpected Error", False, str(e))
        print(f"\n[FAIL] TEST FAILED with exception: {e}")

        # Try to clean up
        if result.token and result.project_slug:
            delete_project(result, result.token)

        return False

    finally:
        # Print summary
        print("\n" + "-" * 60)
        print("Test Summary:")
        print("-" * 60)
        for step in result.steps:
            status = "[OK]" if step["success"] else "[FAIL]"
            print(f"  {status} {step['step']}: {step['message']}")


if __name__ == "__main__":
    success = run_test()
    sys.exit(0 if success else 1)
