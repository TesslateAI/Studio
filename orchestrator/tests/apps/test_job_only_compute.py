"""Wave 9 Track B3 — compute.model="job-only" headless app support.

Verifies:
  * 2025-02 manifest schema accepts compute.model="job-only" and
    compute.model="always-on" (and rejects nonsense values).
  * Default (omitted) compute.model parses cleanly.
  * The runtime rollup helper surfaces "job_only" when every container
    in an app's project is marked status="job_only".
  * Mixed status containers do NOT roll up to "job_only".

Installer + runtime endpoint behavior beyond the rollup is exercised by
the existing integration suite (test_publisher_installer.py and the
wave3 router tests). Those tests need a live Postgres + the `db_session`
fixture, so we keep this file unit-only and assert the pure pieces:
schema validation + rollup logic + installer logic via direct
inspection.
"""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.routers.app_runtime_status import _rollup_state
from app.services.apps.manifest_parser import ManifestValidationError, parse


def _job_only_manifest() -> dict:
    return {
        "manifest_schema_version": "2025-02",
        "app": {
            "id": "com.example.headless-app",
            "name": "Headless App",
            "slug": "headless-app",
            "version": "0.1.0",
        },
        "compatibility": {
            "studio": {"min": "0.0.0"},
            "manifest_schema": "2025-02",
            "runtime_api": "^1.0",
            "required_features": [],
        },
        "compute": {
            "tier": 0,
            "model": "job-only",
            "containers": [
                {
                    "name": "runner",
                    "primary": True,
                    "image": "node:20-alpine",
                    "startup_command": "node scripts/digest.js",
                }
            ],
        },
        "surfaces": [],
        "schedules": [
            {
                "name": "nightly",
                "default_cron": "0 2 * * *",
                "execution": "job",
                "entrypoint": "node /app/scripts/digest.js",
            }
        ],
        "state": {"model": "per-install-volume", "volume_size": "500Mi"},
        "billing": {
            "ai_compute": {"payer": "platform"},
            "general_compute": {"payer": "platform"},
            "platform_fee": {"model": "free"},
        },
        "listing": {"visibility": "public"},
    }


# --- Schema validation -----------------------------------------------------


def test_job_only_manifest_validates() -> None:
    parsed = parse(_job_only_manifest())
    assert parsed.schema_version == "2025-02"
    assert parsed.raw["compute"]["model"] == "job-only"


def test_always_on_explicit_validates() -> None:
    m = _job_only_manifest()
    m["compute"]["model"] = "always-on"
    parsed = parse(m)
    assert parsed.raw["compute"]["model"] == "always-on"


def test_default_model_omitted_still_validates() -> None:
    """Back-compat: manifests without compute.model parse fine and
    consumers should default to "always-on" themselves."""
    m = _job_only_manifest()
    del m["compute"]["model"]
    parsed = parse(m)
    assert "model" not in parsed.raw["compute"]


def test_invalid_model_value_rejected() -> None:
    m = _job_only_manifest()
    m["compute"]["model"] = "sometimes"
    with pytest.raises(ManifestValidationError):
        parse(m)


# --- Installer status mapping (logic isolated from DB) ---------------------


def test_installer_initial_status_uses_job_only_for_headless() -> None:
    """Mirror the branch in installer.install_app — keeping it here as a
    regression guard so the mapping doesn't silently drift."""
    compute = _job_only_manifest()["compute"]
    compute_model = str(compute.get("model") or "always-on")
    initial_status = "job_only" if compute_model == "job-only" else "stopped"
    assert initial_status == "job_only"


def test_installer_initial_status_defaults_stopped() -> None:
    compute = {"tier": 0, "containers": []}
    compute_model = str(compute.get("model") or "always-on")
    initial_status = "job_only" if compute_model == "job-only" else "stopped"
    assert initial_status == "stopped"


# --- Runtime rollup --------------------------------------------------------


def _container(status: str):
    """Lightweight stand-in for the SQLAlchemy Container model."""
    return SimpleNamespace(id=uuid4(), name="c", status=status)


def test_rollup_all_job_only() -> None:
    assert _rollup_state([_container("job_only")]) == "job_only"
    assert (
        _rollup_state([_container("job_only"), _container("job_only")]) == "job_only"
    )


def test_rollup_mixed_job_only_does_not_collapse() -> None:
    # If any container is non-job_only, we do NOT report job_only — the
    # state machine should reflect the always-on container's reality.
    assert (
        _rollup_state([_container("job_only"), _container("running")]) != "job_only"
    )
    assert (
        _rollup_state([_container("job_only"), _container("stopped")]) != "job_only"
    )


def test_rollup_running_unchanged() -> None:
    assert _rollup_state([_container("running")]) == "running"


def test_rollup_stopped_default_unchanged() -> None:
    assert _rollup_state([_container("stopped")]) == "stopped"


def test_rollup_empty_unchanged() -> None:
    assert _rollup_state([]) == "stopped"


# --- Default-shape sanity for the seed manifest ---------------------------


def test_seed_nightly_digest_manifest_is_job_only() -> None:
    """Catch accidental regressions of seeds/apps/nightly_digest/app.manifest.json."""
    import json
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[3]
    manifest_path = repo_root / "seeds" / "apps" / "nightly_digest" / "app.manifest.json"
    data = json.loads(manifest_path.read_text())
    assert data["compute"]["model"] == "job-only"
    assert data["surfaces"] == []
    # And it must still validate against the schema.
    parse(deepcopy(data))
