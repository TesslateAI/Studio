"""Centralized Kubernetes client configuration loader.

Wraps ``kubernetes.config.load_incluster_config`` / ``load_kube_config``
to work around a regression in ``kubernetes`` >= 33 where
``load_incluster_config`` stores the service-account token under
``Configuration.api_key['authorization']`` but
``Configuration.auth_settings()`` only registers a ``BearerToken`` auth
entry when ``api_key['BearerToken']`` is set. The mismatch makes every
generated client method (``list_namespaced_pod``, ``create_namespaced_pod``,
``read_namespace`` …) skip the ``Authorization`` header and the API
server rejects the call as ``system:anonymous`` → 401.

We discovered this on EKS beta 2026-05-23: ``write_file`` / ``read_file``
worked because they route through Volume Hub (gRPC), but every k8s API
call from the backend and worker was failing.

Two defenses in this module:

1. ``load_in_cluster_or_kube()`` — the explicit helper every call site
   should use. It loads the config, then mirrors
   ``api_key['authorization']`` into ``api_key['BearerToken']`` and
   re-publishes the default ``Configuration``.

2. ``_patch_configuration_auth_settings()`` — a one-shot monkey-patch
   applied at import time that makes ``Configuration.auth_settings()``
   honour either key. Belt-and-suspenders: even if a caller forgets the
   helper (or a vendored library calls ``load_incluster_config`` itself),
   the patch keeps auth working.
"""

from __future__ import annotations

import logging

from kubernetes import client as k8s_client
from kubernetes import config as k8s_config

logger = logging.getLogger(__name__)

__all__ = [
    "load_in_cluster_or_kube",
]


def _patch_configuration_auth_settings() -> None:
    """Monkey-patch ``Configuration.auth_settings`` to honour the
    ``authorization`` api_key alongside the ``BearerToken`` one.

    Idempotent — checks for ``_tesslate_patched`` to avoid double-wrap.
    """
    Configuration = k8s_client.Configuration
    if getattr(Configuration.auth_settings, "_tesslate_patched", False):
        return

    original = Configuration.auth_settings

    def auth_settings(self):  # type: ignore[no-untyped-def]
        result = original(self)
        if "BearerToken" not in result and self.api_key and "authorization" in self.api_key:
            result["BearerToken"] = {
                "type": "api_key",
                "in": "header",
                "key": "authorization",
                "value": self.get_api_key_with_prefix("authorization"),
            }
        return result

    auth_settings._tesslate_patched = True  # type: ignore[attr-defined]
    Configuration.auth_settings = auth_settings


_patch_configuration_auth_settings()


def load_in_cluster_or_kube() -> None:
    """Load in-cluster config, falling back to ``~/.kube/config`` for dev.

    Raises ``kubernetes.config.ConfigException`` if neither works — this
    is a hard failure for any code path that needs the k8s API, so we
    deliberately do NOT swallow it.

    Safe to call multiple times; the kubernetes lib happily re-loads the
    same config and the BearerToken mirror is idempotent.
    """
    try:
        k8s_config.load_incluster_config()
    except k8s_config.ConfigException:
        k8s_config.load_kube_config()

    cfg = k8s_client.Configuration.get_default_copy()
    if cfg.api_key:
        token = cfg.api_key.get("authorization")
        if token and not cfg.api_key.get("BearerToken"):
            cfg.api_key["BearerToken"] = token
            k8s_client.Configuration.set_default(cfg)
