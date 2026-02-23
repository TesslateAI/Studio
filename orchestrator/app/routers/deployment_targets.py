"""
Deployment Targets API Router.

This module provides API endpoints for managing deployment target nodes in the
React Flow graph. Deployment targets are standalone nodes that containers connect
to for external deployment (Vercel, Netlify, Cloudflare, DigitalOcean K8s, etc.).
"""

import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_db
from ..models import (
    Container,
    Deployment,
    DeploymentCredential,
    DeploymentTarget,
    DeploymentTargetConnection,
    Project,
    User,
)
from ..services.deployment.guards import (
    PROVIDER_CAPABILITIES,
    get_provider_info,
    list_all_providers,
    validate_deployment_connection,
)
from ..users import current_active_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["deployment-targets"])


# ============================================================================
# Request/Response Models
# ============================================================================


class DeploymentTargetCreate(BaseModel):
    """Request to create a deployment target node."""

    provider: str = Field(
        ..., description="Deployment provider: vercel, netlify, cloudflare, digitalocean, railway, fly"
    )
    environment: str = Field(default="production", description="Environment: production, staging, preview")
    name: str | None = Field(None, description="Optional custom display name")
    position_x: float = Field(default=0, description="X position on canvas")
    position_y: float = Field(default=0, description="Y position on canvas")


class DeploymentTargetUpdate(BaseModel):
    """Request to update a deployment target node."""

    environment: str | None = Field(None, description="Environment: production, staging, preview")
    name: str | None = Field(None, description="Optional custom display name")
    position_x: float | None = Field(None, description="X position on canvas")
    position_y: float | None = Field(None, description="Y position on canvas")


class ContainerSummary(BaseModel):
    """Summary of a connected container."""

    id: UUID
    name: str
    container_type: str | None = None
    framework: str | None = None
    status: str


class DeploymentSummary(BaseModel):
    """Summary of a deployment for history."""

    id: UUID
    version: str | None = None
    status: str
    deployment_url: str | None = None
    container_id: UUID | None = None
    container_name: str | None = None
    created_at: str
    completed_at: str | None = None


class ProviderInfo(BaseModel):
    """Provider capability information."""

    display_name: str
    icon: str
    color: str
    types: list[str]
    frameworks: list[str]
    supports_serverless: bool
    supports_static: bool
    supports_fullstack: bool
    deployment_mode: str


class DeploymentTargetResponse(BaseModel):
    """Response containing deployment target information."""

    id: UUID
    project_id: UUID
    provider: str
    environment: str
    name: str | None = None
    position_x: float
    position_y: float
    is_connected: bool
    credential_id: UUID | None = None
    provider_info: ProviderInfo
    connected_containers: list[ContainerSummary]
    deployment_history: list[DeploymentSummary]
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class ConnectionValidation(BaseModel):
    """Result of validating a container-target connection."""

    allowed: bool
    reason: str


class DeployRequest(BaseModel):
    """Request to deploy connected containers."""

    env_vars: dict[str, str] = Field(default_factory=dict, description="Additional environment variables")
    build_command: str | None = Field(None, description="Custom build command override")


# ============================================================================
# Helper Functions
# ============================================================================


