#!/usr/bin/env python3
"""
E2E Test: Next.js Container Lifecycle

This test verifies the complete container lifecycle:
1. Login and get token
2. Create a new project
3. Get the Next.js marketplace base
4. Add a container with that base (simulates dragging to grid)
5. Start the container
6. Verify files exist (package.json, etc.)
7. Verify container is running
8. Delete the project
"""

import requests
import time
import sys
import json

BASE_URL = "http://localhost:8000"
TEST_USER_EMAIL = "test@example.com"
TEST_USER_PASSWORD = "testpassword123"

def log(msg: str, level: str = "INFO"):
    print(f"[{level}] {msg}")

def login() -> str:
    """Login and return bearer token."""
    log("Logging in...")

    resp = requests.post(
        f"{BASE_URL}/api/auth/jwt/login",
        data={
            "username": TEST_USER_EMAIL,
            "password": TEST_USER_PASSWORD
        }
    )

    if resp.status_code != 200:
        log(f"Login failed: {resp.status_code} - {resp.text}", "ERROR")
        sys.exit(1)

    token = resp.json()["access_token"]
    log(f"Login successful, got token")
    return token

def create_project(token: str) -> dict:
    """Create a new project."""
    log("Creating new project...")

    resp = requests.post(
        f"{BASE_URL}/api/projects",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "E2E Test Project",
            "description": "Automated E2E test for Next.js container"
        }
    )

    if resp.status_code not in [200, 201]:
        log(f"Failed to create project: {resp.status_code} - {resp.text}", "ERROR")
        sys.exit(1)

    project = resp.json()
    log(f"Project created: {project['slug']} (ID: {project['id']})")
    return project

def get_nextjs_base(token: str) -> dict:
    """Get the Next.js marketplace base."""
    log("Fetching Next.js marketplace base...")

    resp = requests.get(
        f"{BASE_URL}/api/marketplace-bases",
        headers={"Authorization": f"Bearer {token}"}
    )

    if resp.status_code != 200:
        log(f"Failed to get bases: {resp.status_code} - {resp.text}", "ERROR")
        sys.exit(1)

    bases = resp.json()
    nextjs_base = next((b for b in bases if "next" in b["name"].lower()), None)

    if not nextjs_base:
        log(f"Next.js base not found in {len(bases)} bases: {[b['name'] for b in bases]}", "ERROR")
        sys.exit(1)

    log(f"Found Next.js base: {nextjs_base['name']} (git: {nextjs_base.get('git_repo_url', 'N/A')})")
    return nextjs_base

def add_container(token: str, project_id: str, base: dict) -> dict:
    """Add a container to the project (simulates dragging to grid)."""
    log(f"Adding container with base '{base['name']}'...")

    resp = requests.post(
        f"{BASE_URL}/api/projects/{project_id}/containers",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": base["name"],
            "base_id": base["id"],
            "directory": base.get("slug", "next-js-15"),
            "internal_port": 3000
        }
    )

    if resp.status_code not in [200, 201]:
        log(f"Failed to add container: {resp.status_code} - {resp.text}", "ERROR")
        sys.exit(1)

    container = resp.json()
    log(f"Container added: {container['name']} (ID: {container['id']})")
    return container

def start_container(token: str, project_slug: str, container_id: str) -> dict:
    """Start the container and wait for task completion."""
    log(f"Starting container {container_id}...")

    # This endpoint returns a task ID for async operation
    resp = requests.post(
        f"{BASE_URL}/api/projects/{project_slug}/containers/{container_id}/start",
        headers={"Authorization": f"Bearer {token}"}
    )

    if resp.status_code not in [200, 201, 202]:
        log(f"Failed to start container: {resp.status_code} - {resp.text}", "ERROR")
        sys.exit(1)

    result = resp.json()
    task_id = result.get("task_id")

    if task_id:
        log(f"Container start task initiated: {task_id}")
        # Poll task status
        for i in range(60):  # Wait up to 5 minutes
            time.sleep(5)
            task_resp = requests.get(
                f"{BASE_URL}/api/tasks/{task_id}",
                headers={"Authorization": f"Bearer {token}"}
            )
            if task_resp.status_code == 200:
                task = task_resp.json()
                status = task.get("status")
                progress = task.get("progress", 0)
                log(f"Task status: {status} ({progress}%)")

                if status == "completed":
                    log("Container start completed!")
                    return task.get("result", {})
                elif status == "failed":
                    log(f"Container start failed: {task.get('error')}", "ERROR")
                    sys.exit(1)
            else:
                log(f"Failed to get task status: {task_resp.status_code}", "WARN")

        log("Container start timed out", "ERROR")
        sys.exit(1)
    else:
        log(f"Container started: {result}")
        return result

def verify_files(token: str, project_id: str, container_dir: str) -> bool:
    """Verify that Next.js files exist in the container directory."""
    log(f"Verifying files in {container_dir}...")

    resp = requests.get(
        f"{BASE_URL}/api/projects/{project_id}/files",
        headers={"Authorization": f"Bearer {token}"},
        params={"path": container_dir}
    )

    if resp.status_code != 200:
        log(f"Failed to list files: {resp.status_code} - {resp.text}", "ERROR")
        return False

    files = resp.json()
    file_names = [f["name"] for f in files]

    log(f"Files found: {file_names}")

    # Check for essential Next.js files
    required_files = ["package.json"]
    missing = [f for f in required_files if f not in file_names]

    if missing:
        log(f"Missing required files: {missing}", "ERROR")
        return False

    # Check for node_modules
    if "node_modules" not in file_names:
        log("WARNING: node_modules not found - npm install may not have run", "WARN")

    log("File verification passed!")
    return True

