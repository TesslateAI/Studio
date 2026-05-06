"""Materialize per-install Secrets that an app's manifest references.

Apps may declare environment values like ``${secret:pg-creds/password}`` in
their ``compute.containers[].env`` block. There are three cases for the
referenced secret name:

1. **Platform secret** (e.g. ``llama-api-credentials``) — exists in the
   orchestrator namespace and is copied into the project namespace by
   :mod:`.secret_propagator`. Untouched here.

2. **Orchestrator-managed secret** (e.g. ``app-pod-key-{instance_id}``,
   ``app-managed-db-{app_id}``, ``app-userenv-{instance_id}``) — minted by
   the install / runtime services that own them. Untouched here so we
   never collide with their lifecycle.

3. **Per-install secret** (e.g. ``pg-creds`` for crm-with-postgres) — the
   manifest references it but no platform or orchestrator service owns it.
   Without this module, kubelet stalls the pod with
   ``CreateContainerConfigError: secret "pg-creds" not found`` and the user
   has no UI to create it. We auto-generate a random value for each
   referenced key, write the Secret into the project namespace before the
   pods come up, and let the existing ``secretKeyRef`` plumbing in
   :func:`.env_resolver.resolve_env_for_pod` wire it into the spec.

The K8s Secret is itself the persistent record — on subsequent ``/start``
calls we read it back and reuse the values, so postgres data survives
restarts. Operators can rotate by deleting the Secret in the project
namespace; the next start materializes a fresh one.

Caller contract: invoke from the install-time saga **after** namespace
creation (i.e. alongside :func:`.installer.create_per_pod_signing_key` in
``app_runtime_status.start_runtime``). Best-effort: failures log and
return — the kubelet will surface a clearer ``CreateContainerConfigError``
on the pod, which beats hard-failing the start request.
"""

from __future__ import annotations

import logging
import secrets
from typing import TYPE_CHECKING

from .env_resolver import SECRET_REF_RE

if TYPE_CHECKING:
    from uuid import UUID

logger = logging.getLogger(__name__)

__all__ = [
    "RESERVED_SECRET_NAME_PREFIXES",
    "extract_secret_keymap",
    "materialize_per_install_secrets",
]

# Secret-name prefixes minted by other orchestrator services. Auto-generation
# would race their lifecycle (delete-on-uninstall, key-rotation, etc.). We
# leave them entirely to the owning module.
#
# The trailing slash / dash is part of the prefix so a hypothetical app
# legitimately named ``app-pod-keyboard`` wouldn't be matched.
RESERVED_SECRET_NAME_PREFIXES: tuple[str, ...] = (
    "app-pod-key-",  # installer.create_per_pod_signing_key
    "app-managed-db-",  # apps.managed_resources (postgres/clickhouse)
    "app-managed-s3-",  # apps.managed_resources (S3-compatible)
    "app-managed-redis-",  # apps.managed_resources (Redis)
    "app-userenv-",  # apps.user_secret_propagator
)


def _is_reserved(secret_name: str) -> bool:
    return any(secret_name.startswith(p) for p in RESERVED_SECRET_NAME_PREFIXES)


def extract_secret_keymap(env_dicts: list[dict[str, str] | None]) -> dict[str, set[str]]:
    """Walk every env dict and return ``{secret_name: {key, ...}}``.

    Multiple env vars may reference the same secret with different keys
    (e.g. ``USER`` → ``creds/user`` and ``PASS`` → ``creds/password``);
    callers need every key to materialize a single Secret holding both.
    """
    out: dict[str, set[str]] = {}
    for env in env_dicts:
        if not env:
            continue
        for raw in env.values():
            if raw is None:
                continue
            m = SECRET_REF_RE.match(str(raw))
            if not m:
                continue
            name, key = m.group(1), m.group(2)
            out.setdefault(name, set()).add(key)
    return out


def _generate_secret_value() -> str:
    """32-byte urlsafe token. Postgres handles this in a password column,
    and it's well below the 1MiB Secret size limit even at hundreds of keys.
    """
    return secrets.token_urlsafe(32)


