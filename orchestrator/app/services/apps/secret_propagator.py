"""Propagate platform Secrets referenced by an app manifest into the project namespace.

K8s `secretKeyRef` is namespace-local, but platform secrets (e.g.
`llama-api-credentials`) live in the `tesslate` namespace while app pods run in
per-project namespaces (`proj-<uuid>`). Without this propagator, any fresh
install of an app that references a platform secret fails with
`CreateContainerConfigError: secret "<name>" not found`.

This module reads the referenced Secret from the platform ("source") namespace
and upserts a labelled copy into the target namespace. Idempotent: safe to call
on every start_environment so rotations of the source secret flow through.

Secrets are labelled `tesslate.io/managed-by=apps-installer` for GC/audit.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from kubernetes import client as k8s_client
from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)

MANAGED_LABEL_KEY = "tesslate.io/managed-by"
MANAGED_LABEL_VALUE = "apps-installer"
SOURCE_LABEL_KEY = "tesslate.io/source-secret"


def propagate_secrets(
    core_v1: k8s_client.CoreV1Api,
    secret_names: Iterable[str],
    source_namespace: str,
    target_namespace: str,
) -> list[str]:
    """Copy each named Secret from source → target namespace. Returns copied names.

    Missing source secrets are logged and skipped (pod will fail its own
    clearer ErrImageNeverPull/ConfigError, which is fine for dev).
    """
    copied: list[str] = []
    for name in set(secret_names):
        try:
            src = core_v1.read_namespaced_secret(name=name, namespace=source_namespace)
        except ApiException as e:
            if e.status == 404:
                logger.warning(
                    "secret_propagator: source secret %s not found in ns=%s; skipping",
                    name,
                    source_namespace,
                )
                continue
            raise

        body = k8s_client.V1Secret(
            metadata=k8s_client.V1ObjectMeta(
                name=name,
                namespace=target_namespace,
                labels={
                    MANAGED_LABEL_KEY: MANAGED_LABEL_VALUE,
                    SOURCE_LABEL_KEY: name,
                },
                annotations={
                    "tesslate.io/source-namespace": source_namespace,
                },
            ),
            type=src.type,
            data=src.data,
        )
        try:
            core_v1.create_namespaced_secret(namespace=target_namespace, body=body)
            logger.info("secret_propagator: created %s in ns=%s", name, target_namespace)
        except ApiException as e:
            if e.status == 409:
                # Already exists — patch data to track rotation.
                core_v1.patch_namespaced_secret(
                    name=name,
                    namespace=target_namespace,
                    body={"data": src.data, "metadata": {"labels": body.metadata.labels}},
                )
                logger.debug("secret_propagator: patched %s in ns=%s", name, target_namespace)
            else:
                raise
        copied.append(name)
    return copied
