"""Helpers for resolving container env vars at runtime and substituting
connection templates.

Secret resolution (post-migration 0057):
  * Values in ``Container.encrypted_secrets`` are Fernet-encrypted and
    decrypted via ``deployment_encryption_service``.
  * Values in ``Container.environment_vars`` are PLAINTEXT — they are written
    plaintext by the direct-edit PATCH endpoint and the node-config tool for
    non-secret keys.
  * For transitional safety, if an ``environment_vars`` value fails to look
    like plaintext (looks base64-ish and decodes to something printable), we
    also accept it but emit a ``secret_backfill_needed`` structured warning
    so ops can spot un-migrated rows.

Once migration 0058 has run everywhere the base64 fallback can be removed
(currently gated by ``_try_legacy_base64``).
"""

import base64
import binascii
import json
import logging
import re
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..models import Container
    from .service_definitions import ServiceDefinition

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Secret resolution
# ---------------------------------------------------------------------------


_LEGACY_BASE64_RE = re.compile(r"^[A-Za-z0-9+/=]+$")


def _try_legacy_base64(value: str) -> str | None:
    """If *value* looks like base64 AND decodes to printable ASCII, return the
    decoded string. Otherwise return None.

    Transitional helper — kept until everyone has run migration 0058.
    """
    if not value or len(value) < 8 or len(value) % 4 != 0:
        return None
    if not _LEGACY_BASE64_RE.match(value):
        return None
    try:
        decoded_bytes = base64.b64decode(value.encode("utf-8"), validate=True)
        decoded = decoded_bytes.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    # Heuristic: the round-trip that re-encodes must match the original AND
    # the decoded string must look reasonable (printable).
    if any(ord(ch) < 32 and ch not in "\n\r\t" for ch in decoded):
        return None
    return decoded


def _decode_env_map(
    raw: dict[str, str] | None,
    *,
    project_id: str | None = None,
    container_id: str | None = None,
) -> dict[str, str]:
    """Return a plaintext env map. See module docstring for strategy."""
    if not raw:
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(value, str):
            out[key] = "" if value is None else str(value)
            continue
        legacy = _try_legacy_base64(value)
        if legacy is not None and legacy != value:
            logger.warning(
                json.dumps(
                    {
                        "event": "secret_backfill_needed",
                        "project_id": project_id,
                        "container_id": container_id,
                        "key": key,
                    }
                )
            )
            out[key] = legacy
        else:
            out[key] = value
    return out


def _merge_decrypted_secrets(
    container: "Container", env_map: dict[str, str]
) -> dict[str, str]:
    """Overlay decrypted ``encrypted_secrets`` on top of *env_map*."""
    encrypted = getattr(container, "encrypted_secrets", None) or {}
    if not encrypted:
        return env_map
    try:
        from .deployment_encryption import (
            DeploymentEncryptionError,
            get_deployment_encryption_service,
        )

        enc = get_deployment_encryption_service()
    except Exception:
        logger.warning(
            "[secret_manager_env] no encryption service — skipping %d secret key(s) "
            "on container %s",
            len(encrypted),
            getattr(container, "id", "?"),
        )
        return env_map
    for key, enc_val in encrypted.items():
        if not isinstance(enc_val, str) or not enc_val:
            continue
        try:
            env_map[key] = enc.decrypt(enc_val)
        except DeploymentEncryptionError:
            logger.warning(
                "[secret_manager_env] decrypt failed for container=%s key=%s",
                getattr(container, "id", "?"),
                key,
            )
    return env_map


def container_env(container: "Container") -> dict[str, str]:
    """Public helper: return the fully-resolved plaintext env map for a container."""
    base = _decode_env_map(
        container.environment_vars,
        project_id=str(getattr(container, "project_id", "")) or None,
        container_id=str(getattr(container, "id", "")) or None,
    )
    return _merge_decrypted_secrets(container, base)


# ---------------------------------------------------------------------------
# Connection template resolution
# ---------------------------------------------------------------------------


def resolve_connection_env_vars(
    source_container: "Container",
    service_def: "ServiceDefinition | None",
    decrypted_credentials: dict[str, str] | None = None,
) -> dict[str, str]:
    """Resolve connection template variables for a service container.

    See module docstring for the decode strategy.
    """
    if service_def is None:
        return {}

    template = service_def.connection_template
    if not template:
        return {}

    context: dict[str, str] = {}
    context["container_name"] = source_container.container_name or ""
    if service_def.internal_port is not None:
        context["internal_port"] = str(service_def.internal_port)
    for key, value in (service_def.environment_vars or {}).items():
        context[key] = value
    if source_container.environment_vars or getattr(
        source_container, "encrypted_secrets", None
    ):
        context.update(container_env(source_container))
    if decrypted_credentials:
        context.update(decrypted_credentials)

    resolved: dict[str, str] = {}
    for env_key, tmpl in template.items():
        try:
            resolved[env_key] = _substitute_template(tmpl, context)
        except Exception:
            logger.debug(
                "Skipping unresolvable template key %s for service %s",
                env_key,
                service_def.slug,
            )
    return resolved


