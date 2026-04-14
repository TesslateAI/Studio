"""Unit tests for public K8s projects router helpers."""
from __future__ import annotations

import app.models  # noqa: F401
from app.routers.public.k8s_projects import _lifecycle_payload


def test_lifecycle_payload_maps_orchestrator_result():
    payload = _lifecycle_payload(
        "proj-slug",
        {
            "status": "running",
            "containers": {"web": "http://web.localhost"},
            "namespace": "proj-abc",
        },
    )
    assert payload == {
        "project_slug": "proj-slug",
        "status": "running",
        "containers": {"web": "http://web.localhost"},
        "namespace": "proj-abc",
    }


def test_lifecycle_payload_defaults_when_missing_fields():
    payload = _lifecycle_payload("proj-slug", {})
    assert payload["status"] == "unknown"
    assert payload["containers"] == {}
    assert payload["namespace"] is None
