"""Per-install app-infrastructure secret materializer.

At runtime start (after the project namespace is created), scans all
Container.environment_vars and ContainerConnection config values for
``${secret:<name>/<key>}`` references.  For any secret name that:

  1. is NOT managed by another subsystem (``app-pod-key-*`` signing keys,
     ``app-userenv-*`` user-credential bundles), AND
  2. does NOT already exist in the project namespace,

a new K8s Secret is created with a cryptographically-random value for each
referenced key.  This resolves ``CreateContainerConfigError`` for
app-infrastructure secrets (e.g. ``pg-creds/password``) that must exist
before the pod scheduler can bind the container env.

Design notes
------------
* Only runs in Kubernetes mode; no-ops silently on docker/desktop.
* Idempotent: GET before CREATE; 409 → skip (another call beat us).
* Best-effort: a Secret-create failure logs and returns rather than
  blocking the start-runtime flow.  The pod will surface the missing env
  explicitly and the user can retry ``/start``.
* Values are generated with ``secrets.token_urlsafe(32)`` (URL-safe
  base64, ~43 chars).  All keys in the same Secret get independent values
  so rotation is key-granular.
* The extractor uses a non-anchored pattern so it also catches refs
  embedded inside larger strings (e.g. the DATABASE_URL connection mapping
  ``postgresql://user:${secret:pg-creds/password}@host/db``).
"""

from __future__ import annotations

import logging
import re
import secrets
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from ...models import Container, ContainerConnection

__all__ = ["provision_app_secrets"]

logger = logging.getLogger(__name__)

# Non-anchored variant — matches refs embedded anywhere in a string.
_SECRET_REF_ANY_RE = re.compile(r"\$\{secret:([^/}]+)/([^}]+)\}")

# Prefixes managed by other subsystems; skip them.
_SKIP_PREFIXES = ("app-pod-key-", "app-userenv-", "app-managed-")


def _collect_secret_refs(
    containers: list[Container],
    connections: list[ContainerConnection],
) -> dict[str, set[str]]:
    """Scan env vars and connection configs for ${secret:name/key} refs.

    Returns a mapping of ``{secret_name: {key, ...}}`` covering every ref
    found across all containers and connections, excluding managed prefixes.
    """
    refs: dict[str, set[str]] = {}

    def _scan(value: str | None) -> None:
        if not value:
            return
        for m in _SECRET_REF_ANY_RE.finditer(str(value)):
            name, key = m.group(1), m.group(2)
            if any(name.startswith(p) for p in _SKIP_PREFIXES):
                continue
            refs.setdefault(name, set()).add(key)

    for container in containers:
        for v in (container.environment_vars or {}).values():
            _scan(v)

    for conn in connections:
        cfg = conn.config or {}
        env_mapping = cfg.get("env_mapping") or {}
        for v in env_mapping.values():
            _scan(v)

    return refs


async def provision_app_secrets(
    *,
    project_id: UUID,
    containers: list[Container],
    connections: list[ContainerConnection],
) -> None:
    """Create missing app-infrastructure K8s Secrets in the project namespace.

    Called from ``app_runtime_status.start_runtime`` AFTER
    ``orchestrator.start_project()`` creates the namespace.  Best-effort:
    exceptions are logged and swallowed.
    """
    from ...config import get_settings

    settings = get_settings()
    if not getattr(settings, "is_kubernetes_mode", False):
        return

    refs = _collect_secret_refs(containers, connections)
    if not refs:
        return

    namespace = f"proj-{project_id}"

    from kubernetes import client as k8s_client

    core_v1 = k8s_client.CoreV1Api()

    for secret_name, keys in refs.items():
        try:
            _ensure_secret(core_v1, namespace=namespace, secret_name=secret_name, keys=keys)
        except Exception:
            logger.exception(
                "provision_app_secrets: failed to provision secret=%s ns=%s (pod will "
                "surface the missing env; retry /start to re-provision)",
                secret_name,
                namespace,
            )


def _ensure_secret(
    core_v1: object,
    *,
    namespace: str,
    secret_name: str,
    keys: set[str],
) -> None:
    from kubernetes import client as k8s_client
    from kubernetes.client.rest import ApiException

    api: k8s_client.CoreV1Api = core_v1  # type: ignore[assignment]

    # Idempotency check — if the Secret already exists, leave it alone.
    try:
        api.read_namespaced_secret(name=secret_name, namespace=namespace)
        logger.debug(
            "provision_app_secrets: secret=%s ns=%s already exists; skipping",
            secret_name,
            namespace,
        )
        return
    except ApiException as exc:
        if exc.status != 404:
            raise

    # Secret is absent — generate a random value per key and create it.
    string_data = {key: secrets.token_urlsafe(32) for key in keys}
    body = k8s_client.V1Secret(
        metadata=k8s_client.V1ObjectMeta(
            name=secret_name,
            namespace=namespace,
            labels={
                "tesslate.io/managed-by": "secret-provisioner",
                "tesslate.io/provisioned-for": "app-infra",
            },
        ),
        type="Opaque",
        string_data=string_data,
    )
    try:
        api.create_namespaced_secret(namespace=namespace, body=body)
        logger.info(
            "provision_app_secrets: created secret=%s ns=%s keys=%s",
            secret_name,
            namespace,
            sorted(keys),
        )
    except ApiException as exc:
        if exc.status == 409:
            # Lost a race; another caller created it first.
            logger.debug(
                "provision_app_secrets: secret=%s ns=%s created concurrently; skipping",
                secret_name,
                namespace,
            )
        else:
            raise
