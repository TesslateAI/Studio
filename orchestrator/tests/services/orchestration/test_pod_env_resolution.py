"""Verify that pod-spec builders route Container env through env_resolver,
so ``${secret:...}`` references become ``valueFrom.secretKeyRef`` (not
plaintext values leaked into Deployment manifests).
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


def test_v2_dev_deployment_resolves_secret_refs() -> None:
    dep = helpers.create_v2_dev_deployment(
        namespace="proj-test",
        project_id=uuid4(),
        user_id=uuid4(),
        container_id=uuid4(),
        container_directory="web",
        image="node:20-alpine",
        startup_command="npm run dev",
        port=3000,
        extra_env={
            "PLAIN": "keep-me",
            "API_KEY": "${secret:llama-creds/api_key}",
            "HOST": "should-be-dropped",  # reserved
        },
    )
    # First container in spec is the dev container.
    c = dep.spec.template.spec.containers[0]
    env = _collect_env(c)
    assert env["PLAIN"] == "keep-me"
    assert env["API_KEY"] == ("secret", "llama-creds", "api_key")
    # HOST is reserved — the builder-supplied value wins, not the user's.
    assert env.get("HOST") == "0.0.0.0"


def test_v2_service_deployment_uses_resolver_for_env() -> None:
    dep = helpers.create_v2_service_deployment(
        namespace="proj-test",
        project_id=uuid4(),
        user_id=uuid4(),
        container_id=uuid4(),
        container_directory="db",
        image="postgres:16",
        port=5432,
        environment_vars={
            "POSTGRES_USER": "app",
            "POSTGRES_PASSWORD": "${secret:pg-creds/password}",
        },
        volumes=["/var/lib/postgresql/data"],
        service_pvc_name="svc-db-pvc",
    )
    c = dep.spec.template.spec.containers[0]
    env = _collect_env(c)
    assert env["POSTGRES_USER"] == "app"
    assert env["POSTGRES_PASSWORD"] == ("secret", "pg-creds", "password")
