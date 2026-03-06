"""
Container Startup Timing Test

End-to-end test that measures the complete container startup flow:
1. Sign in as a new user
2. Create a new project
3. Add a Next.js 16 container
4. Verify files are initialized
5. Start the container
6. Poll until HTTP 200 with valid HTML
7. Report timing for every phase
8. Cleanup (delete project, user)

This test identifies bottlenecks in the container startup process.

Usage:
    # Set required environment variables
    export BASE_URL=https://your-domain.com
    export TEST_USER_EMAIL=timing-test@example.com
    export TEST_USER_PASSWORD=YourSecurePassword123

    # Run the test
    pytest orchestrator/tests/k8s/test_container_startup_timing.py -v -s

    # Skip cleanup for debugging
    export CLEANUP_ENABLED=false
    pytest orchestrator/tests/k8s/test_container_startup_timing.py -v -s
"""

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from .timing_observer import HttpProbeResult


class TestContainerStartupTiming:
    """End-to-end test for container startup timing."""

    @pytest.fixture(autouse=True)
    def setup(self, timing_observer):
        """Initialize test state."""
        self.observer = timing_observer
        self.auth_token: str | None = None
        self.user_id: str | None = None
        self.project_slug: str | None = None
        self.project_id: str | None = None
        self.container_id: str | None = None
        self.container_url: str | None = None
        self.base_url: str | None = None

    async def _register_or_login_user(
        self, client: httpx.AsyncClient, base_url: str, email: str, password: str
    ) -> tuple[str, str]:
        """Register a new user or login if already exists."""
        self.observer.record("auth_start")

        # Try to register first
        try:
            register_response = await client.post(
                f"{base_url}/api/auth/register",
                json={
                    "email": email,
                    "password": password,
                    "name": "Timing Test User",
                },
            )

            if register_response.status_code == 201:
                self.observer.record("user_registered", {"email": email})
            elif register_response.status_code == 400:
                # User already exists, that's fine
                self.observer.record("user_exists", {"email": email})
        except Exception as e:
            self.observer.record("register_error", {"error": str(e)})

        # Login
        login_response = await client.post(
            f"{base_url}/api/auth/jwt/login",
            data={
                "username": email,
                "password": password,
            },
        )

        if login_response.status_code != 200:
            raise RuntimeError(
                f"Login failed: {login_response.status_code} - {login_response.text}"
            )

        token_data = login_response.json()
        token = token_data["access_token"]

        self.observer.record("auth_complete", {"token_length": len(token)})

        # Get user info
        me_response = await client.get(
            f"{base_url}/api/users/me", headers={"Authorization": f"Bearer {token}"}
        )

        if me_response.status_code != 200:
            raise RuntimeError(f"Failed to get user info: {me_response.text}")

        user_data = me_response.json()
        user_id = user_data["id"]

        return token, user_id

    async def _create_project(
        self, client: httpx.AsyncClient, base_url: str, token: str, base_id: str
    ) -> tuple[str, str]:
        """Create a new project from a marketplace base."""
        self.observer.record("project_creation_start")

        project_name = f"Timing Test {datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"

        response = await client.post(
            f"{base_url}/api/projects/",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": project_name,
                "description": "Container startup timing test project",
                "source_type": "base",
                "base_id": base_id,  # Create from marketplace base
            },
        )

        if response.status_code not in (200, 201, 202):
            raise RuntimeError(f"Project creation failed: {response.status_code} - {response.text}")

        data = response.json()
        project_slug = data["project"]["slug"]
        project_id = data["project"]["id"]
        task_id = data.get("task_id")

        self.observer.record("project_created_in_db", {"slug": project_slug, "task_id": task_id})

        # Poll task status until complete
        if task_id:
            await self._wait_for_task(client, base_url, token, task_id, "project_setup")

        self.observer.record("project_setup_complete", {"slug": project_slug})

        return project_slug, project_id

    async def _get_nextjs_base_id(
        self, client: httpx.AsyncClient, base_url: str, token: str, base_slug: str
    ) -> str:
        """Get the Next.js 16 base ID from marketplace."""
        self.observer.record("marketplace_lookup_start")

        # Get all bases
        response = await client.get(
            f"{base_url}/api/marketplace/bases", headers={"Authorization": f"Bearer {token}"}
        )

        if response.status_code != 200:
            raise RuntimeError(f"Failed to get marketplace bases: {response.text}")

        data = response.json()
        # API returns {"bases": [...]} structure
        bases = data.get("bases", data) if isinstance(data, dict) else data

        # Find the next.js base
        nextjs_base = None
        for base in bases:
            if base.get("slug") == base_slug:
                nextjs_base = base
                break

        if not nextjs_base:
            # Try to find any Next.js base
            for base in bases:
                if "next" in base.get("slug", "").lower() or "next" in base.get("name", "").lower():
                    nextjs_base = base
                    break

        if not nextjs_base:
            available_slugs = [b.get("slug") for b in bases[:10]]
            raise RuntimeError(
                f"Next.js base '{base_slug}' not found. Available: {available_slugs}"
            )

        self.observer.record(
            "marketplace_lookup_complete",
            {"base_slug": nextjs_base["slug"], "base_id": nextjs_base["id"]},
        )

        return nextjs_base["id"]

    async def _add_container(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        token: str,
        project_slug: str,
        project_id: str,
        base_id: str,
    ) -> str:
        """Add a Next.js container to the project."""
        self.observer.record("container_add_start")

        response = await client.post(
            f"{base_url}/api/projects/{project_slug}/containers",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": "Next.js 16",
                "project_id": project_id,
                "base_id": base_id,
                "container_type": "base",
                "position_x": 100,
                "position_y": 100,
            },
        )

        if response.status_code not in (200, 201, 202):
            raise RuntimeError(f"Container add failed: {response.status_code} - {response.text}")

        data = response.json()
        container_id = data["container"]["id"]
        task_id = data.get("task_id")

        self.observer.record(
            "container_added_to_db", {"container_id": container_id, "task_id": task_id}
        )

        # Wait for file initialization task
        if task_id:
            await self._wait_for_task(client, base_url, token, task_id, "container_file_init")

        self.observer.record("container_files_initialized")

        return container_id

    async def _start_container(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        token: str,
        project_slug: str,
        container_id: str,
    ) -> str:
        """Start the container and return its URL."""
        self.observer.record("container_start_request")

        response = await client.post(
            f"{base_url}/api/projects/{project_slug}/containers/{container_id}/start",
            headers={"Authorization": f"Bearer {token}"},
        )

        if response.status_code != 202:
            raise RuntimeError(f"Container start failed: {response.status_code} - {response.text}")

        data = response.json()
        task_id = data["task_id"]

        self.observer.record("container_start_task_created", {"task_id": task_id})

        # Wait for container startup with detailed phase tracking and get task result
        task_result = await self._wait_for_task_with_phases(
            client, base_url, token, task_id, "container_startup"
        )

        self.observer.record("container_k8s_ready")

        # Get URL from task result
        container_url = None
        if task_result and isinstance(task_result, dict):
            container_url = task_result.get("url")
            if not container_url:
                # Try nested result
                nested_result = task_result.get("result", {})
                if isinstance(nested_result, dict):
                    container_url = nested_result.get("url")

        # Fallback: try container endpoint
        if not container_url:
            status_response = await client.get(
                f"{base_url}/api/projects/{project_slug}/containers/{container_id}",
                headers={"Authorization": f"Bearer {token}"},
            )

            if status_response.status_code == 200:
                container_data = status_response.json()
                container_url = container_data.get("url")

                # Try to construct URL from directory or name
                if not container_url:
                    container_dir = (
                        container_data.get("directory")
                        or container_data.get("directory_name")
                        or container_data.get("name")
                    )
                    if container_dir:
                        # Normalize directory name for URL
                        container_dir = (
                            container_dir.lower()
                            .replace(" ", "-")
                            .replace("_", "-")
                            .replace(".", "-")
                        )
                        container_url = (
                            f"https://{container_dir}.{project_slug}.studio.your-domain.com"
                        )

        # Final fallback: use container name
        if not container_url:
            container_url = f"https://next-js-15.{project_slug}.studio.your-domain.com"

        self.observer.record("container_url_retrieved", {"url": container_url})

        return container_url

    async def _wait_for_task(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        token: str,
        task_id: str,
        phase_prefix: str,
        timeout: int = 600,
    ):
        """Wait for a task to complete, recording progress."""
        start = time.time()
        last_progress = -1

        while time.time() - start < timeout:
            response = await client.get(
                f"{base_url}/api/tasks/{task_id}/status",
                headers={"Authorization": f"Bearer {token}"},
            )

            if response.status_code != 200:
                await asyncio.sleep(1)
                continue

            task_data = response.json()
            status = task_data.get("status")
            progress = task_data.get("progress", {})

            current_progress = progress.get("percentage", 0)
            if current_progress != last_progress and current_progress > 0:
                self.observer.record(
                    f"{phase_prefix}_progress_{current_progress}",
                    {"message": progress.get("message", ""), "status": status},
                )
                last_progress = current_progress

            if status == "completed":
                return
            elif status == "failed":
                error = task_data.get("error") or task_data.get("result", {}).get("error")
                raise RuntimeError(f"Task {task_id} failed: {error}")

            await asyncio.sleep(0.5)

        raise TimeoutError(f"Task {task_id} did not complete within {timeout}s")

    async def _wait_for_task_with_phases(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        token: str,
        task_id: str,
        phase_prefix: str,
        timeout: int = 600,
    ) -> dict[str, Any] | None:
        """Wait for container startup task, recording K8s phases from logs.

        Returns the task result dict on completion.
        """
        start = time.time()
        seen_phases = set()

        while time.time() - start < timeout:
            response = await client.get(
                f"{base_url}/api/tasks/{task_id}/status",
                headers={"Authorization": f"Bearer {token}"},
            )

            if response.status_code != 200:
                await asyncio.sleep(0.5)
                continue

            task_data = response.json()
            status = task_data.get("status")
            progress = task_data.get("progress", {})
            logs = task_data.get("logs", [])
            result = task_data.get("result", {})

            # Extract phase from progress message
            phase_message = progress.get("message", "")
            if phase_message and phase_message not in seen_phases:
                seen_phases.add(phase_message)
                self.observer.record(
                    "k8s_phase",
                    {"message": phase_message, "progress_pct": progress.get("percentage", 0)},
                )

            # Parse logs for timing info
            for log in logs:
                log_lower = log.lower()

                if "creating namespace" in log_lower and "namespace_create" not in seen_phases:
                    seen_phases.add("namespace_create")
                    self.observer.record("k8s_namespace_create")

                elif "networkpolicy" in log_lower and "network_policy" not in seen_phases:
                    seen_phases.add("network_policy")
                    self.observer.record("k8s_network_policy")

                elif "pvc" in log_lower and "pvc_create" not in seen_phases:
                    seen_phases.add("pvc_create")
                    self.observer.record("k8s_pvc_create")

                elif "git clone" in log_lower and "git_clone" not in seen_phases:
                    seen_phases.add("git_clone")
                    self.observer.record("k8s_git_clone")

                elif "deployment" in log_lower and "deployment_create" not in seen_phases:
                    seen_phases.add("deployment_create")
                    self.observer.record("k8s_deployment_create")

                elif "npm install" in log_lower and "npm_install" not in seen_phases:
                    seen_phases.add("npm_install")
                    self.observer.record("k8s_npm_install")

                elif "service" in log_lower and "service_create" not in seen_phases:
                    seen_phases.add("service_create")
                    self.observer.record("k8s_service_create")

                elif "ingress" in log_lower and "ingress_create" not in seen_phases:
                    seen_phases.add("ingress_create")
                    self.observer.record("k8s_ingress_create")

            if status == "completed":
                # Return the result containing URL and other info
                return result if result else task_data
            elif status == "failed":
                error = task_data.get("error") or result.get("error")
                raise RuntimeError(f"Task {task_id} failed: {error}")

            await asyncio.sleep(0.5)

        raise TimeoutError(f"Task {task_id} did not complete within {timeout}s")

    async def _poll_container_url(
        self, client: httpx.AsyncClient, url: str, timeout: int = 180
    ) -> bool:
        """Poll the container URL until it returns valid Next.js HTML."""
        if not url:
            self.observer.record("http_polling_skipped", {"reason": "no url"})
            return False

        self.observer.record("http_polling_start", {"url": url})

        start = time.time()
        poll_count = 0

        while time.time() - start < timeout:
            poll_count += 1
            probe_start = time.time()

            try:
                response = await client.get(url, timeout=10.0)

                probe_time = (time.time() - probe_start) * 1000
                content_type = response.headers.get("content-type", "")
                body = response.text[:2000] if response.status_code == 200 else ""

                # Check for Next.js markers
                is_html = "text/html" in content_type
                has_next_markers = any(
                    [
                        "__NEXT_DATA__" in body,
                        "next/dist" in body,
                        "_next/static" in body,
                        "<!DOCTYPE html>" in body and "Next" in body,
                        "next-size-adjust" in body,
                    ]
                )

                result = HttpProbeResult(
                    timestamp=datetime.now(UTC),
                    status_code=response.status_code,
                    response_time_ms=probe_time,
                    is_html=is_html,
                    has_next_js_markers=has_next_markers,
                )
                self.observer.record_http_probe(result)

                if response.status_code == 200 and has_next_markers:
                    self.observer.record(
                        "first_successful_html",
                        {"poll_count": poll_count, "response_time_ms": probe_time},
                    )
                    return True

                # Log significant error responses (but not every poll)
                if poll_count % 5 == 1 and response.status_code in (
                    404,
                    502,
                    503,
                ):  # Log every 5th poll
                    self.observer.record(f"http_{response.status_code}", {"poll_count": poll_count})

            except Exception as e:
                result = HttpProbeResult(
                    timestamp=datetime.now(UTC),
                    status_code=0,
                    response_time_ms=(time.time() - probe_start) * 1000,
                    error=str(e),
                )
                self.observer.record_http_probe(result)

            await asyncio.sleep(2)

        self.observer.record("http_polling_timeout", {"poll_count": poll_count})
        return False

    async def _cleanup(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        token: str,
        project_slug: str | None,
        user_id: str | None,
        cleanup_enabled: bool,
    ):
        """Clean up test resources."""
        if not cleanup_enabled:
            self.observer.record("cleanup_skipped")
            return

        self.observer.record("cleanup_start")

        # Delete project (cascades to K8s namespace)
        if project_slug and token:
            try:
                response = await client.delete(
                    f"{base_url}/api/projects/{project_slug}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                self.observer.record(
                    "project_deleted", {"slug": project_slug, "status": response.status_code}
                )
            except Exception as e:
                self.observer.record("cleanup_project_error", {"error": str(e)})

        # Delete user - try different endpoints
        if user_id and token:
            try:
                # Try admin delete endpoint
                response = await client.delete(
                    f"{base_url}/api/users/{user_id}", headers={"Authorization": f"Bearer {token}"}
                )
                if response.status_code in (200, 204):
                    self.observer.record("user_deleted", {"user_id": user_id})
                else:
                    self.observer.record(
                        "user_delete_skipped",
                        {
                            "user_id": user_id,
                            "status": response.status_code,
                            "reason": "endpoint may require admin",
                        },
                    )
            except Exception as e:
                self.observer.record("cleanup_user_error", {"error": str(e)})

        self.observer.record("cleanup_complete")

    @pytest.mark.asyncio
    @pytest.mark.kubernetes
    @pytest.mark.e2e
    @pytest.mark.slow
    async def test_nextjs_container_startup_timing(
        self,
        http_client: httpx.AsyncClient,
        base_url: str,
        test_user_email: str,
        test_user_password: str,
        nextjs_base_slug: str,
        cleanup_enabled: bool,
        test_timeout: int,
    ):
        """
        Full end-to-end test measuring container startup timing.

        This test:
        1. Registers/logs in as a test user
        2. Creates a new project
        3. Finds the Next.js 16 base in marketplace
        4. Adds a Next.js 16 container
        5. Starts the container
        6. Polls until port 3000 returns valid HTML
        7. Reports timing metrics for each phase
        8. Cleans up resources
        """
        self.base_url = base_url
        self.observer.start()

        try:
            # Phase 1: Authentication
            print(f"\n[TEST] Authenticating as {test_user_email}...")
            self.auth_token, self.user_id = await self._register_or_login_user(
                http_client, base_url, test_user_email, test_user_password
            )
            print(f"[TEST] Authenticated. User ID: {self.user_id}")

            # Phase 2: Get Next.js Base ID (needed for project creation)
            print(f"[TEST] Looking up {nextjs_base_slug} base...")
            base_id = await self._get_nextjs_base_id(
                http_client, base_url, self.auth_token, nextjs_base_slug
            )
            print(f"[TEST] Found base ID: {base_id}")

            # Phase 3: Create Project from base
            print("[TEST] Creating project from base...")
            self.project_slug, self.project_id = await self._create_project(
                http_client, base_url, self.auth_token, base_id
            )
            print(f"[TEST] Project created: {self.project_slug}")

            # Phase 4: Add Container
            print("[TEST] Adding Next.js container...")
            self.container_id = await self._add_container(
                http_client, base_url, self.auth_token, self.project_slug, self.project_id, base_id
            )
            print(f"[TEST] Container added: {self.container_id}")

            # Phase 5: Start Container
            print("[TEST] Starting container...")
            self.container_url = await self._start_container(
                http_client, base_url, self.auth_token, self.project_slug, self.container_id
            )
            print(f"[TEST] Container started. URL: {self.container_url}")

            # Phase 6: Poll for HTML
            print("[TEST] Polling for HTML response...")
            success = await self._poll_container_url(http_client, self.container_url, timeout=180)

            self.observer.record("test_complete", {"success": success})

            # Generate and print report
            self.observer.print_report()

            # Also print slowest phases
            print("\nTop 5 Slowest Phases:")
            print("-" * 40)
            for phase in self.observer.get_slowest_phases(5):
                duration_ms = phase["duration_ms"]
                print(f"  {phase['phase']}: {duration_ms:.0f}ms")

            if not success:
                print("\n[WARNING] Container did not return valid HTML within timeout")
                print("Check the error counts in the report above for 404/502 patterns")

            # Test assertion
            assert success, "Container did not return valid Next.js HTML within timeout"

        finally:
            print("\n[TEST] Cleaning up...")
            await self._cleanup(
                http_client,
                base_url,
                self.auth_token,
                self.project_slug,
                self.user_id,
                cleanup_enabled,
            )
            print("[TEST] Done.")
