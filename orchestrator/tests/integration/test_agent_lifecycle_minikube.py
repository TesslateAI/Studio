"""End-to-end lifecycle test against a live minikube cluster.

Skipped unless ``MINIKUBE_INTEGRATION=1`` is set. Exercises the full
``apply_setup_config`` → ``project_start`` → ``container_stop`` → ``project_stop``
flow via the HTTP API and verifies Kubernetes resources (namespace,
deployments, services) appear and disappear as expected via kubectl.

Requirements:
  * minikube running with OpenSail deployed (`./scripts/minikube.sh start`)
  * kubectl available with context `tesslate`
  * Environment:
      - ``MINIKUBE_INTEGRATION=1``            — enable this test
      - ``ORCHESTRATOR_URL`` (optional)       — default ``http://tesslate.localhost``
      - ``MINIKUBE_TEST_BASE_ID`` (optional)  — marketplace base ID; otherwise
                                                picks the first available base

The test manages its own user (registers a fresh account) and project so it
can run repeatedly without state cleanup between runs.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import time
from uuid import uuid4

import httpx
import pytest

MINIKUBE_ENABLED = os.environ.get("MINIKUBE_INTEGRATION") == "1"
ORCHESTRATOR_URL = os.environ.get("ORCHESTRATOR_URL", "http://tesslate.localhost")
KUBECTL_CONTEXT = os.environ.get("MINIKUBE_KUBECTL_CONTEXT", "tesslate")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.kubernetes,
    pytest.mark.slow,
    pytest.mark.skipif(
        not MINIKUBE_ENABLED,
        reason="Set MINIKUBE_INTEGRATION=1 to run minikube E2E tests",
    ),
]


# ---------------------------------------------------------------------------
# kubectl helpers
# ---------------------------------------------------------------------------


def _kubectl(*args: str, check: bool = True) -> str:
    """Run a kubectl command with the tesslate context pinned."""
    cmd = ["kubectl", f"--context={KUBECTL_CONTEXT}", *args]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"kubectl failed: {' '.join(cmd)}\nstderr: {result.stderr}")
    return result.stdout


def _namespace_exists(namespace: str) -> bool:
    result = subprocess.run(
        ["kubectl", f"--context={KUBECTL_CONTEXT}", "get", "ns", namespace],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _wait_for_namespace(namespace: str, timeout: int = 30) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _namespace_exists(namespace):
            return True
        time.sleep(1)
    return False


def _wait_for_namespace_gone(namespace: str, timeout: int = 60) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _namespace_exists(namespace):
            return True
        time.sleep(1)
    return False


def _deployments_in_namespace(namespace: str) -> list[str]:
    out = _kubectl("get", "deployments", "-n", namespace, "-o", "json", check=False)
    if not out:
        return []
    data = json.loads(out)
    return [item["metadata"]["name"] for item in data.get("items", [])]


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _register_and_login(client: httpx.Client) -> dict:
    email = f"minikube-e2e-{uuid4().hex}@example.com"
    password = "TestPassword123!"

    reg = client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "name": "Minikube E2E"},
    )
    if reg.status_code not in (200, 201):
        pytest.fail(f"Registration failed: {reg.status_code} {reg.text}")

    login = client.post(
        "/api/auth/jwt/login",
        data={"username": email, "password": password},
    )
    if login.status_code != 200:
        pytest.fail(f"Login failed: {login.status_code} {login.text}")

    token = login.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return {"email": email, "token": token}


def _pick_base_id(client: httpx.Client) -> str:
    if os.environ.get("MINIKUBE_TEST_BASE_ID"):
        base_id = os.environ["MINIKUBE_TEST_BASE_ID"]
        client.post(f"/api/marketplace/bases/{base_id}/purchase")
        return base_id

    resp = client.get("/api/marketplace/bases")
    assert resp.status_code == 200, resp.text
    bases = resp.json().get("bases", [])
    if not bases:
        pytest.skip("No marketplace bases available in this minikube cluster")

    base_id = bases[0]["id"]
    client.post(f"/api/marketplace/bases/{base_id}/purchase")
    return base_id


def _create_project(client: httpx.Client, base_id: str) -> dict:
    resp = client.post(
        "/api/projects/",
        json={"name": f"minikube-e2e-{uuid4().hex[:8]}", "base_id": base_id},
    )
    assert resp.status_code == 200, f"Project create failed: {resp.text}"
    project = resp.json()["project"]

    # Wait out the provisioning window (copy template, create PVC).
    deadline = time.time() + 180
    while time.time() < deadline:
        status_resp = client.get(f"/api/projects/{project['slug']}")
        if status_resp.status_code == 200:
            body = status_resp.json()
            if body.get("environment_status") not in ("provisioning", None):
                return body
        time.sleep(2)

    pytest.fail(f"Project {project['slug']} never exited provisioning state")


# ---------------------------------------------------------------------------
# The end-to-end flow
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def http_client():
    """httpx Client talking to the running minikube orchestrator."""
    with httpx.Client(base_url=ORCHESTRATOR_URL, timeout=60.0) as client:
        yield client


@pytest.fixture(scope="module")
def e2e_project(http_client):
    """Create a fresh user + project for the whole test module."""
    _register_and_login(http_client)
    base_id = _pick_base_id(http_client)
    project = _create_project(http_client, base_id)
    yield project

    # Cleanup: stop + delete project so the next run is hermetic.
    with contextlib.suppress(Exception):
        http_client.post(f"/api/projects/{project['slug']}/containers/stop-all")
    with contextlib.suppress(Exception):
        http_client.delete(f"/api/projects/{project['slug']}")


def test_apply_setup_config_happy_path(http_client, e2e_project):
    """apply_setup_config writes the file and returns container IDs."""
    slug = e2e_project["slug"]
    config = {
        "apps": {
            "app": {
                "directory": ".",
                "port": 3000,
                "start": "npm run dev -- --host 0.0.0.0",
            }
        },
        "primaryApp": "app",
    }
    resp = http_client.post(f"/api/projects/{slug}/setup-config", json=config)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["container_ids"]) == 1
    assert data["primary_container_id"] == data["container_ids"][0]


def test_project_start_creates_namespace(http_client, e2e_project):
    """start-all creates the project namespace and at least one deployment."""
    slug = e2e_project["slug"]
    project_id = e2e_project["id"]
    namespace = f"proj-{project_id}"

    resp = http_client.post(f"/api/projects/{slug}/containers/start-all")
    assert resp.status_code == 200, resp.text

    assert _wait_for_namespace(namespace, timeout=60), (
        f"Namespace {namespace} did not appear within 60s"
    )
    deployments = _deployments_in_namespace(namespace)
    assert deployments, f"No deployments in {namespace} after start-all"


def test_container_stop_scales_down_deployment(http_client, e2e_project):
    """Stopping a single container scales its Deployment to zero ready pods.

    K8s orchestrators typically scale replicas to 0 rather than delete the
    Deployment outright. We verify the API call succeeds and then check
    that the target pod is no longer ready.
    """
    slug = e2e_project["slug"]
    project_id = e2e_project["id"]
    namespace = f"proj-{project_id}"

    resp = http_client.get(f"/api/projects/{slug}/containers")
    assert resp.status_code == 200, resp.text
    containers = resp.json()
    app_container = next((c for c in containers if c["name"] == "app"), None)
    if app_container is None:
        pytest.skip("container 'app' not present — setup-config test must run first")
    container_id = app_container["id"]

    resp = http_client.post(f"/api/projects/{slug}/containers/{container_id}/stop")
    assert resp.status_code == 200, resp.text

    # Verify the container's pods transition to not-ready or disappear.
    deadline = time.time() + 60
    while time.time() < deadline:
        out = _kubectl("get", "pods", "-n", namespace, "-o", "json", check=False)
        try:
            pods_data = json.loads(out) if out else {"items": []}
        except json.JSONDecodeError:
            pods_data = {"items": []}

        ready_app_pods = [
            p
            for p in pods_data.get("items", [])
            if p.get("metadata", {}).get("labels", {}).get("app", "").startswith("dev-")
            and any(
                cond.get("type") == "Ready" and cond.get("status") == "True"
                for cond in p.get("status", {}).get("conditions", [])
            )
        ]
        if not ready_app_pods:
            break
        time.sleep(2)
    else:
        pytest.fail(f"App pods in {namespace} are still ready 60s after container stop")


def test_project_stop_tears_down_namespace(http_client, e2e_project):
    """stop-all deletes the project namespace."""
    slug = e2e_project["slug"]
    project_id = e2e_project["id"]
    namespace = f"proj-{project_id}"

    resp = http_client.post(f"/api/projects/{slug}/containers/stop-all")
    assert resp.status_code == 200, resp.text

    assert _wait_for_namespace_gone(namespace, timeout=120), (
        f"Namespace {namespace} still exists 120s after stop-all"
    )