def _resolve_via_exports(source_container: "Container") -> dict[str, str]:
    """Resolve env vars using the export-based system (plaintext env map)."""
    from .export_resolver import resolve_node_exports

    decoded_env = container_env(source_container)
    effective_port = (
        source_container.internal_port
        or source_container.port
        or 3000
    )
    return resolve_node_exports(
        node_name=source_container.container_name or source_container.name or "",
        exports=source_container.exports,
        env=decoded_env,
        port=effective_port,
    )


def _substitute_template(template: str, context: dict[str, str]) -> str:
    def _replacer(match: re.Match) -> str:
        key = match.group(1)
        if key not in context:
            raise KeyError(key)
        return context[key]

    return re.sub(r"\{(\w+)\}", _replacer, template)


async def _decrypt_container_credentials(
    db: "AsyncSession",
    container: "Container",
) -> dict[str, str] | None:
    if not container.credentials_id:
        return None

    from ..models import DeploymentCredential

    credential = await db.get(DeploymentCredential, container.credentials_id)
    if not credential or not credential.access_token_encrypted:
        return None

    try:
        from .deployment_encryption import get_deployment_encryption_service

        encryption_service = get_deployment_encryption_service()
        decrypted_json = encryption_service.decrypt(credential.access_token_encrypted)
        return json.loads(decrypted_json)
    except Exception:
        logger.warning(
            "Failed to decrypt credentials for container %s",
            container.id,
            exc_info=True,
        )
        return None


async def get_injected_env_vars_for_container(
    db: "AsyncSession",
    container_id: UUID,
    project_id: UUID,
) -> list[dict]:
    from ..models import Container, ContainerConnection

    result = await db.execute(
        select(ContainerConnection).where(
            ContainerConnection.project_id == project_id,
            ContainerConnection.target_container_id == container_id,
            ContainerConnection.connector_type == "env_injection",
        )
    )
    connections = result.scalars().all()
    if not connections:
        return []

    from .service_definitions import get_service

    injected: list[dict] = []
    for conn in connections:
        source = await db.get(Container, conn.source_container_id)
        if not source:
            continue

        if source.exports:
            # resolve via exports — uses the plaintext env map
            from .export_resolver import resolve_node_exports

            effective_port = source.internal_port or source.port or 3000
            resolved = resolve_node_exports(
                node_name=source.container_name or source.name or "",
                exports=source.exports,
                env=container_env(source),
                port=effective_port,
            )
        else:
            service_def = get_service(source.service_slug) if source.service_slug else None
            creds = None
            if source.deployment_mode == "external" and source.credentials_id:
                creds = await _decrypt_container_credentials(db, source)
            resolved = resolve_connection_env_vars(source, service_def, decrypted_credentials=creds)

        for env_key in resolved:
            injected.append(
                {
                    "key": env_key,
                    "source_container_name": source.name,
                    "source_container_id": str(source.id),
                }
            )

    return injected


async def build_env_overrides(
    db: "AsyncSession",
    project_id: UUID,
    containers: list,
) -> dict[UUID, dict[str, str]]:
    """Build {container_id: {env_key: plaintext_value}} — decoded env vars
    plus decrypted secrets, merged with any connection-template injections."""
    from ..models import Container, ContainerConnection

    overrides: dict[UUID, dict[str, str]] = {
        c.id: container_env(c) for c in containers
    }

    result = await db.execute(
        select(ContainerConnection).where(
            ContainerConnection.project_id == project_id,
            ContainerConnection.connector_type == "env_injection",
        )
    )
    connections = result.scalars().all()
    if not connections:
        return overrides

    container_map: dict[UUID, object] = {c.id: c for c in containers}
    from .service_definitions import get_service

    for conn in connections:
        source = container_map.get(conn.source_container_id)
        if source is None:
            source = await db.get(Container, conn.source_container_id)
            if source is None:
                continue
            container_map[source.id] = source

        if source.exports:
            from .export_resolver import resolve_node_exports

            effective_port = source.internal_port or source.port or 3000
            resolved = resolve_node_exports(
                node_name=source.container_name or source.name or "",
                exports=source.exports,
                env=container_env(source),
                port=effective_port,
            )
        else:
            service_def = get_service(source.service_slug) if source.service_slug else None
            creds = None
            if source.deployment_mode == "external" and source.credentials_id:
                creds = await _decrypt_container_credentials(db, source)
            resolved = resolve_connection_env_vars(source, service_def, decrypted_credentials=creds)

        if resolved:
            target_id = conn.target_container_id
            overrides.setdefault(target_id, {})
            overrides[target_id].update(resolved)

    return overrides