def materialize_per_install_secrets(
    *,
    app_instance_id: UUID,
    target_namespace: str,
    source_namespace: str,
    env_dicts: list[dict[str, str] | None],
) -> dict[str, list[str]]:
    """Create any missing per-install Secrets in ``target_namespace``.

    Args:
        app_instance_id: For label/audit. Stamped on every Secret we mint.
        target_namespace: The ``proj-{project_id}`` namespace where the
            app's pods will run.
        source_namespace: The orchestrator namespace (typically
            ``tesslate``). Names that exist there are platform secrets
            and skipped — :mod:`.secret_propagator` copies them.
        env_dicts: Container environment dicts to scan for
            ``${secret:NAME/KEY}`` refs. Pass everything we know about
            (primary container env + connector overlays) so we don't miss
            a key referenced from only one container.

    Returns:
        ``{secret_name: [key, ...]}`` for each Secret we created. Names we
        skipped (reserved, already-present, platform-owned) are NOT in the
        return value.
    """
    # Late K8s imports keep this module importable in non-K8s deployment
    # modes (desktop, docker compose) where the materializer is a no-op.
    from kubernetes import client as k8s_client
    from kubernetes.client.rest import ApiException

    keymap = extract_secret_keymap(env_dicts)
    if not keymap:
        return {}

    core_v1 = k8s_client.CoreV1Api()
    created: dict[str, list[str]] = {}

    for name, keys in keymap.items():
        if _is_reserved(name):
            logger.debug(
                "per_install_secret_provisioner: %s is reserved; "
                "owning service handles it (instance=%s)",
                name,
                app_instance_id,
            )
            continue

        # 1) Already in target ns (prior /start materialized it, or the
        # platform-secret propagator beat us here). Idempotent: skip.
        try:
            core_v1.read_namespaced_secret(name=name, namespace=target_namespace)
            logger.debug(
                "per_install_secret_provisioner: %s already exists in ns=%s; skipping",
                name,
                target_namespace,
            )
            continue
        except ApiException as exc:
            if exc.status not in (404, 410):
                logger.warning(
                    "per_install_secret_provisioner: read %s in ns=%s failed (%s); "
                    "skipping to avoid clobbering an existing secret",
                    name,
                    target_namespace,
                    exc.status,
                )
                continue

        # 2) Lives in the platform ns — secret_propagator will copy it
        # at start_environment time. Don't shadow it with a random value.
        try:
            core_v1.read_namespaced_secret(name=name, namespace=source_namespace)
            logger.debug(
                "per_install_secret_provisioner: %s is a platform secret in ns=%s; "
                "leaving propagator to handle",
                name,
                source_namespace,
            )
            continue
        except ApiException as exc:
            if exc.status not in (404, 410):
                logger.warning(
                    "per_install_secret_provisioner: lookup %s in source ns=%s "
                    "failed (%s); generating per-install value defensively",
                    name,
                    source_namespace,
                    exc.status,
                )
                # Fall through — generating a per-install value is safer
                # than letting the pod CrashLoop with no secret at all.

        # 3) Mint a fresh value per key and write a single Secret holding all.
        sorted_keys = sorted(keys)
        body = k8s_client.V1Secret(
            metadata=k8s_client.V1ObjectMeta(
                name=name,
                namespace=target_namespace,
                labels={
                    "tesslate.io/managed-by": "per-install-secret-provisioner",
                    "tesslate.io/app-instance-id": str(app_instance_id),
                },
            ),
            type="Opaque",
            string_data={k: _generate_secret_value() for k in sorted_keys},
        )
        try:
            core_v1.create_namespaced_secret(namespace=target_namespace, body=body)
            created[name] = sorted_keys
            logger.info(
                "per_install_secret_provisioner: minted %s with keys=%s in ns=%s instance=%s",
                name,
                sorted_keys,
                target_namespace,
                app_instance_id,
            )
        except ApiException as exc:
            if exc.status == 409:
                # Raced with another /start — the other request won; reuse it.
                logger.info(
                    "per_install_secret_provisioner: %s in ns=%s won by concurrent "
                    "/start; reusing existing values",
                    name,
                    target_namespace,
                )
                continue
            logger.warning(
                "per_install_secret_provisioner: create %s in ns=%s failed (%s); "
                "kubelet will surface CreateContainerConfigError on the pod",
                name,
                target_namespace,
                exc.status,
            )
        except Exception:  # noqa: BLE001 — non-fatal
            logger.exception(
                "per_install_secret_provisioner: unexpected error minting %s in ns=%s",
                name,
                target_namespace,
            )

    return created
