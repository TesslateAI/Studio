"""End-to-end smoke test for seed apps published by `scripts/seed_apps.py`.

Walks ``seeds/apps/registry.py:SEED_APPS`` and, for each app, drives the
full install → wait-for-running → hit-primary-url flow through the HTTP
API. Headless apps (``compute.model == "job-only"`` with ``schedules`` and
no ``surfaces``) skip the URL check and instead assert the expected
``AgentSchedule`` row was materialized by the installer.

This test is integration-only and is skipped unless
``MINIKUBE_INTEGRATION=1`` is set. It requires:

* A running orchestrator reachable at ``ORCHESTRATOR_URL`` (default
  ``http://localhost`` when run via the minikube tunnel).
* Seed apps already published to the cluster
  (``kubectl -n tesslate exec deploy/tesslate-backend -- env
  TSL_APPS_DEV_AUTO_APPROVE=1 python -m scripts.seed_apps``).
* ``kubectl`` in ``PATH`` with the ``tesslate`` context (overridable via
  ``MINIKUBE_KUBECTL_CONTEXT``) — used to dump pod logs on failure.

Test artifacts
--------------
On failure, pod logs for every pod in the project namespace are written
to ``{pytest_tmpdir}/seed-apps-logs/<slug>-<ts>/`` and reported via
``request.node.add_report_section`` so they survive into pytest's output
and CI artifact collection.

Fail-fast behaviour
-------------------
Each seed app is its own ``pytest.param``; a failure in one app does not
short-circuit the rest, but readiness timeouts hard-fail that app rather
than hanging forever. The timeout is ``SEED_APP_READINESS_TIMEOUT`` (default
``settings.k8s_readiness_probe_timeout`` = 600s per the issue).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest

# ---------------------------------------------------------------------------
# Registry resolution — ``seeds/apps/registry.py`` lives at the repo root,
# which isn't on ``sys.path`` by default when running under the orchestrator
# test suite. Path hop mirrors ``scripts/seed_apps.py``.
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from seeds.apps.registry import SEED_APPS, SeedApp  # noqa: E402

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MINIKUBE_ENABLED = os.environ.get("MINIKUBE_INTEGRATION") == "1"
ORCHESTRATOR_URL = os.environ.get("ORCHESTRATOR_URL", "http://localhost")
KUBECTL_CONTEXT = os.environ.get("MINIKUBE_KUBECTL_CONTEXT", "tesslate")
READINESS_TIMEOUT = int(os.environ.get("SEED_APP_READINESS_TIMEOUT", "600"))
INSTALL_POLL_INTERVAL = 2.0

pytestmark = [
    pytest.mark.integration,
    pytest.mark.kubernetes,
    pytest.mark.slow,
    pytest.mark.skipif(
        not MINIKUBE_ENABLED,
        reason="Set MINIKUBE_INTEGRATION=1 to run seed-app E2E tests",
    ),
]


# ---------------------------------------------------------------------------
# Manifest introspection — the registry doesn't carry manifest metadata so
# we read the raw JSON alongside the asset dir to decide whether an app has
# surfaces (GUI) vs. schedules (headless).
# ---------------------------------------------------------------------------


def _load_manifest(app: SeedApp) -> dict[str, Any]:
    path = app.assets_dir / app.manifest_filename
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _is_headless(manifest: dict[str, Any]) -> bool:
    surfaces = manifest.get("surfaces") or []
    schedules = manifest.get("schedules") or []
    compute = manifest.get("compute") or {}
    job_only = (compute.get("model") or "").lower() in {"job-only", "job_only"}
    return job_only or (not surfaces and bool(schedules))


def _surface_entrypoints(manifest: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for s in manifest.get("surfaces") or []:
        if not isinstance(s, dict):
            continue
        entrypoint = s.get("entrypoint") or "/"
        out.append(entrypoint)
    return out


def _schedule_names(manifest: dict[str, Any]) -> list[str]:
    return [
        s.get("name")
        for s in (manifest.get("schedules") or [])
        if isinstance(s, dict) and s.get("name")
    ]


# ---------------------------------------------------------------------------
# kubectl helper — only used for log collection on failure.
# ---------------------------------------------------------------------------


def _kubectl(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    cmd = ["kubectl", f"--context={KUBECTL_CONTEXT}", *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def _dump_namespace_logs(namespace: str, out_dir: Path) -> None:
    """Write pod logs for every pod in ``namespace`` under ``out_dir``.

    Best-effort: log collection never raises. The caller wires the dir
    into the pytest report so it's discoverable even when CI stashes the
    whole ``tmp_path`` as an artifact.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    pods_res = _kubectl("get", "pods", "-n", namespace, "-o", "json")
    if pods_res.returncode != 0:
        (out_dir / "_kubectl-error.txt").write_text(
            f"kubectl get pods failed: {pods_res.stderr}", encoding="utf-8"
        )
        return
    try:
        pods = json.loads(pods_res.stdout or "{}").get("items") or []
    except json.JSONDecodeError:
        pods = []
    for pod in pods:
        name = pod.get("metadata", {}).get("name")
        if not name:
            continue
        # Previous + current logs for every container (previous catches
        # CrashLoopBackOff where the "current" log is empty).
        for container in pod.get("spec", {}).get("containers", []) or [{}]:
            cname = container.get("name")
            suffix = f".{cname}" if cname else ""
            for label, extra in (("current", []), ("previous", ["--previous"])):
                args = ["logs", "-n", namespace, name]
                if cname:
                    args += ["-c", cname]
                args += extra
                res = _kubectl(*args)
                if res.returncode == 0 and res.stdout:
                    (out_dir / f"{name}{suffix}.{label}.log").write_text(
                        res.stdout, encoding="utf-8"
                    )


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _register_and_login(client: httpx.Client) -> dict:
    email = f"seedapps-e2e-{uuid4().hex[:8]}@example.com"
    password = "TestPassword123!"
    reg = client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "name": "Seed Apps E2E"},
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