async def get_project_or_404(
    slug: str, db: AsyncSession, user: User
) -> Project:
    """Get project by slug or raise 404."""
    result = await db.execute(
        select(Project).where(
            and_(Project.slug == slug, Project.owner_id == user.id)
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{slug}' not found",
        )
    return project


async def get_deployment_target_or_404(
    target_id: UUID, project_id: UUID, db: AsyncSession
) -> DeploymentTarget:
    """Get deployment target by ID or raise 404."""
    result = await db.execute(
        select(DeploymentTarget)
        .options(selectinload(DeploymentTarget.connected_containers))
        .where(
            and_(
                DeploymentTarget.id == target_id,
                DeploymentTarget.project_id == project_id,
            )
        )
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deployment target '{target_id}' not found",
        )
    return target


def build_target_response(
    target: DeploymentTarget,
    connected_containers: list[ContainerSummary],
    deployment_history: list[DeploymentSummary],
) -> DeploymentTargetResponse:
    """Build a response object for a deployment target."""
    provider_info = get_provider_info(target.provider)
    return DeploymentTargetResponse(
        id=target.id,
        project_id=target.project_id,
        provider=target.provider,
        environment=target.environment,
        name=target.name,
        position_x=target.position_x,
        position_y=target.position_y,
        is_connected=target.is_connected,
        credential_id=target.credential_id,
        provider_info=ProviderInfo(
            display_name=provider_info["display_name"] if provider_info else target.provider,
            icon=provider_info["icon"] if provider_info else "🚀",
            color=provider_info["color"] if provider_info else "#888888",
            types=provider_info["types"] if provider_info else ["*"],
            frameworks=provider_info["frameworks"] if provider_info else ["*"],
            supports_serverless=provider_info["supports_serverless"] if provider_info else False,
            supports_static=provider_info["supports_static"] if provider_info else True,
            supports_fullstack=provider_info["supports_fullstack"] if provider_info else False,
            deployment_mode=provider_info["deployment_mode"] if provider_info else "source",
        ),
        connected_containers=connected_containers,
        deployment_history=deployment_history,
        created_at=target.created_at.isoformat() if target.created_at else "",
        updated_at=target.updated_at.isoformat() if target.updated_at else "",
    )


# ============================================================================
# CRUD Endpoints
# ============================================================================


@router.post("/{slug}/deployment-targets", response_model=DeploymentTargetResponse)
async def create_deployment_target(
    slug: str,
    request: DeploymentTargetCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """Create a new deployment target node."""
    project = await get_project_or_404(slug, db, user)

    # Validate provider
    if request.provider not in PROVIDER_CAPABILITIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown deployment provider: {request.provider}. "
            f"Supported: {', '.join(PROVIDER_CAPABILITIES.keys())}",
        )

    # Check if user has credentials for this provider
    credential_result = await db.execute(
        select(DeploymentCredential).where(
            and_(
                DeploymentCredential.user_id == user.id,
                DeploymentCredential.provider == request.provider,
            )
        )
    )
    credential = credential_result.scalar_one_or_none()
    is_connected = credential is not None

    # Create target
    target = DeploymentTarget(
        project_id=project.id,
        provider=request.provider,
        environment=request.environment,
        name=request.name,
        position_x=request.position_x,
        position_y=request.position_y,
        is_connected=is_connected,
        credential_id=credential.id if credential else None,
    )
    db.add(target)
    await db.commit()
    await db.refresh(target)

    logger.info(
        f"Created deployment target {target.id} for project {project.slug} "
        f"(provider: {request.provider}, connected: {is_connected})"
    )

    return build_target_response(target, [], [])


@router.get("/{slug}/deployment-targets", response_model=list[DeploymentTargetResponse])
async def list_deployment_targets(
    slug: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """List all deployment targets for a project."""
    project = await get_project_or_404(slug, db, user)

    # Fetch targets with connected containers
    result = await db.execute(
        select(DeploymentTarget)
        .options(
            selectinload(DeploymentTarget.connected_containers).selectinload(
                DeploymentTargetConnection.container
            )
        )
        .where(DeploymentTarget.project_id == project.id)
        .order_by(DeploymentTarget.created_at)
    )
    targets = result.scalars().all()

    responses = []
    for target in targets:
        # Get connected containers
        connected = []
        for conn in target.connected_containers:
            if conn.container:
                # Get framework from settings or base
                framework = None
                if conn.deployment_settings:
                    framework = conn.deployment_settings.get("framework")
                connected.append(
                    ContainerSummary(
                        id=conn.container.id,
                        name=conn.container.name,
                        container_type=conn.container.container_type,
                        framework=framework,
                        status=conn.container.status,
                    )
                )

        # Get deployment history
        history_result = await db.execute(
            select(Deployment)
            .where(Deployment.deployment_target_id == target.id)
            .order_by(desc(Deployment.created_at))
            .limit(10)
        )
        deployments = history_result.scalars().all()

        history = []
        for dep in deployments:
            container_name = None
            if dep.container_id:
                container_result = await db.execute(
                    select(Container).where(Container.id == dep.container_id)
                )
                container = container_result.scalar_one_or_none()
                if container:
                    container_name = container.name
            history.append(
                DeploymentSummary(
                    id=dep.id,
                    version=dep.version,
                    status=dep.status,
                    deployment_url=dep.deployment_url,
                    container_id=dep.container_id,
                    container_name=container_name,
                    created_at=dep.created_at.isoformat() if dep.created_at else "",
                    completed_at=dep.completed_at.isoformat() if dep.completed_at else None,
                )
            )

        responses.append(build_target_response(target, connected, history))

    return responses


@router.get("/{slug}/deployment-targets/providers")
async def list_providers(
    slug: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """List all available deployment providers with their capabilities."""
    await get_project_or_404(slug, db, user)

    # Get user's connected providers
    credentials_result = await db.execute(
        select(DeploymentCredential.provider).where(
            DeploymentCredential.user_id == user.id
        )
    )
    connected_providers = set(r[0] for r in credentials_result.all())

    providers = []
    for provider_slug, info in list_all_providers().items():
        providers.append({
            "slug": provider_slug,
            "display_name": info["display_name"],
            "icon": info["icon"],
            "color": info["color"],
            "types": info["types"],
            "frameworks": info["frameworks"],
            "supports_serverless": info["supports_serverless"],
            "supports_static": info["supports_static"],
            "supports_fullstack": info["supports_fullstack"],
            "deployment_mode": info["deployment_mode"],
            "is_connected": provider_slug in connected_providers,
        })

    return providers


@router.get("/{slug}/deployment-targets/{target_id}", response_model=DeploymentTargetResponse)
async def get_deployment_target(
    slug: str,
    target_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """Get a specific deployment target."""
    project = await get_project_or_404(slug, db, user)
    target = await get_deployment_target_or_404(target_id, project.id, db)

    # Get connected containers
    connected = []
    for conn in target.connected_containers:
        container_result = await db.execute(
            select(Container).where(Container.id == conn.container_id)
        )
        container = container_result.scalar_one_or_none()
        if container:
            framework = None
            if conn.deployment_settings:
                framework = conn.deployment_settings.get("framework")
            connected.append(
                ContainerSummary(
                    id=container.id,
                    name=container.name,
                    container_type=container.container_type,
                    framework=framework,
                    status=container.status,
                )
            )

    # Get deployment history
    history_result = await db.execute(
        select(Deployment)
        .where(Deployment.deployment_target_id == target.id)
        .order_by(desc(Deployment.created_at))
        .limit(10)
    )
    deployments = history_result.scalars().all()

    history = []
    for dep in deployments:
        container_name = None
        if dep.container_id:
            c_result = await db.execute(
                select(Container).where(Container.id == dep.container_id)
            )
            c = c_result.scalar_one_or_none()
            if c:
                container_name = c.name
        history.append(
            DeploymentSummary(
                id=dep.id,
                version=dep.version,
                status=dep.status,
                deployment_url=dep.deployment_url,
                container_id=dep.container_id,
                container_name=container_name,
                created_at=dep.created_at.isoformat() if dep.created_at else "",
                completed_at=dep.completed_at.isoformat() if dep.completed_at else None,
            )
        )

    return build_target_response(target, connected, history)


@router.patch("/{slug}/deployment-targets/{target_id}", response_model=DeploymentTargetResponse)
async def update_deployment_target(
    slug: str,
    target_id: UUID,
    request: DeploymentTargetUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """Update a deployment target (position, name, environment)."""
    project = await get_project_or_404(slug, db, user)
    target = await get_deployment_target_or_404(target_id, project.id, db)

    # Update fields
    if request.environment is not None:
        target.environment = request.environment
    if request.name is not None:
        target.name = request.name
    if request.position_x is not None:
        target.position_x = request.position_x
    if request.position_y is not None:
        target.position_y = request.position_y

    await db.commit()
    await db.refresh(target)

    # Return full response
    return await get_deployment_target(slug, target_id, db, user)


@router.delete("/{slug}/deployment-targets/{target_id}")
async def delete_deployment_target(
    slug: str,
    target_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """Delete a deployment target and all its connections."""
    project = await get_project_or_404(slug, db, user)
    target = await get_deployment_target_or_404(target_id, project.id, db)

    await db.delete(target)
    await db.commit()

    logger.info(f"Deleted deployment target {target_id} from project {project.slug}")

    return {"status": "deleted", "id": str(target_id)}


# ============================================================================
# Connection Endpoints
# ============================================================================


@router.post("/{slug}/deployment-targets/{target_id}/connect/{container_id}")
async def connect_container_to_target(
    slug: str,
    target_id: UUID,
    container_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """Connect a container to a deployment target."""
    project = await get_project_or_404(slug, db, user)
    target = await get_deployment_target_or_404(target_id, project.id, db)

    # Get container
    container_result = await db.execute(
        select(Container).where(
            and_(Container.id == container_id, Container.project_id == project.id)
        )
    )
    container = container_result.scalar_one_or_none()
    if not container:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Container '{container_id}' not found",
        )

    # Validate connection using guards
    validation = validate_deployment_connection(
        provider=target.provider,
        container_type=container.container_type,
        service_slug=container.service_slug,
        framework=None,  # Will be detected during deployment
    )

    if not validation["allowed"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=validation["reason"],
        )

    # Check if connection already exists
    existing_result = await db.execute(
        select(DeploymentTargetConnection).where(
            and_(
                DeploymentTargetConnection.container_id == container_id,
                DeploymentTargetConnection.deployment_target_id == target_id,
            )
        )
    )
    if existing_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Container is already connected to this deployment target",
        )

    # Create connection
    connection = DeploymentTargetConnection(
        project_id=project.id,
        container_id=container_id,
        deployment_target_id=target_id,
    )
    db.add(connection)
    await db.commit()

    logger.info(
        f"Connected container {container.name} to deployment target {target.provider} "
        f"in project {project.slug}"
    )

    return {
        "status": "connected",
        "container_id": str(container_id),
        "target_id": str(target_id),
        "container_name": container.name,
        "provider": target.provider,
    }


@router.delete("/{slug}/deployment-targets/{target_id}/disconnect/{container_id}")
async def disconnect_container_from_target(
    slug: str,
    target_id: UUID,
    container_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """Disconnect a container from a deployment target."""
    project = await get_project_or_404(slug, db, user)
    await get_deployment_target_or_404(target_id, project.id, db)

    # Find and delete connection
    result = await db.execute(
        select(DeploymentTargetConnection).where(
            and_(
                DeploymentTargetConnection.container_id == container_id,
                DeploymentTargetConnection.deployment_target_id == target_id,
            )
        )
    )
    connection = result.scalar_one_or_none()
    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connection not found",
        )

    await db.delete(connection)
    await db.commit()

    logger.info(
        f"Disconnected container {container_id} from deployment target {target_id}"
    )

    return {
        "status": "disconnected",
        "container_id": str(container_id),
        "target_id": str(target_id),
    }


@router.get("/{slug}/deployment-targets/{target_id}/validate/{container_id}")
async def validate_connection(
    slug: str,
    target_id: UUID,
    container_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> ConnectionValidation:
    """Validate if a container can connect to a deployment target."""
    project = await get_project_or_404(slug, db, user)
    target = await get_deployment_target_or_404(target_id, project.id, db)

    # Get container
    container_result = await db.execute(
        select(Container).where(
            and_(Container.id == container_id, Container.project_id == project.id)
        )
    )
    container = container_result.scalar_one_or_none()
    if not container:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Container '{container_id}' not found",
        )

    validation = validate_deployment_connection(
        provider=target.provider,
        container_type=container.container_type,
        service_slug=container.service_slug,
        framework=None,
    )

    return ConnectionValidation(allowed=validation["allowed"], reason=validation["reason"])


# ============================================================================
# Deployment Endpoints
# ============================================================================


@router.post("/{slug}/deployment-targets/{target_id}/deploy")
async def deploy_target(
    slug: str,
    target_id: UUID,
    request: DeployRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """Deploy all connected containers to this deployment target."""
    from ..services.deployment.builder import get_deployment_builder
    from ..services.deployment.manager import DeploymentManager
    from ..services.deployment_encryption import get_deployment_encryption_service
    from .deployments import prepare_provider_credentials

    project = await get_project_or_404(slug, db, user)
    target = await get_deployment_target_or_404(target_id, project.id, db)

    if not request:
        request = DeployRequest()

    # Check if connected
    if not target.is_connected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Please connect your {target.provider} account first",
        )

    # Get connected containers
    connections_result = await db.execute(
        select(DeploymentTargetConnection)
        .options(selectinload(DeploymentTargetConnection.container))
        .where(DeploymentTargetConnection.deployment_target_id == target_id)
    )
    connections = connections_result.scalars().all()

    if not connections:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No containers connected to this deployment target",
        )

    # Get credentials
    credential_result = await db.execute(
        select(DeploymentCredential).where(
            and_(
                DeploymentCredential.user_id == user.id,
                DeploymentCredential.provider == target.provider,
            )
        )
    )
    credential = credential_result.scalar_one_or_none()
    if not credential:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No credentials found for {target.provider}. Please connect your account.",
        )

    # Decrypt credentials
    encryption_service = get_deployment_encryption_service()
    try:
        access_token = encryption_service.decrypt(credential.access_token_encrypted)
    except Exception as e:
        logger.error(f"Failed to decrypt credentials: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to decrypt credentials. Please reconnect your account.",
        )

    # Deploy each connected container
    results = []
    builder = get_deployment_builder()

    # Prepare provider credentials
    provider_metadata = credential.provider_metadata if hasattr(credential, 'provider_metadata') else None
    provider_credentials = prepare_provider_credentials(
        target.provider, access_token, provider_metadata
    )

    # Generate next version number
    version_result = await db.execute(
        select(Deployment)
        .where(Deployment.deployment_target_id == target_id)
        .order_by(desc(Deployment.created_at))
        .limit(1)
    )
    last_deployment = version_result.scalar_one_or_none()
    if last_deployment and last_deployment.version:
        try:
            # Parse version like v1.2.3 -> increment patch
            parts = last_deployment.version.lstrip("v").split(".")
            if len(parts) == 3:
                parts[2] = str(int(parts[2]) + 1)
            version = "v" + ".".join(parts)
        except (ValueError, IndexError):
            version = "v1.0.0"
    else:
        version = "v1.0.0"

    for conn in connections:
        container = conn.container
        if not container:
            continue

        # Create deployment record
        deployment = Deployment(
            project_id=project.id,
            user_id=user.id,
            provider=target.provider,
            deployment_target_id=target.id,
            container_id=container.id,
            version=version,
            status="pending",
            logs=[f"Starting deployment of {container.name} to {target.provider}..."],
        )
        db.add(deployment)
        await db.commit()
        await db.refresh(deployment)

        try:
            # Update status
            deployment.status = "building"
            deployment.logs = deployment.logs + [f"Building {container.name}..."]
            await db.commit()

            # Get deployment config from provider capabilities
            provider_info = get_provider_info(target.provider)
            deployment_mode = provider_info["deployment_mode"] if provider_info else "source"

            # Determine framework from connection settings or auto-detect
            framework = (
                conn.deployment_settings.get("framework")
                if conn.deployment_settings
                else None
            )

            # Build if needed
            if deployment_mode == "pre-built":
                custom_build_cmd = (
                    request.build_command
                    or (conn.deployment_settings.get("build_command") if conn.deployment_settings else None)
                )
                success, build_output = await builder.trigger_build(
                    user_id=str(user.id),
                    project_id=str(project.id),
                    project_slug=project.slug,
                    framework=framework,
                    custom_build_command=custom_build_cmd,
                    container_name=container.name,
                    volume_name=project.slug,
                )
                if not success:
                    raise Exception(f"Build failed: {build_output}")
                deployment.logs = deployment.logs + [f"Build completed: {build_output[:200]}"]

            # Collect files
            deployment.status = "deploying"
            deployment.logs = deployment.logs + ["Collecting deployment files..."]
            await db.commit()

            files = await builder.collect_deployment_files(
                user_id=str(user.id),
                project_id=str(project.id),
                framework=framework,
                collect_source=(deployment_mode == "source"),
                container_directory=container.directory,
                volume_name=project.slug,
            )

            # Deploy to provider
            from ..services.deployment.base import DeploymentConfig

            env_vars = {
                **(request.env_vars or {}),
                **(conn.deployment_settings.get("env_vars", {}) if conn.deployment_settings else {}),
            }

            config = DeploymentConfig(
                project_id=str(project.id),
                project_name=f"{project.slug}-{container.name}",
                framework=framework or "vite",
                deployment_mode=deployment_mode,
                build_command=request.build_command,
                env_vars=env_vars,
            )

            provider = DeploymentManager.get_provider(target.provider, provider_credentials)
            result = await provider.deploy(files, config)

            # Update deployment record
            deployment.status = "success" if result.success else "failed"
            deployment.deployment_id = result.deployment_id
            deployment.deployment_url = result.deployment_url
            deployment.error = result.error
            deployment.logs = deployment.logs + result.logs
            deployment.completed_at = datetime.utcnow()
            await db.commit()

            results.append({
                "container_id": str(container.id),
                "container_name": container.name,
                "status": "success" if result.success else "failed",
                "deployment_id": str(deployment.id),
                "deployment_url": result.deployment_url,
                "error": result.error,
            })

        except Exception as e:
            logger.error(f"Deployment failed for {container.name}: {e}")
            deployment.status = "failed"
            deployment.error = str(e)
            deployment.logs = deployment.logs + [f"Deployment failed: {e}"]
            deployment.completed_at = datetime.utcnow()
            await db.commit()

            results.append({
                "container_id": str(container.id),
                "container_name": container.name,
                "status": "failed",
                "deployment_id": str(deployment.id),
                "error": str(e),
            })

    # Count results
    success_count = sum(1 for r in results if r["status"] == "success")
    failed_count = sum(1 for r in results if r["status"] == "failed")

    return {
        "target_id": str(target_id),
        "provider": target.provider,
        "version": version,
        "total": len(results),
        "success": success_count,
        "failed": failed_count,
        "results": results,
    }


@router.get("/{slug}/deployment-targets/{target_id}/history")
async def get_deployment_history(
    slug: str,
    target_id: UUID,
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> list[DeploymentSummary]:
    """Get deployment history for a target."""
    project = await get_project_or_404(slug, db, user)
    await get_deployment_target_or_404(target_id, project.id, db)

    result = await db.execute(
        select(Deployment)
        .where(Deployment.deployment_target_id == target_id)
        .order_by(desc(Deployment.created_at))
        .offset(offset)
        .limit(limit)
    )
    deployments = result.scalars().all()

    history = []
    for dep in deployments:
        container_name = None
        if dep.container_id:
            c_result = await db.execute(
                select(Container).where(Container.id == dep.container_id)
            )
            c = c_result.scalar_one_or_none()
            if c:
                container_name = c.name
        history.append(
            DeploymentSummary(
                id=dep.id,
                version=dep.version,
                status=dep.status,
                deployment_url=dep.deployment_url,
                container_id=dep.container_id,
                container_name=container_name,
                created_at=dep.created_at.isoformat() if dep.created_at else "",
                completed_at=dep.completed_at.isoformat() if dep.completed_at else None,
            )
        )

    return history


@router.post("/{slug}/deployment-targets/{target_id}/rollback/{deployment_id}")
async def rollback_deployment(
    slug: str,
    target_id: UUID,
    deployment_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """Rollback to a previous deployment version."""
    project = await get_project_or_404(slug, db, user)
    target = await get_deployment_target_or_404(target_id, project.id, db)

    # Get the deployment to rollback to
    result = await db.execute(
        select(Deployment).where(
            and_(
                Deployment.id == deployment_id,
                Deployment.deployment_target_id == target_id,
            )
        )
    )
    deployment = result.scalar_one_or_none()
    if not deployment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deployment '{deployment_id}' not found",
        )

    if deployment.status != "success":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only rollback to successful deployments",
        )

    # For now, trigger a new deployment with the same settings
    # In the future, we could implement provider-specific rollback APIs
    logger.info(
        f"Rolling back to deployment {deployment_id} (version {deployment.version}) "
        f"for target {target.provider}"
    )

    # Create a new deployment that references the rollback
    new_deployment = Deployment(
        project_id=project.id,
        user_id=user.id,
        provider=target.provider,
        deployment_target_id=target.id,
        container_id=deployment.container_id,
        version=f"{deployment.version}-rollback",
        status="pending",
        logs=[f"Rolling back to version {deployment.version}..."],
        deployment_metadata={"rollback_from": str(deployment_id)},
    )
    db.add(new_deployment)
    await db.commit()
    await db.refresh(new_deployment)

    # TODO: Implement actual rollback using provider APIs
    # For now, we mark it as requiring manual action
    new_deployment.status = "pending"
    new_deployment.logs.append(
        "Rollback initiated. Provider-specific rollback will be implemented in a future release."
    )
    await db.commit()

    return {
        "status": "rollback_initiated",
        "target_id": str(target_id),
        "deployment_id": str(new_deployment.id),
        "rollback_to_version": deployment.version,
        "message": "Rollback deployment created. Full provider rollback support coming soon.",
    }


