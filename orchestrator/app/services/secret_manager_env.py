"""Helpers for decoding container env vars at runtime and resolving connection templates."""

import json
import logging
import re
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

from .secret_codec import decode_secret_map

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..models import Container
    from .service_definitions import ServiceDefinition

logger = logging.getLogger(__name__)


def resolve_connection_env_vars(
    source_container: "Container",
    service_def: "ServiceDefinition | None",
    decrypted_credentials: dict[str, str] | None = None,
) -> dict[str, str]:
    """Resolve connection template variables for a service container.

    For container-type services (postgres, redis, etc.), substitutes:
      - {container_name} → sanitised Docker/K8s container name
      - {internal_port}  → str(service_def.internal_port)
      - {VAR}            → value from service_def.environment_vars

    For external services, substitutes:
      - {credential_key} → value from *decrypted_credentials*

    Returns a dict of env var name → resolved value ready to inject into
    the target container.
    """
    if service_def is None:
        return {}

    template = service_def.connection_template
    if not template:
        return {}

    # Build the substitution context
    context: dict[str, str] = {}

    # Container name (sanitised for DNS)
    context["container_name"] = source_container.container_name or ""

    # Internal port
    if service_def.internal_port is not None:
        context["internal_port"] = str(service_def.internal_port)

    # Service default env vars (e.g. POSTGRES_USER, POSTGRES_PASSWORD)
    for key, value in (service_def.environment_vars or {}).items():
        context[key] = value

    # Override with any user-customised env vars stored on the container
    if source_container.environment_vars:
        decoded = decode_secret_map(source_container.environment_vars)
        for key, value in decoded.items():
            context[key] = value

    # For external services, merge decrypted credentials into context
    # Credentials are stored in DeploymentCredential (Fernet-encrypted JSON)
    # and must be decrypted by the caller before passing here.
    if decrypted_credentials:
        context.update(decrypted_credentials)

    # Perform template substitution
    resolved: dict[str, str] = {}
    for env_key, tmpl in template.items():
        try:
            value = _substitute_template(tmpl, context)
            resolved[env_key] = value
        except Exception:
            logger.debug(
                "Skipping unresolvable template key %s for service %s",
                env_key,
                service_def.slug,
            )

    return resolved


def _resolve_via_exports(source_container: "Container") -> dict[str, str]:
    """Resolve env vars using the new export-based system.

    When a container has .exports populated, resolve ${} placeholders
    against the container's own env vars, HOST (container_name), and PORT.

    Returns resolved export key-value pairs ready for injection.
    """
    from .export_resolver import resolve_node_exports

    decoded_env = decode_secret_map(source_container.environment_vars or {})
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
    """Replace {placeholder} tokens in *template* with values from *context*.

    Raises ``KeyError`` if any placeholder is missing from context.
    """

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
    """Decrypt stored credentials for an external service container.

    Returns the credential key-value pairs or None if no credentials exist.
    """
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
    """Return the list of injected env vars for a target container.

    Each entry: {"key": "DATABASE_URL", "source_container_name": "postgres-1", "source_container_id": "<uuid>"}
    """
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

        # New export-based path: if source has .exports, use the export resolver
        if source.exports:
            resolved = _resolve_via_exports(source)
        else:
            # Fallback to legacy template-based resolution
            service_def = get_service(source.service_slug) if source.service_slug else None

            # Decrypt credentials for external services
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
    """Decode base64-encoded container env vars *and* merge injected connection
    template vars for runtime injection.

    Returns {container_id: {env_key: plain_value}} for every container.
    """
    from ..models import Container, ContainerConnection

    # 1. Start with each container's own env vars (decoded)
    overrides: dict[UUID, dict[str, str]] = {
        c.id: decode_secret_map(c.environment_vars or {}) for c in containers
    }

    # 2. Look up all env_injection connections in the project
    result = await db.execute(
        select(ContainerConnection).where(
            ContainerConnection.project_id == project_id,
            ContainerConnection.connector_type == "env_injection",
        )
    )
    connections = result.scalars().all()

    if not connections:
        return overrides

    # Build a lookup of container by id for fast access
    container_map: dict[UUID, object] = {c.id: c for c in containers}

    from .service_definitions import get_service

    for conn in connections:
        source = container_map.get(conn.source_container_id)
        if source is None:
            # Source container not in provided list — fetch from DB
            source = await db.get(Container, conn.source_container_id)
            if source is None:
                continue
            container_map[source.id] = source

        # New export-based path: if source has .exports, use the export resolver
        if source.exports:
            resolved = _resolve_via_exports(source)
        else:
            # Fallback to legacy template-based resolution
            service_def = get_service(source.service_slug) if source.service_slug else None

            # Decrypt credentials for external services
            creds = None
            if source.deployment_mode == "external" and source.credentials_id:
                creds = await _decrypt_container_credentials(db, source)

            resolved = resolve_connection_env_vars(source, service_def, decrypted_credentials=creds)

        if resolved:
            target_id = conn.target_container_id
            overrides.setdefault(target_id, {})
            overrides[target_id].update(resolved)

    return overrides