def _default_team_id(client: httpx.Client) -> str:
    """Return the user's personal team id — required on every install call.

    ``GET /api/teams`` returns a bare JSON array (list of team dicts); some
    other list endpoints wrap in ``{items: [...]}``. Handle both so the
    test survives minor API shape evolution.
    """
    resp = client.get("/api/teams")
    assert resp.status_code == 200, f"list teams failed: {resp.text}"
    body = resp.json()
    teams = body if isinstance(body, list) else (body.get("teams") or body.get("items") or [])
    if not teams:
        pytest.fail("user has no teams — did /api/auth/register not seed a personal team?")
    personal = next((t for t in teams if t.get("is_personal")), None) or teams[0]
    return personal["id"]


def _find_app_by_slug(client: httpx.Client, slug: str) -> dict | None:
    resp = client.get("/api/marketplace-apps", params={"q": slug, "limit": 50})
    assert resp.status_code == 200, resp.text
    for item in resp.json().get("items") or []:
        if item.get("slug") == slug:
            return item
    return None


def _latest_version(client: httpx.Client, app_id: str) -> dict | None:
    resp = client.get(f"/api/marketplace-apps/{app_id}/versions", params={"limit": 1})
    if resp.status_code != 200:
        return None
    items = resp.json().get("items") or []
    return items[0] if items else None


def _install(
    client: httpx.Client,
    *,
    app_version_id: str,
    team_id: str,
    manifest: dict[str, Any],
) -> dict:
    """POST /install with a consent payload that matches the manifest billing."""
    billing = manifest.get("billing") or {}
    wallet_mix_consent = {
        dim: (cfg.get("payer") if isinstance(cfg, dict) else "platform")
        for dim, cfg in billing.items()
        if isinstance(cfg, dict) and dim in {"ai_compute", "general_compute"}
    }
    payload = {
        "app_version_id": app_version_id,
        "team_id": team_id,
        "wallet_mix_consent": wallet_mix_consent or {"ai_compute": "platform", "general_compute": "platform"},
        "mcp_consents": [],
        "update_policy": "manual",
    }
    resp = client.post("/api/app-installs/install", json=payload)
    assert resp.status_code in (200, 201), f"install failed: {resp.status_code} {resp.text}"
    return resp.json()


def _poll_install_ready(client: httpx.Client, app_instance_id: str, timeout: int) -> dict:
    deadline = time.time() + timeout
    last: dict | None = None
    while time.time() < deadline:
        resp = client.get(f"/api/app-installs/{app_instance_id}")
        if resp.status_code == 200:
            last = resp.json()
            if last.get("state") == "installed":
                # "installed" is the DB-level state; still need to check that
                # containers (if any) are reporting running.
                containers = last.get("containers") or []
                if not containers:
                    return last
                non_running = [
                    c for c in containers if (c.get("status") or "").lower() != "running"
                ]
                if not non_running:
                    return last
        time.sleep(INSTALL_POLL_INTERVAL)
    pytest.fail(
        f"app_instance {app_instance_id} did not reach running within {timeout}s "
        f"(last state={last.get('state') if last else 'unknown'})"
    )


def _primary_container_row(detail: dict) -> dict | None:
    pid = detail.get("primary_container_id")
    for c in detail.get("containers") or []:
        if c.get("id") == pid or c.get("is_primary"):
            return c
    return (detail.get("containers") or [None])[0]


