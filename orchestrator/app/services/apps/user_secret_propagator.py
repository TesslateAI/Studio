"""Propagate per-user OAuth/API-key credentials into per-install K8s Secrets.

Phase 3, Wave 1B: companion to ``secret_propagator.py``.

``secret_propagator.py`` copies *platform* secrets (e.g. ``llama-api-credentials``)
from the ``tesslate`` namespace into ``proj-*``. That covers shared platform
keys but says nothing about credentials a user has connected for THEIR account
(Linear PATs, Slack OAuth tokens, GitHub PATs, ...).

This module fills that gap for ``exposure: env`` connector grants. It pulls
credentials from the rows pointed at by
``AppConnectorGrant.resolved_ref`` (``user_mcp_config`` / ``oauth_connection``
/ ``api_key_secret``), Fernet-decrypts them via the shared channel encryption
key, and upserts a SINGLE per-install Secret named
``app-userenv-{instance_id}`` in the install's namespace. The app pod's
``env_resolver`` later resolves
``${secret:app-userenv-${self.id}/<connector>_<key>}`` patterns against this
Secret at start time.

Design notes
------------
* One Secret per install. No cross-namespace copies — every install gets
  its own copy keyed by ``app_instance_id`` so revocation/uninstall is a
  single ``delete``.
* ``oauth + exposure='env'`` is REJECTED at install time by Wave 1B's
  Pydantic validator. We log+skip if one slips through here, so we never
  expose long-lived bearer tokens as plain env vars.
* Failures are logged and surface to the caller as exceptions only when
  the K8s API itself fails. The installer wraps the call in try/except so
  a propagation hiccup does not roll back the install — the user can
  re-trigger via "Resync credentials".
* ``string_data`` is used (not ``data``) so callers don't have to
  base64-encode. K8s does it server-side.
* Idempotent: 409 from create → patch.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any
from uuid import UUID

from kubernetes import client as k8s_client
from kubernetes.client.rest import ApiException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import McpOAuthConnection, UserMcpConfig
from ...models_automations import (
    AppConnectorGrant,
    AppConnectorRequirement,
    AppInstance,
)
from ..channels.registry import decrypt_credentials

logger = logging.getLogger(__name__)

__all__ = [
    "propagate_user_secrets",
    "delete_user_secrets",
    "user_secret_name",
    "MANAGED_LABEL_KEY",
    "MANAGED_LABEL_VALUE",
]

MANAGED_LABEL_KEY = "tesslate.io/managed-by"
MANAGED_LABEL_VALUE = "user-secret-propagator"
APP_INSTANCE_LABEL_KEY = "tesslate.io/app-instance-id"
SOURCE_ANNOTATION_KEY = "tesslate.io/source"
SOURCE_ANNOTATION_VALUE = "user-credentials"


def user_secret_name(app_instance_id: UUID) -> str:
    """Canonical per-install Secret name."""
    return f"app-userenv-{app_instance_id}"


def _sanitize_key(raw: str) -> str:
    """Coerce an arbitrary credential key to a K8s Secret key.

    K8s Secret keys must match ``[-._a-zA-Z0-9]+``. We replace anything
    else with ``_`` so credential dicts with hyphenated keys (e.g.
    ``api-key``) still land cleanly.
    """
    out = []
    for ch in raw:
        if ch.isalnum() or ch in "-._":
            out.append(ch)
        else:
            out.append("_")
    return "".join(out) or "_"


async def _load_env_grants_for_install(
    db: AsyncSession, app_instance_id: UUID
) -> list[tuple[AppConnectorGrant, AppConnectorRequirement]]:
    """Return ``(grant, requirement)`` pairs for live env-exposure grants."""
    stmt = (
        select(AppConnectorGrant, AppConnectorRequirement)
        .join(
            AppConnectorRequirement,
            AppConnectorRequirement.id == AppConnectorGrant.requirement_id,
        )
        .where(
            AppConnectorGrant.app_instance_id == app_instance_id,
            AppConnectorGrant.exposure_at_grant == "env",
            AppConnectorGrant.revoked_at.is_(None),
        )
    )
    rows = (await db.execute(stmt)).all()
    return [(row[0], row[1]) for row in rows]


async def _resolve_grant_credentials(
    db: AsyncSession,
    grant: AppConnectorGrant,
    connector_id: str,
) -> tuple[dict[str, str], str]:
    """Decrypt the credentials referenced by a single grant.

    Returns ``(plaintext_dict, status)`` where status is one of:

    * ``"upserted"``       — credentials decrypted and ready to write
    * ``"skipped_no_credentials"`` — referenced row missing or empty
    * ``"skipped_oauth_env_invalid"`` — defensive: oauth+env never legal
    * ``"skipped_unknown_kind"`` — resolved_ref.kind not recognized
    * ``"skipped_decrypt_failed"`` — Fernet decrypt failed
    """
    ref: dict[str, Any] = grant.resolved_ref or {}
    kind = ref.get("kind")
    raw_id = ref.get("id")
    if not kind or not raw_id:
        logger.warning(
            "user_secret_propagator: grant %s has malformed resolved_ref; skipping",
            grant.id,
        )
        return {}, "skipped_no_credentials"

    if kind == "user_mcp_config":
        try:
            cfg_id = UUID(str(raw_id))
        except (TypeError, ValueError):
            return {}, "skipped_no_credentials"
        cfg = await db.get(UserMcpConfig, cfg_id)
        if cfg is None or not cfg.credentials:
            return {}, "skipped_no_credentials"
        try:
            decrypted = decrypt_credentials(cfg.credentials)
        except Exception as exc:
            logger.error(
                "user_secret_propagator: decrypt failed for user_mcp_config=%s err=%r",
                cfg_id,
                exc,
            )
            return {}, "skipped_decrypt_failed"
        # Coerce values to strings — Secret string_data must be str.
        flat = {
            _sanitize_key(str(k)): "" if v is None else str(v)
            for k, v in (decrypted or {}).items()
        }
        return flat, "upserted"

    if kind == "oauth_connection":
        # Defensive: Wave 1B's validator rejects oauth+env at install time.
        # If one ever slips through, refuse to expose the bearer as env.
        logger.warning(
            "user_secret_propagator: oauth + env grant for connector=%s "
            "instance=%s; refusing to expose (wave-1B validator should have "
            "caught this)",
            connector_id,
            grant.app_instance_id,
        )
        return {}, "skipped_oauth_env_invalid"

    if kind == "api_key_secret":
        # Mirrors the connector_proxy stub. The platform-managed
        # api_key_secret store is a Phase 3.1 follow-up; until then we
        # surface a clear status so the install UI can tell the user.
        logger.info(
            "user_secret_propagator: api_key_secret resolution not yet "
            "implemented (connector=%s grant=%s)",
            connector_id,
            grant.id,
        )
        return {}, "skipped_no_credentials"

    logger.warning(
        "user_secret_propagator: unknown resolved_ref.kind=%r for grant=%s",
        kind,
        grant.id,
    )
    return {}, "skipped_unknown_kind"


def _upsert_secret(
    core_v1: k8s_client.CoreV1Api,
    *,
    secret_name: str,
    target_namespace: str,
    string_data: dict[str, str],
    labels: dict[str, str],
    annotations: dict[str, str],
) -> str:
    """Create-or-patch the Secret. Returns ``"created"`` or ``"patched"``."""
    body = k8s_client.V1Secret(
        metadata=k8s_client.V1ObjectMeta(
            name=secret_name,
            namespace=target_namespace,
            labels=labels,
            annotations=annotations,
        ),
        type="Opaque",
        string_data=string_data,
    )
    try:
        core_v1.create_namespaced_secret(namespace=target_namespace, body=body)
        logger.info(
            "user_secret_propagator: created %s in ns=%s (%d keys)",
            secret_name,
            target_namespace,
            len(string_data),
        )
        return "created"
    except ApiException as e:
        if e.status == 409:
            core_v1.patch_namespaced_secret(
                name=secret_name,
                namespace=target_namespace,
                body={
                    "stringData": string_data,
                    "metadata": {
                        "labels": labels,
                        "annotations": annotations,
                    },
                },
            )
            logger.debug(
                "user_secret_propagator: patched %s in ns=%s (%d keys)",
                secret_name,
                target_namespace,
                len(string_data),
            )
            return "patched"
        raise


async def propagate_user_secrets(
    db: AsyncSession,
    core_v1: k8s_client.CoreV1Api,
    *,
    app_instance: AppInstance,
    target_namespace: str,
    grants: Iterable[AppConnectorGrant] | None = None,
) -> dict[str, str]:
    """Pull per-user credentials and upsert ``app-userenv-{instance_id}``.

    Args:
        db: Active SQLAlchemy session.
        core_v1: Kubernetes ``CoreV1Api`` client. Tests inject a mock.
        app_instance: The install we're materializing credentials for.
        target_namespace: Namespace where the app's pods live (typically
            ``proj-{project_id}``).
        grants: Optional iterable of ``AppConnectorGrant`` rows. If
            ``None``, we query all live ``exposure='env'`` grants for the
            install.

    Returns:
        ``{connector_id: status}`` for every grant we considered. Statuses
        match ``_resolve_grant_credentials``.
    """
    if grants is None:
        pairs = await _load_env_grants_for_install(db, app_instance.id)
    else:
        # Caller provided grants — load their requirements so we can read
        # ``connector_id`` for status reporting + secret-key prefixing.
        pairs = []
        for grant in grants:
            req = await db.get(AppConnectorRequirement, grant.requirement_id)
            if req is None:
                continue
            if grant.exposure_at_grant != "env" or grant.revoked_at is not None:
                continue
            pairs.append((grant, req))

    statuses: dict[str, str] = {}
    string_data: dict[str, str] = {}

    for grant, requirement in pairs:
        connector_id = requirement.connector_id
        creds, status = await _resolve_grant_credentials(db, grant, connector_id)
        statuses[connector_id] = status
        if status != "upserted":
            continue
        # Prefix every key with the connector_id so two connectors with
        # the same key (e.g. both expose ``api_key``) don't collide in
        # the flat Secret.
        prefix = _sanitize_key(connector_id)
        for k, v in creds.items():
            string_data[f"{prefix}_{k}"] = v

    if not pairs:
        logger.debug(
            "user_secret_propagator: no env grants for instance=%s; skipping",
            app_instance.id,
        )
        return statuses

    # Even if every grant resolved to skipped, we still upsert the Secret
    # (possibly empty string_data) so the pod's ``envFrom: secretRef``
    # doesn't fail with "Secret not found". An empty Secret is preferable
    # to a missing one — the pod env vars will simply be absent and the
    # app's startup error will name them explicitly.
    secret_name = user_secret_name(app_instance.id)
    labels = {
        MANAGED_LABEL_KEY: MANAGED_LABEL_VALUE,
        APP_INSTANCE_LABEL_KEY: str(app_instance.id),
    }
    annotations = {
        SOURCE_ANNOTATION_KEY: SOURCE_ANNOTATION_VALUE,
    }
    _upsert_secret(
        core_v1,
        secret_name=secret_name,
        target_namespace=target_namespace,
        string_data=string_data,
        labels=labels,
        annotations=annotations,
    )

    return statuses


async def delete_user_secrets(
    core_v1: k8s_client.CoreV1Api,
    *,
    app_instance_id: UUID,
    target_namespace: str,
) -> bool:
    """Delete ``app-userenv-{instance_id}`` from ``target_namespace``.

    Returns ``True`` if the Secret was deleted, ``False`` if it was already
    gone. Other ``ApiException`` errors propagate so the caller can decide
    whether to retry. Cleanup is a best-effort step — uninstall flows wrap
    this in try/except so a stuck Secret doesn't block namespace teardown.
    """
    secret_name = user_secret_name(app_instance_id)
    try:
        core_v1.delete_namespaced_secret(
            name=secret_name,
            namespace=target_namespace,
        )
        logger.info(
            "user_secret_propagator: deleted %s from ns=%s",
            secret_name,
            target_namespace,
        )
        return True
    except ApiException as e:
        if e.status == 404:
            logger.debug(
                "user_secret_propagator: %s already absent from ns=%s",
                secret_name,
                target_namespace,
            )
            return False
        raise
