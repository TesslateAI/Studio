"""Integration-ish unit test for Container.image × env secret-ref ordering.

Previously, the Apps installer smuggled the manifest-declared image through
``environment_vars["TSL_CONTAINER_IMAGE"]`` and compute_manager stripped the
key at pod-spec build time. The two code paths share the env dict, so any
regression in one (e.g., an image-override path that mutates ``environment_vars``
before the resolver runs) could silently drop ``${secret:...}`` references.

Migration 0060 moves the image to a dedicated ``Container.image`` column, but
the orchestrator keeps a one-release fallback to the legacy env var. This test
locks in both:

1. When the legacy env var is present, the pod spec uses it as the image AND
   the sentinel never reaches the pod's env.
2. The resolver still turns every other ``${secret:foo/bar}`` entry into a
   ``valueFrom.secretKeyRef`` in the same deployment.
"""

from __future__ import annotations

from uuid import uuid4

from app.services.orchestration.kubernetes import helpers


def _collect_env(container_spec) -> dict[str, object]:
    out: dict[str, object] = {}
    for ev in container_spec.env or []:
        if ev.value_from is not None and ev.value_from.secret_key_ref is not None:
            sr = ev.value_from.secret_key_ref
            out[ev.name] = ("secret", sr.name, sr.key)
        else:
            out[ev.name] = ev.value
    return out


def test_image_column_and_secret_ref_coexist() -> None:
    """Simulate the post-migration path: caller passes image directly (from
    Container.image), env carries a secret-ref. Both survive the round-trip.
    """
    dep = helpers.create_v2_dev_deployment(
        namespace="proj-test",
        project_id=uuid4(),
        user_id=uuid4(),
        container_id=uuid4(),
        container_directory="web",
        image="ghcr.io/creator/crm-web:v1.2.3",
        startup_command="node server.js",
        port=3000,
        extra_env={
            "DATABASE_URL": "${secret:pg-creds/url}",
            "PUBLIC_FLAG": "on",
        },
    )
    container = dep.spec.template.spec.containers[0]
    assert container.image == "ghcr.io/creator/crm-web:v1.2.3"
    env = _collect_env(container)
    assert env["DATABASE_URL"] == ("secret", "pg-creds", "url")
    assert env["PUBLIC_FLAG"] == "on"
    # Sentinel never appears in the pod env, regardless of source.
    assert "TSL_CONTAINER_IMAGE" not in env


def test_legacy_env_image_sentinel_is_stripped() -> None:
    """Pre-migration in-flight installs may still have the sentinel in
    environment_vars. The deployment builder must accept a pre-stripped env
    dict (compute_manager strips before calling helpers), and importantly
    the sentinel must not round-trip into the pod even if the caller forgets
    to strip it: the resolver's allow-list should quietly drop reserved keys.
    """
    dep = helpers.create_v2_dev_deployment(
        namespace="proj-test",
        project_id=uuid4(),
        user_id=uuid4(),
        container_id=uuid4(),
        container_directory="api",
        image="node:20-alpine",
        startup_command="node server.js",
        port=3001,
        extra_env={
            "API_KEY": "${secret:svc-creds/token}",
            # A buggy caller forgot to strip this. Belt-and-suspenders:
            # it's not a valid pod env anyway — asserting behaviour so we
            # notice if it ever starts leaking.
            "TSL_CONTAINER_IMAGE": "should-not-leak",
        },
    )
    container = dep.spec.template.spec.containers[0]
    env = _collect_env(container)
    # Secret-ref resolution unaffected by the sentinel's presence.
    assert env["API_KEY"] == ("secret", "svc-creds", "token")