def verify_container_running(project_id: str, container_dir: str) -> bool:
    """Verify the container pod is running in K8s."""
    import subprocess

    log(f"Verifying container pod is running...")

    namespace = f"proj-{project_id}"
    try:
        result = subprocess.run(
            ["kubectl", "get", "pods", "-n", namespace, "-o", "json"],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            log(f"kubectl failed: {result.stderr}", "ERROR")
            return False

        pods = json.loads(result.stdout)
        for pod in pods.get("items", []):
            name = pod["metadata"]["name"]
            phase = pod["status"]["phase"]
            log(f"Pod {name}: {phase}")

            # Check for dev container pod
            if f"dev-{container_dir}" in name:
                if phase == "Running":
                    log(f"Container pod {name} is Running!")
                    return True
                else:
                    log(f"Container pod {name} is {phase}", "WARN")

        return False

    except Exception as e:
        log(f"Error checking pods: {e}", "ERROR")
        return False

def verify_files_via_kubectl(project_id: str, container_dir: str) -> bool:
    """Verify files exist via kubectl exec into file-manager pod."""
    import subprocess

    log(f"Verifying files via kubectl exec...")

    namespace = f"proj-{project_id}"
    try:
        # Get file-manager pod
        result = subprocess.run(
            ["kubectl", "get", "pods", "-n", namespace, "-l", "app=file-manager", "-o", "jsonpath={.items[0].metadata.name}"],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0 or not result.stdout:
            log(f"Could not find file-manager pod: {result.stderr}", "ERROR")
            return False

        pod_name = result.stdout.strip()
        log(f"Found file-manager pod: {pod_name}")

        # List files in container directory
        result = subprocess.run(
            ["kubectl", "exec", "-n", namespace, pod_name, "--", "ls", "-la", f"/app/{container_dir}/"],
            capture_output=True,
            text=True,
            timeout=30,
            env={**dict(__import__('os').environ), "MSYS_NO_PATHCONV": "1"}
        )

        if result.returncode != 0:
            log(f"Failed to list files: {result.stderr}", "ERROR")
            return False

        log(f"Files in /app/{container_dir}/:")
        print(result.stdout)

        # Check for package.json
        if "package.json" in result.stdout:
            log("package.json found!")

            # Check for node_modules/.bin
            result2 = subprocess.run(
                ["kubectl", "exec", "-n", namespace, pod_name, "--", "ls", "-la", f"/app/{container_dir}/node_modules/.bin/"],
                capture_output=True,
                text=True,
                timeout=30,
                env={**dict(__import__('os').environ), "MSYS_NO_PATHCONV": "1"}
            )

            if result2.returncode == 0 and "next" in result2.stdout:
                log("node_modules/.bin/next found - symlinks preserved!")
                return True
            else:
                log(f"node_modules/.bin check: {result2.stderr or 'next not found'}", "WARN")

            return True
        else:
            log("package.json NOT found!", "ERROR")
            return False

    except Exception as e:
        log(f"Error verifying files: {e}", "ERROR")
        return False

def delete_project(token: str, project_slug: str):
    """Delete the test project."""
    log(f"Deleting project {project_slug}...")

    resp = requests.delete(
        f"{BASE_URL}/api/projects/{project_slug}",
        headers={"Authorization": f"Bearer {token}"}
    )

    if resp.status_code not in [200, 204]:
        log(f"Failed to delete project: {resp.status_code} - {resp.text}", "WARN")
    else:
        log("Project deleted successfully")

def main():
    log("=" * 60)
    log("E2E Test: Next.js Container Lifecycle")
    log("=" * 60)

    project = None
    token = None

    try:
        # Step 1: Login
        token = login()

        # Step 2: Create project
        project = create_project(token)

        # Step 3: Get Next.js base
        nextjs_base = get_nextjs_base(token)

        # Step 4: Add container
        container = add_container(token, project["id"], nextjs_base)
        container_dir = container.get("directory", "next-js-15")

        # Step 5: Start container
        start_result = start_container(token, project["slug"], container["id"])
        log(f"Start result: {start_result}")

        # Step 6: Wait for pod to stabilize
        log("Waiting 10 seconds for pod to stabilize...")
        time.sleep(10)

        # Step 7: Verify files via kubectl (more reliable)
        files_ok = verify_files_via_kubectl(project["id"], container_dir)

        # Step 8: Verify container is running
        container_ok = verify_container_running(project["id"], container_dir)

        # Final result
        log("=" * 60)
        if files_ok and container_ok:
            log("E2E TEST PASSED!", "SUCCESS")
            return 0
        elif files_ok:
            log("E2E TEST PARTIAL: Files OK but container not running", "WARN")
            return 1
        else:
            log("E2E TEST FAILED: Files not found", "ERROR")
            return 1

    except Exception as e:
        log(f"E2E Test failed with exception: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        # Cleanup
        if project and token:
            delete_project(token, project["slug"])

if __name__ == "__main__":
    sys.exit(main())