def _build_surface_url(detail: dict, entrypoint: str) -> str:
    """Mirror services/apps/runtime_urls.container_url for the primary container."""
    project_slug = detail.get("project_slug")
    primary = _primary_container_row(detail)
    assert project_slug, "install detail missing project_slug"
    assert primary, "install detail has no primary container"
    dir_or_name = primary.get("directory") or primary.get("name")
    # ORCHESTRATOR_URL's host is our app_domain under the minikube tunnel
    # (localhost). Reconstruct with the per-container subdomain.
    url = httpx.URL(ORCHESTRATOR_URL)
    host = f"{project_slug}-{dir_or_name}.{url.host}"
    scheme = url.scheme or "http"
    port = f":{url.port}" if url.port and url.port not in (80, 443) else ""
    entrypoint = "/" + entrypoint.lstrip("/")
    return f"{scheme}://{host}{port}{entrypoint}"


def _uninstall(client: httpx.Client, app_instance_id: str) -> None:
    with httpx.Timeout(30.0):
        client.post(f"/api/app-installs/{app_instance_id}/uninstall")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def http_client():
    # follow_redirects=True absorbs the trailing-slash 307 from FastAPI's
    # routes. Per-request overrides for surface probes below set it back
    # to False so we can assert the actual upstream status.
    with httpx.Client(
        base_url=ORCHESTRATOR_URL, timeout=60.0, follow_redirects=True
    ) as client:
        _register_and_login(client)
        yield client


@pytest.fixture(scope="module")
def team_id(http_client) -> str:
    return _default_team_id(http_client)


# ---------------------------------------------------------------------------
# The parametrized smoke test
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "seed_app", SEED_APPS, ids=[a.slug for a in SEED_APPS]
)
def test_seed_app_install_to_primary_url(
    seed_app: SeedApp,
    http_client: httpx.Client,
    team_id: str,
    tmp_path_factory: pytest.TempPathFactory,
    request: pytest.FixtureRequest,
) -> None:
    manifest = _load_manifest(seed_app)
    headless = _is_headless(manifest)

    # 1. App + latest version must be published already.
    app_row = _find_app_by_slug(http_client, seed_app.slug)
    if app_row is None:
        pytest.fail(
            f"MarketplaceApp slug={seed_app.slug!r} not found — run "
            "`python -m scripts.seed_apps` in the backend pod first."
        )
    version_row = _latest_version(http_client, app_row["id"])
    if version_row is None:
        pytest.fail(f"No AppVersion for slug={seed_app.slug!r} — seeds incomplete.")

    # 2. Install.
    install_resp = _install(
        http_client,
        app_version_id=version_row["id"],
        team_id=team_id,
        manifest=manifest,
    )
    app_instance_id = install_resp["app_instance_id"]
    project_id = install_resp.get("project_id")
    namespace = f"proj-{project_id}" if project_id else None

    logs_dir = tmp_path_factory.mktemp(f"seed-apps-logs-{seed_app.slug}")

    try:
        # 3. Wait for ready (installed + containers running).
        detail = _poll_install_ready(
            http_client, app_instance_id, timeout=READINESS_TIMEOUT
        )

        if headless:
            # 4a. Headless: assert at least one schedule row materialized and
            # covers the manifest's declared schedule names. Full HMAC
            # webhook invocation is covered by test_webhook_rotation.py;
            # here we only assert the installer wired the row.
            expected_names = set(_schedule_names(manifest))
            got_names = {
                s.get("name")
                for s in (detail.get("schedules") or [])
                if s.get("name")
            }
            missing = expected_names - got_names
            assert not missing, (
                f"{seed_app.slug}: installer did not create schedules "
                f"for {sorted(missing)} (got {sorted(got_names)})"
            )
            return

        # 4b. GUI: HTTP-GET every surface entrypoint on the primary container.
        entrypoints = _surface_entrypoints(manifest) or ["/"]
        errors: list[str] = []
        for ep in entrypoints:
            url = _build_surface_url(detail, ep)
            try:
                with httpx.Client(timeout=30.0, follow_redirects=False) as surface:
                    resp = surface.get(url)
            except httpx.HTTPError as e:
                errors.append(f"{ep}: transport error {e!r}")
                continue
            if resp.status_code >= 400:
                errors.append(
                    f"{ep}: {resp.status_code} {resp.reason_phrase} "
                    f"(body head: {resp.text[:200]!r})"
                )
        assert not errors, f"{seed_app.slug}: surface probe failures — {errors}"

    except BaseException:
        # On any failure, capture pod logs for the project namespace so the
        # CI artifact job has something to diagnose with.
        if namespace:
            try:
                _dump_namespace_logs(namespace, logs_dir)
                request.node.add_report_section(
                    "call",
                    "pod-logs",
                    f"pod logs written to {logs_dir}",
                )
            except Exception:  # pragma: no cover
                logger.exception("pod log dump failed")
        raise
    finally:
        # Always try to uninstall so repeat runs are hermetic.
        try:
            _uninstall(http_client, app_instance_id)
        except Exception:
            logger.exception("uninstall failed for %s", seed_app.slug)
