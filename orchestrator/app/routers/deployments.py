"""
Deployments API Router.

This module provides API endpoints for deploying projects to various providers
(Cloudflare Workers, Vercel, Netlify, etc.) with support for builds, status tracking,
and deployment management.
"""

import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Container, Deployment, DeploymentCredential, Project, User
from ..services.deployment.base import (
    ENV_CPU,
    ENV_IMAGE_REF,
    ENV_MEMORY,
    ENV_PORT,
    ENV_REGION,
    ENV_REPO_URL,
    INTERNAL_ENV_PREFIX,
    BaseDeploymentProvider,
    DeploymentConfig,
    DeploymentResult,
)
from ..services.deployment.builder import BuildError, get_deployment_builder
from ..services.deployment.container_base import BaseContainerDeploymentProvider, ContainerDeployConfig
from ..services.deployment.manager import DeploymentManager
from ..services.deployment_encryption import (
    DeploymentEncryptionError,
    get_deployment_encryption_service,
)
from ..services.orchestration import get_orchestrator
from ..users import current_active_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/deployments", tags=["deployments"])


# ============================================================================
# Request/Response Models
# ============================================================================


class DeploymentRequest(BaseModel):
    """Request to deploy a project."""

    provider: str = Field(..., description="Deployment provider (cloudflare, vercel, netlify)")
    deployment_mode: str | None = Field(
        None,
        description="Deployment mode: 'source' (provider builds) or 'pre-built' (upload built files). Default varies by provider.",
    )
    custom_domain: str | None = Field(None, description="Custom domain")
    env_vars: dict[str, str] = Field(default_factory=dict, description="Environment variables")
    build_command: str | None = Field(None, description="Build command override (primary source is container.build_command)")
    framework: str | None = Field(
        None, description="Framework override (primary source is container.framework)"
    )


class DeploymentResponse(BaseModel):
    """Response containing deployment information."""

    id: UUID
    project_id: UUID
    user_id: UUID
    provider: str
    deployment_id: str | None
    deployment_url: str | None
    status: str
    logs: list[str] | None
    error: str | None
    created_at: str
    updated_at: str
    completed_at: str | None

    class Config:
        from_attributes = True


class DeploymentStatusResponse(BaseModel):
    """Response for deployment status check."""

    status: str
    deployment_url: str | None
    provider_status: dict | None
    updated_at: str


class DeployAllResult(BaseModel):
    """Result for a single container deployment in deploy_all."""
    container_id: UUID
    container_name: str
    provider: str
    status: str  # 'success' | 'failed' | 'skipped'
    deployment_id: UUID | None = None
    deployment_url: str | None = None
    error: str | None = None


class DeployAllResponse(BaseModel):
    """Response for deploy_all endpoint."""
    total: int
    deployed: int
    failed: int
    skipped: int
    results: list[DeployAllResult]


# ============================================================================
# Helper Functions
# ============================================================================


def resolve_container_directory(container) -> str:
    """
    Resolve the actual on-disk working directory for a container.

    Must match compute_manager.resolve_k8s_container_dir / helpers.py logic:
    - directory="." or "" or None → working_dir is /app (return ".")
    - directory="frontend"       → working_dir is /app/frontend/

    Both Docker and K8s agree: "." means project root (/app).
    """
    if container.directory not in (".", "", None):
        raw = container.directory
    else:
        return "."

    # Replicate _sanitize_name from KubernetesOrchestrator
    safe = raw.lower().replace(" ", "-").replace("_", "-").replace(".", "-")
    safe = "".join(c for c in safe if c.isalnum() or c == "-")
    while "--" in safe:
        safe = safe.replace("--", "-")
    safe = safe.strip("-")
    return safe[:59]


async def get_credential_for_deployment(
    db: AsyncSession, user_id: UUID, project_id: UUID, provider: str
) -> DeploymentCredential:
    """
    Get deployment credential for a project, with support for project overrides.

    First checks for a project-specific credential, then falls back to user default.

    Args:
        db: Database session
        user_id: User ID
        project_id: Project ID
        provider: Provider name

    Returns:
        DeploymentCredential

    Raises:
        HTTPException: If no credential is found
    """
    # First try to get project-specific credential
    result = await db.execute(
        select(DeploymentCredential).where(
            and_(
                DeploymentCredential.user_id == user_id,
                DeploymentCredential.provider == provider,
                DeploymentCredential.project_id == project_id,
            )
        )
    )
    credential = result.scalar_one_or_none()

    if credential:
        logger.debug(f"Using project-specific credential for {provider}")
        return credential

    # Fall back to user default credential
    result = await db.execute(
        select(DeploymentCredential).where(
            and_(
                DeploymentCredential.user_id == user_id,
                DeploymentCredential.provider == provider,
                DeploymentCredential.project_id.is_(None),
            )
        )
    )
    credential = result.scalar_one_or_none()

    if not credential:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No credentials found for {provider}. Please connect your account in settings.",
        )

    logger.debug(f"Using default user credential for {provider}")
    return credential


def prepare_provider_credentials(
    provider: str, decrypted_token: str, metadata: dict | None
) -> dict[str, str]:
    """
    Prepare credentials dict for a provider.

    Delegates to the canonical credential builder in deployment_credentials
    to keep all 22 providers' field mappings in one place.

    Args:
        provider: Provider name
        decrypted_token: Decrypted access token
        metadata: Credential metadata

    Returns:
        Provider-specific credentials dict
    """
    from .deployment_credentials import _build_provider_credentials

    return _build_provider_credentials(provider, decrypted_token, metadata)


# ============================================================================
# Container-provider deploy helper
# ============================================================================


async def _execute_provider_deploy(
    provider_instance: BaseDeploymentProvider,
    provider_name: str,
    files: list,
    config: DeploymentConfig,
    container: "Container | None" = None,
) -> "DeploymentResult":
    """
    Execute deployment, routing container providers through push_image + deploy_image.

    Source/file-based providers go through the normal .deploy() path.
    Container-push providers (aws-apprunner, gcp-cloudrun, azure-container-apps,
    do-container, fly) are routed through push_image → deploy_image instead.
    """
    if DeploymentManager.is_container_provider(provider_name) and isinstance(
        provider_instance, BaseContainerDeploymentProvider
    ):
        # Derive image ref from env_vars or project name
        image_ref = config.env_vars.get(ENV_IMAGE_REF) or f"{config.project_name}:latest"
        port = int(
            config.env_vars.get(ENV_PORT)
            or (str(container.internal_port) if container and container.internal_port else "8080")
        )

        container_config = ContainerDeployConfig(
            image_ref=image_ref,
            port=port,
            cpu=config.env_vars.get(ENV_CPU, "0.25"),
            memory=config.env_vars.get(ENV_MEMORY, "512Mi"),
            env_vars={
                k: v
                for k, v in config.env_vars.items()
                if not k.startswith(INTERNAL_ENV_PREFIX)
            },
            region=config.env_vars.get(ENV_REGION, "us-east-1"),
        )

        pushed_uri = await provider_instance.push_image(container_config.image_ref)
        container_config = ContainerDeployConfig(
            **{**container_config.model_dump(), "image_ref": pushed_uri}
        )
        return await provider_instance.deploy_image(container_config)

    # File/source-based providers
    return await provider_instance.deploy(files, config)


# ============================================================================
# API Endpoints
# ============================================================================


@router.post("/{project_slug}/deploy", response_model=DeploymentResponse)
async def deploy_project(
    project_slug: str,
    request: DeploymentRequest,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Deploy a project to a provider.

    This endpoint handles the complete deployment flow:
    1. Verify project ownership
    2. Fetch and decrypt credentials
    3. Run build in container
    4. Collect built files
    5. Deploy to provider
    6. Save deployment record

    Args:
        project_slug: Project slug
        request: Deployment request
        current_user: Current authenticated user
        db: Database session

    Returns:
        Deployment information
    """
    deployment = None

    try:
        # 1. Verify project ownership
        result = await db.execute(
            select(Project).where(
                and_(Project.slug == project_slug, Project.owner_id == current_user.id)
            )
        )
        project = result.scalar_one_or_none()

        if not project:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

        # 2. Fetch credentials
        provider_lower = request.provider.lower()
        credential = await get_credential_for_deployment(
            db, current_user.id, project.id, provider_lower
        )

        # 3. Decrypt credentials
        encryption_service = get_deployment_encryption_service()
        decrypted_token = encryption_service.decrypt(credential.access_token_encrypted)
        provider_credentials = prepare_provider_credentials(
            provider_lower, decrypted_token, credential.provider_metadata
        )

        # 4. Create deployment record (status: building)
        deployment = Deployment(
            project_id=project.id,
            user_id=current_user.id,
            provider=provider_lower,
            status="building",
            logs=["Deployment started"],
            deployment_metadata={},
        )
        db.add(deployment)
        await db.commit()
        await db.refresh(deployment)

        logger.info(f"Created deployment {deployment.id} for project {project.slug}")

        # 5. Get builder
        builder = get_deployment_builder()

        # 6. Determine deployment mode (source vs pre-built)
        # Default modes per provider:
        # - Vercel: source (has Git/CLI integration for builds)
        # - Cloudflare: pre-built (upload to Workers)
        # - Netlify: pre-built (file upload API doesn't trigger builds)
        deployment_mode = request.deployment_mode
        if not deployment_mode:
            # Set sensible defaults per provider
            default_modes = {"vercel": "source", "netlify": "pre-built", "cloudflare": "pre-built"}
            deployment_mode = default_modes.get(provider_lower, "pre-built")
            deployment.logs.append(
                f"Using default deployment mode for {provider_lower}: {deployment_mode}"
            )
        else:
            deployment.logs.append(f"Using requested deployment mode: {deployment_mode}")
        await db.commit()

        # 7. Find the primary container for multi-container projects
        result = await db.execute(
            select(Container)
            .where(Container.project_id == project.id)
            .order_by(Container.created_at.asc())
        )
        containers = result.scalars().all()

        # Determine which container to build in
        build_container_name = None
        build_directory = None

        if containers:
            # Multi-container project - use the first container (or find the frontend/main one)
            # TODO: Add logic to identify the primary/frontend container
            primary_container = containers[0]
            build_container_name = primary_container.container_name
            build_directory = resolve_container_directory(primary_container)

            deployment.logs.append(
                f"Multi-container project: building in container '{primary_container.name}' ({build_container_name})"
            )
            logger.info(
                f"Using container {build_container_name} for build (directory: {build_directory})"
            )
        else:
            # Single-container project (legacy)
            deployment.logs.append("Single-container project")
            logger.info("Single-container project - using legacy container management")

        await db.commit()

        # 8. Ensure dev container is running
        if build_container_name:
            # For multi-container projects, verify the specific container is running
            deployment.logs.append(f"Verifying container {build_container_name} is running")
            await db.commit()

            # Use orchestrator to check container status (works with both Docker and Kubernetes)
            orchestrator = get_orchestrator()
            container_status = await orchestrator.get_container_status(
                project_slug=project.slug,
                project_id=project.id,
                container_name=build_container_name,
                user_id=current_user.id
            )

            is_running = container_status.get("status") == "running"

            if not is_running:
                error_msg = f"Container {build_container_name} is not running. Please start your project containers first."
                deployment.status = "failed"
                deployment.error = error_msg
                deployment.completed_at = datetime.utcnow()
                await db.commit()
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)

            deployment.logs.append(f"Container {build_container_name} is running")
            await db.commit()
        else:
            # No containers found - all projects must use multi-container system
            error_msg = "Project has no containers. Please add containers to your project using the graph canvas."
            logger.error(f"Deployment failed: {error_msg}")
            deployment.status = "failed"
            deployment.error = error_msg
            deployment.completed_at = datetime.utcnow()
            await db.commit()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)

        # Resolve framework from container fields, with request override
        framework = request.framework or primary_container.framework or "static"

        # 8. Run build (skip if source mode - provider will build)
        use_source_deployment = deployment_mode == "source"

        # Resolve build command: request override > container field
        effective_build_command = request.build_command or primary_container.build_command

        if use_source_deployment:
            deployment.logs.append(
                f"Skipping local build - {provider_lower} will build remotely (framework: {framework})"
            )
            await db.commit()
        else:
            deployment.logs.append(f"Building project locally (framework: {framework})")
            await db.commit()

            try:
                success, build_output = await builder.trigger_build(
                    user_id=str(current_user.id),
                    project_id=str(project.id),
                    project_slug=project.slug,
                    framework=framework,
                    custom_build_command=effective_build_command,
                    container_name=build_container_name,
                    volume_name=project.slug,
                    container_directory=build_directory,
                    deployment_mode=deployment_mode,
                    volume_id=project.volume_id,
                    cache_node=project.cache_node,
                )

                if not success:
                    raise BuildError("Build failed")

                deployment.logs.append("Build completed successfully")
                await db.commit()

            except BuildError as e:
                deployment.status = "failed"
                deployment.error = f"Build failed: {str(e)}"
                deployment.completed_at = datetime.utcnow()
                await db.commit()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=f"Build failed: {str(e)}"
                ) from e

        # 9. Collect files
        if use_source_deployment:
            deployment.logs.append("Collecting source files for remote build")
        else:
            deployment.logs.append("Collecting built files")
        deployment.status = "deploying"
        await db.commit()

        files = await builder.collect_deployment_files(
            user_id=str(current_user.id),
            project_id=str(project.id),
            framework=framework,
            custom_output_dir=primary_container.output_directory,
            collect_source=use_source_deployment,
            container_directory=build_directory,
            volume_name=project.slug,
            container_name=build_container_name,
            volume_id=project.volume_id,
        )

        deployment.logs.append(f"Collected {len(files)} files")
        await db.commit()

        # 10. Deploy to provider
        deployment.logs.append(f"Deploying to {provider_lower}")
        await db.commit()

        config = DeploymentConfig(
            project_id=str(project.id),
            project_name=project.name,
            framework=framework,
            deployment_mode=deployment_mode,
            build_command=effective_build_command,
            env_vars=request.env_vars,
            custom_domain=request.custom_domain,
        )

        provider = DeploymentManager.get_provider(provider_lower, provider_credentials)
        result = await _execute_provider_deploy(
            provider, provider_lower, files, config, container=primary_container
        )

        # 11. Update deployment record
        if result.success:
            deployment.status = "success"
            deployment.deployment_id = result.deployment_id
            deployment.deployment_url = result.deployment_url
            # For JSON fields, we need to create a new list to trigger SQLAlchemy's change detection
            deployment.logs = deployment.logs + result.logs
            deployment.deployment_metadata = result.metadata
            deployment.completed_at = datetime.utcnow()

            logger.info(f"Deployment {deployment.id} succeeded: {result.deployment_url}")
        else:
            deployment.status = "failed"
            deployment.error = result.error
            # For JSON fields, we need to create a new list to trigger SQLAlchemy's change detection
            deployment.logs = deployment.logs + result.logs
            deployment.completed_at = datetime.utcnow()

            # Extract deployment_id from metadata if available (for failed deployments)
            if result.metadata and "deployment_id" in result.metadata:
                deployment.deployment_id = result.metadata["deployment_id"]

            # Try to get deployment_url if it's in metadata
            if result.deployment_url:
                deployment.deployment_url = result.deployment_url

            logger.error(f"Deployment {deployment.id} failed: {result.error}")

        await db.commit()
        await db.refresh(deployment)

        # Return response
        return DeploymentResponse(
            id=deployment.id,
            project_id=deployment.project_id,
            user_id=deployment.user_id,
            provider=deployment.provider,
            deployment_id=deployment.deployment_id,
            deployment_url=deployment.deployment_url,
            status=deployment.status,
            logs=deployment.logs,
            error=deployment.error,
            created_at=deployment.created_at.isoformat(),
            updated_at=deployment.updated_at.isoformat(),
            completed_at=deployment.completed_at.isoformat() if deployment.completed_at else None,
        )

    except HTTPException:
        raise
    except DeploymentEncryptionError as e:
        logger.error(f"Encryption error: {e}", exc_info=True)
        if deployment:
            deployment.status = "failed"
            deployment.error = "Failed to decrypt credentials"
            deployment.completed_at = datetime.utcnow()
            await db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to decrypt credentials",
        ) from e
    except Exception as e:
        logger.error(f"Deployment failed: {e}", exc_info=True)
        if deployment:
            deployment.status = "failed"
            deployment.error = str(e)
            deployment.completed_at = datetime.utcnow()
            await db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Deployment failed: {str(e)}"
        ) from e


@router.post("/{project_slug}/deploy-all", response_model=DeployAllResponse)
async def deploy_all_containers(
    project_slug: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Deploy all containers that have deployment targets assigned.

    This endpoint:
    1. Finds all containers with deployment_provider set
    2. Validates credentials exist for each provider
    3. Deploys containers in parallel (non-blocking)
    4. Returns aggregated results

    Only base containers with deployment targets are deployed.
    Service containers (databases, caches) are skipped.
    """
    import asyncio

    from sqlalchemy.orm import selectinload

    # 1. Verify project ownership
    result = await db.execute(
        select(Project).where(
            and_(
                Project.slug == project_slug,
                Project.owner_id == current_user.id
            )
        )
    )
    project = result.scalar_one_or_none()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )

    # 2. Get all containers with deployment targets
    result = await db.execute(
        select(Container)
        .where(
            and_(
                Container.project_id == project.id,
                Container.deployment_provider.isnot(None)
            )
        )
        .options(selectinload(Container.base))
    )
    containers_with_targets = result.scalars().all()

    if not containers_with_targets:
        return DeployAllResponse(
            total=0,
            deployed=0,
            failed=0,
            skipped=0,
            results=[]
        )

    # 3. Group containers by provider to validate credentials
    providers_needed = {c.deployment_provider for c in containers_with_targets}
    encryption_service = get_deployment_encryption_service()

    # Validate credentials for each provider
    provider_credentials = {}
    for provider in providers_needed:
        try:
            credential = await get_credential_for_deployment(
                db, current_user.id, project.id, provider
            )
            decrypted_token = encryption_service.decrypt(credential.access_token_encrypted)
            provider_credentials[provider] = {
                "token": decrypted_token,
                "metadata": credential.provider_metadata,
                "credential": credential
            }
        except HTTPException:
            # Credential not found for this provider - will mark containers as failed
            provider_credentials[provider] = None

    # 4. Deploy each container (non-blocking parallel deployment)
    results = []

    async def deploy_single_container(container: Container) -> DeployAllResult:
        """Deploy a single container to its assigned provider."""
        provider = container.deployment_provider

        # Check if we have credentials
        if provider_credentials.get(provider) is None:
            return DeployAllResult(
                container_id=container.id,
                container_name=container.name,
                provider=provider,
                status="failed",
                error=f"No credentials found for {provider}. Please connect your {provider} account in Settings."
            )

        # Skip service containers (databases, caches, etc.)
        if container.container_type != "base":
            return DeployAllResult(
                container_id=container.id,
                container_name=container.name,
                provider=provider,
                status="skipped",
                error="Service containers cannot be deployed to external providers"
            )

        try:
            # Create deployment record
            deployment = Deployment(
                project_id=project.id,
                user_id=current_user.id,
                provider=provider,
                status="building",
                logs=[f"Deploy-all: Deploying {container.name} to {provider}"],
                deployment_metadata={"container_id": str(container.id), "container_name": container.name}
            )
            db.add(deployment)
            await db.commit()
            await db.refresh(deployment)

            # Get builder and framework from container fields
            builder = get_deployment_builder()
            framework = container.framework or "static"

            # Determine deployment mode
            default_modes = {
                "vercel": "source",
                "netlify": "pre-built",
                "cloudflare": "pre-built"
            }
            deployment_mode = default_modes.get(provider, "pre-built")

            # Build if needed
            resolved_directory = resolve_container_directory(container)
            if deployment_mode == "pre-built":
                deployment.logs.append(f"Building {container.name} locally...")
                await db.commit()

                success, build_output = await builder.trigger_build(
                    user_id=str(current_user.id),
                    project_id=str(project.id),
                    project_slug=project.slug,
                    framework=framework,
                    custom_build_command=container.build_command,
                    container_name=container.container_name,
                    volume_name=project.slug,
                    container_directory=resolved_directory,
                    deployment_mode=deployment_mode,
                    volume_id=project.volume_id,
                    cache_node=project.cache_node,
                )

                if not success:
                    deployment.status = "failed"
                    deployment.error = "Build failed"
                    deployment.logs.append(f"Build failed: {build_output[:500]}")
                    deployment.completed_at = datetime.utcnow()
                    await db.commit()

                    return DeployAllResult(
                        container_id=container.id,
                        container_name=container.name,
                        provider=provider,
                        status="failed",
                        deployment_id=deployment.id,
                        error="Build failed"
                    )

            # Deploy to provider
            deployment.logs.append(f"Deploying to {provider}...")
            deployment.status = "deploying"
            await db.commit()

            creds = provider_credentials[provider]
            prepared_creds = prepare_provider_credentials(
                provider, creds["token"], creds["metadata"]
            )

            # Auto-derive git repo URL for source-mode providers
            deploy_env_vars: dict[str, str] = {}
            if deployment_mode == "source" and project.git_remote_url:
                deploy_env_vars[ENV_REPO_URL] = project.git_remote_url

            config = DeploymentConfig(
                project_id=str(project.id),
                project_name=f"{project.slug}-{container.name}",
                framework=framework,
                deployment_mode=deployment_mode,
                env_vars=deploy_env_vars,
            )

            provider_instance = DeploymentManager.get_provider(provider, prepared_creds)

            # Collect files for deployment (skipped internally for container providers)
            files = await builder.collect_deployment_files(
                user_id=str(current_user.id),
                project_id=str(project.id),
                framework=framework,
                custom_output_dir=container.output_directory,
                collect_source=(deployment_mode == "source"),
                container_directory=resolved_directory,
                volume_name=project.slug,
                container_name=container.container_name,
                volume_id=project.volume_id,
            )

            deploy_result = await _execute_provider_deploy(
                provider_instance, provider, files, config, container=container
            )

            # Update deployment record
            deployment.status = "success" if deploy_result.success else "failed"
            deployment.deployment_id = deploy_result.deployment_id
            deployment.deployment_url = deploy_result.deployment_url
            deployment.error = deploy_result.error
            deployment.logs.extend(deploy_result.logs or [])
            deployment.completed_at = datetime.utcnow()
            await db.commit()

            return DeployAllResult(
                container_id=container.id,
                container_name=container.name,
                provider=provider,
                status="success" if deploy_result.success else "failed",
                deployment_id=deployment.id,
                deployment_url=deploy_result.deployment_url,
                error=deploy_result.error
            )

        except Exception as e:
            logger.error(f"Failed to deploy container {container.name}: {e}", exc_info=True)
            return DeployAllResult(
                container_id=container.id,
                container_name=container.name,
                provider=provider,
                status="failed",
                error=str(e)
            )

    # Run deployments in parallel
    deployment_tasks = [deploy_single_container(c) for c in containers_with_targets]
    results = await asyncio.gather(*deployment_tasks)

    # Calculate summary
    deployed = sum(1 for r in results if r.status == "success")
    failed = sum(1 for r in results if r.status == "failed")
    skipped = sum(1 for r in results if r.status == "skipped")

    logger.info(f"Deploy-all completed for {project.slug}: {deployed} deployed, {failed} failed, {skipped} skipped")

    return DeployAllResponse(
        total=len(results),
        deployed=deployed,
        failed=failed,
        skipped=skipped,
        results=results
    )


class ContainerDeployRequest(BaseModel):
    """Request to deploy a project via container-push (ECR, Cloud Run, etc.)."""

    provider: str = Field(..., description="Container-push provider name")
    container_id: UUID | None = Field(
        None, description="Specific container to deploy (uses primary if omitted)"
    )
    port: int = Field(default=8080, description="Container port to expose")
    cpu: str = Field(default="0.25", description="CPU allocation")
    memory: str = Field(default="512Mi", description="Memory allocation")
    region: str = Field(default="us-east-1", description="Deploy region")
    env_vars: dict[str, str] = Field(default_factory=dict, description="Environment variables")


class ExportRequest(BaseModel):
    """Request to export a project image (Docker Hub, GHCR, Download)."""

    provider: str = Field(..., description="Export provider name (dockerhub, ghcr, download)")
    container_id: UUID | None = Field(
        None, description="Specific container to export (uses primary if omitted)"
    )
    image_name: str | None = Field(None, description="Target image name override")
    tag: str = Field(default="latest", description="Image tag")


class ExportResponse(BaseModel):
    """Response containing export information."""

    id: UUID
    project_id: UUID
    provider: str
    status: str
    image_ref: str | None = None
    pull_command: str | None = None
    download_url: str | None = None
    logs: list[str] | None = None
    error: str | None = None
    created_at: str
    completed_at: str | None = None


@router.post("/{project_slug}/deploy-container", response_model=DeploymentResponse)
async def deploy_container(
    project_slug: str,
    request: ContainerDeployRequest,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Deploy a project via container-push (export image, push to registry, deploy to compute).

    For container-push providers: AWS App Runner, GCP Cloud Run, Azure Container Apps,
    DigitalOcean App Platform (container), Fly.io.

    Flow:
    1. Verify project and container are running
    2. Resolve credentials
    3. Call provider.push_image() to push to provider's registry
    4. Call provider.deploy_image() to create/update compute service
    5. Return deployment result with live URL
    """
    deployment = None

    try:
        # 1. Validate this is a container-push provider
        provider_lower = request.provider.lower()
        if not DeploymentManager.is_container_provider(provider_lower):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"'{request.provider}' is not a container-push provider. "
                "Use POST /deploy for source-push providers or POST /export for export providers.",
            )

        # 2. Verify project ownership
        result = await db.execute(
            select(Project).where(
                and_(Project.slug == project_slug, Project.owner_id == current_user.id)
            )
        )
        project = result.scalar_one_or_none()
        if not project:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

        # 3. Get the target container
        if request.container_id:
            result = await db.execute(
                select(Container).where(
                    and_(Container.id == request.container_id, Container.project_id == project.id)
                )
            )
        else:
            result = await db.execute(
                select(Container)
                .where(Container.project_id == project.id)
                .order_by(Container.created_at.asc())
            )
        container = result.scalars().first()
        if not container:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No containers found for this project.",
            )

        # 4. Check that container is running
        orchestrator = get_orchestrator()
        container_status = await orchestrator.get_container_status(
            project_slug=project.slug,
            project_id=project.id,
            container_name=container.container_name,
            user_id=current_user.id,
        )
        if container_status.get("status") != "running":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Container must be running to export. Start the project first.",
            )

        # 5. Fetch and decrypt credentials
        credential = await get_credential_for_deployment(
            db, current_user.id, project.id, provider_lower
        )
        encryption_service = get_deployment_encryption_service()
        decrypted_token = encryption_service.decrypt(credential.access_token_encrypted)
        provider_credentials = prepare_provider_credentials(
            provider_lower, decrypted_token, credential.provider_metadata
        )

        # 6. Create deployment record
        deployment = Deployment(
            project_id=project.id,
            user_id=current_user.id,
            provider=provider_lower,
            status="pushing",
            logs=[f"Container deploy to {provider_lower} started"],
            deployment_metadata={
                "container_id": str(container.id),
                "container_name": container.name,
                "deploy_type": "container",
            },
        )
        db.add(deployment)
        await db.commit()
        await db.refresh(deployment)

        # 7. Get container-push provider
        from ..services.deployment.container_base import (
            BaseContainerDeploymentProvider,
            ContainerDeployConfig,
        )

        provider = DeploymentManager.get_provider(provider_lower, provider_credentials)
        if not isinstance(provider, BaseContainerDeploymentProvider):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Provider {provider_lower} is registered as container but doesn't implement container interface.",
            )

        # 8. Push image to registry
        image_name = f"{project.slug}-{container.name}"
        image_ref = f"{image_name}:latest"
        deployment.logs = [*deployment.logs, f"Pushing image {image_ref} to registry..."]
        await db.commit()

        pushed_uri = await provider.push_image(image_ref)
        deployment.logs = [*deployment.logs, f"Image pushed: {pushed_uri}"]
        await db.commit()

        # 9. Deploy image to compute
        deployment.status = "deploying"
        deployment.logs = [*deployment.logs, "Deploying image to compute service..."]
        await db.commit()

        # Filter out internal env vars
        env_vars = {k: v for k, v in request.env_vars.items() if not k.startswith(INTERNAL_ENV_PREFIX)}

        container_config = ContainerDeployConfig(
            image_ref=pushed_uri,
            port=request.port,
            cpu=request.cpu,
            memory=request.memory,
            env_vars=env_vars,
            region=request.region,
        )

        deploy_result = await provider.deploy_image(container_config)

        # 10. Update deployment record
        deployment.status = "success" if deploy_result.success else "failed"
        deployment.deployment_id = deploy_result.deployment_id
        deployment.deployment_url = deploy_result.deployment_url
        deployment.error = deploy_result.error
        deployment.logs = [*deployment.logs, *(deploy_result.logs or [])]
        deployment.deployment_metadata = {
            **(deployment.deployment_metadata or {}),
            **(deploy_result.metadata or {}),
        }
        deployment.completed_at = datetime.utcnow()
        await db.commit()
        await db.refresh(deployment)

        return DeploymentResponse(
            id=deployment.id,
            project_id=deployment.project_id,
            user_id=deployment.user_id,
            provider=deployment.provider,
            deployment_id=deployment.deployment_id,
            deployment_url=deployment.deployment_url,
            status=deployment.status,
            logs=deployment.logs,
            error=deployment.error,
            created_at=deployment.created_at.isoformat(),
            updated_at=deployment.updated_at.isoformat(),
            completed_at=deployment.completed_at.isoformat() if deployment.completed_at else None,
        )

    except HTTPException:
        raise
    except DeploymentEncryptionError as e:
        logger.error(f"Encryption error in deploy-container: {e}", exc_info=True)
        if deployment:
            deployment.status = "failed"
            deployment.error = "Failed to decrypt credentials"
            deployment.completed_at = datetime.utcnow()
            await db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to decrypt credentials",
        ) from e
    except Exception as e:
        logger.error(f"Container deployment failed: {e}", exc_info=True)
        if deployment:
            deployment.status = "failed"
            deployment.error = str(e)
            deployment.completed_at = datetime.utcnow()
            await db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Container deployment failed: {str(e)}",
        ) from e


@router.post("/{project_slug}/export", response_model=ExportResponse)
async def export_project(
    project_slug: str,
    request: ExportRequest,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Export a project image to a registry or as a downloadable archive.

    For export providers: Docker Hub, GHCR, Download.

    Flow:
    1. Verify project
    2. For dockerhub/ghcr: push image to registry, return pull command
    3. For download: collect files, create ZIP archive, return download info
    """
    deployment = None

    try:
        # 1. Validate this is an export provider
        provider_lower = request.provider.lower()
        if not DeploymentManager.is_export_provider(provider_lower):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"'{request.provider}' is not an export provider. "
                "Use POST /deploy for source-push or POST /deploy-container for container-push.",
            )

        # 2. Verify project ownership
        result = await db.execute(
            select(Project).where(
                and_(Project.slug == project_slug, Project.owner_id == current_user.id)
            )
        )
        project = result.scalar_one_or_none()
        if not project:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

        # 3. Get the target container
        if request.container_id:
            result = await db.execute(
                select(Container).where(
                    and_(Container.id == request.container_id, Container.project_id == project.id)
                )
            )
        else:
            result = await db.execute(
                select(Container)
                .where(Container.project_id == project.id)
                .order_by(Container.created_at.asc())
            )
        container = result.scalars().first()
        if not container:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No containers found for this project.",
            )

        # 4. Fetch credentials (skip for download provider)
        provider_credentials: dict[str, str] = {}
        if provider_lower != "download":
            credential = await get_credential_for_deployment(
                db, current_user.id, project.id, provider_lower
            )
            encryption_service = get_deployment_encryption_service()
            decrypted_token = encryption_service.decrypt(credential.access_token_encrypted)
            provider_credentials = prepare_provider_credentials(
                provider_lower, decrypted_token, credential.provider_metadata
            )

        # 5. Create deployment record
        deployment = Deployment(
            project_id=project.id,
            user_id=current_user.id,
            provider=provider_lower,
            status="exporting",
            logs=[f"Export to {provider_lower} started"],
            deployment_metadata={
                "container_id": str(container.id),
                "container_name": container.name,
                "deploy_type": "export",
            },
        )
        db.add(deployment)
        await db.commit()
        await db.refresh(deployment)

        # 6. Get provider instance
        provider = DeploymentManager.get_provider(provider_lower, provider_credentials)

        # 7. Handle based on provider type
        if provider_lower == "download":
            # Download export: collect files and create ZIP
            builder = get_deployment_builder()
            resolved_directory = resolve_container_directory(container)
            framework = container.framework or "static"

            files = await builder.collect_deployment_files(
                user_id=str(current_user.id),
                project_id=str(project.id),
                framework=framework,
                custom_output_dir=container.output_directory,
                collect_source=True,
                container_directory=resolved_directory,
                volume_name=project.slug,
                container_name=container.container_name,
                volume_id=project.volume_id,
            )

            config = DeploymentConfig(
                project_id=str(project.id),
                project_name=f"{project.slug}-{container.name}",
                framework=framework,
                deployment_mode="pre-built",
            )

            deploy_result = await provider.deploy(files, config)
        else:
            # Registry export (dockerhub, ghcr): push image
            if not isinstance(provider, BaseContainerDeploymentProvider):
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Provider {provider_lower} doesn't implement container push interface.",
                )

            # Check container is running for image-based export
            orchestrator = get_orchestrator()
            container_status_result = await orchestrator.get_container_status(
                project_slug=project.slug,
                project_id=project.id,
                container_name=container.container_name,
                user_id=current_user.id,
            )
            if container_status_result.get("status") != "running":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Container must be running to export. Start the project first.",
                )

            image_name = request.image_name or f"{project.slug}-{container.name}"
            image_ref = f"{image_name}:{request.tag}"

            deployment.logs = [*deployment.logs, f"Pushing image {image_ref}..."]
            await db.commit()

            pushed_uri = await provider.push_image(image_ref)

            # For export providers, deploy_image returns metadata (pull command, etc.)
            container_config = ContainerDeployConfig(
                image_ref=pushed_uri,
                port=container.internal_port or 8080,
            )
            deploy_result = await provider.deploy_image(container_config)

        # 8. Update deployment record
        deployment.status = "success" if deploy_result.success else "failed"
        deployment.deployment_id = deploy_result.deployment_id
        deployment.deployment_url = deploy_result.deployment_url
        deployment.error = deploy_result.error
        deployment.logs = [*deployment.logs, *(deploy_result.logs or [])]
        deployment.deployment_metadata = {
            **(deployment.deployment_metadata or {}),
            **(deploy_result.metadata or {}),
        }
        deployment.completed_at = datetime.utcnow()
        await db.commit()
        await db.refresh(deployment)

        result_meta = deploy_result.metadata or {}
        return ExportResponse(
            id=deployment.id,
            project_id=deployment.project_id,
            provider=deployment.provider,
            status=deployment.status,
            image_ref=result_meta.get("image_ref"),
            pull_command=result_meta.get("pull_command"),
            download_url=result_meta.get("download_url"),
            logs=deployment.logs,
            error=deployment.error,
            created_at=deployment.created_at.isoformat(),
            completed_at=deployment.completed_at.isoformat() if deployment.completed_at else None,
        )

    except HTTPException:
        raise
    except DeploymentEncryptionError as e:
        logger.error(f"Encryption error in export: {e}", exc_info=True)
        if deployment:
            deployment.status = "failed"
            deployment.error = "Failed to decrypt credentials"
            deployment.completed_at = datetime.utcnow()
            await db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to decrypt credentials",
        ) from e
    except Exception as e:
        logger.error(f"Export failed: {e}", exc_info=True)
        if deployment:
            deployment.status = "failed"
            deployment.error = str(e)
            deployment.completed_at = datetime.utcnow()
            await db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Export failed: {str(e)}",
        ) from e


@router.post("/{project_slug}/containers/{container_id}/deploy", response_model=DeploymentResponse)
async def deploy_single_container_endpoint(
    project_slug: str,
    container_id: UUID,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Deploy a single container to its assigned deployment provider.

    This endpoint allows deploying an individual container that has a deployment
    target assigned (vercel, netlify, or cloudflare).

    Args:
        project_slug: Project slug
        container_id: Container UUID to deploy
        current_user: Current authenticated user
        db: Database session

    Returns:
        Deployment information

    Raises:
        HTTPException: If project/container not found, no deployment target, or no credentials
    """
    from sqlalchemy.orm import selectinload

    # 1. Verify project ownership
    result = await db.execute(
        select(Project).where(
            and_(
                Project.slug == project_slug,
                Project.owner_id == current_user.id,
            )
        )
    )
    project = result.scalar_one_or_none()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    # 2. Get the container with its base loaded
    result = await db.execute(
        select(Container)
        .where(
            and_(
                Container.id == container_id,
                Container.project_id == project.id,
            )
        )
        .options(selectinload(Container.base))
    )
    container = result.scalar_one_or_none()

    if not container:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Container not found",
        )

    # 3. Check if container has a deployment target
    if not container.deployment_provider:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Container has no deployment target assigned. Please assign a deployment provider first.",
        )

    provider_name = container.deployment_provider

    # 4. Check container type - only base containers can be deployed
    if container.container_type != "base":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Service containers (databases, caches) cannot be deployed to external providers",
        )

    # 5. Get credentials for the provider
    encryption_service = get_deployment_encryption_service()
    try:
        credential = await get_credential_for_deployment(
            db, current_user.id, project.id, provider_name
        )
        decrypted_token = encryption_service.decrypt(credential.access_token_encrypted)
    except HTTPException:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No credentials found for {provider_name}. Please connect your {provider_name} account first.",
        ) from None

    # 6. Create deployment record
    deployment = Deployment(
        project_id=project.id,
        user_id=current_user.id,
        provider=provider_name,
        status="building",
        logs=[f"Deploying {container.name} to {provider_name}..."],
        deployment_metadata={"container_id": str(container.id), "container_name": container.name},
    )
    db.add(deployment)
    await db.commit()
    await db.refresh(deployment)

    logger.info(f"Created deployment {deployment.id} for container {container.name} to {provider_name}")

    try:
        # 7. Get builder and framework from container fields
        builder = get_deployment_builder()
        framework = container.framework or "static"

        # 8. Determine deployment mode
        default_modes = {
            "vercel": "source",
            "netlify": "pre-built",
            "cloudflare": "pre-built",
        }
        deployment_mode = default_modes.get(provider_name, "pre-built")

        resolved_directory = resolve_container_directory(container)

        # 9. Build if needed
        if deployment_mode == "pre-built":
            deployment.logs.append(f"Building {container.name} locally...")
            await db.commit()

            success, build_output = await builder.trigger_build(
                user_id=str(current_user.id),
                project_id=str(project.id),
                project_slug=project.slug,
                framework=framework,
                custom_build_command=container.build_command,
                container_name=container.container_name,
                volume_name=project.slug,
                container_directory=resolved_directory,
                deployment_mode=deployment_mode,
                volume_id=project.volume_id,
                cache_node=project.cache_node,
            )

            if not success:
                deployment.status = "failed"
                deployment.error = "Build failed"
                deployment.logs.append(
                    f"Build failed: {build_output[:500] if build_output else 'Unknown error'}"
                )
                deployment.completed_at = datetime.utcnow()
                await db.commit()
                await db.refresh(deployment)

                return DeploymentResponse(
                    id=deployment.id,
                    project_id=deployment.project_id,
                    user_id=deployment.user_id,
                    provider=deployment.provider,
                    deployment_id=deployment.deployment_id,
                    deployment_url=deployment.deployment_url,
                    status=deployment.status,
                    logs=deployment.logs,
                    error=deployment.error,
                    created_at=deployment.created_at.isoformat(),
                    updated_at=deployment.updated_at.isoformat(),
                    completed_at=deployment.completed_at.isoformat()
                    if deployment.completed_at
                    else None,
                )

        # 10. Deploy to provider
        deployment.logs.append(f"Deploying to {provider_name}...")
        deployment.status = "deploying"
        await db.commit()

        provider_credentials = prepare_provider_credentials(
            provider_name, decrypted_token, credential.provider_metadata
        )

        # Auto-derive git repo URL for source-mode providers
        deploy_env_vars: dict[str, str] = {}
        if deployment_mode == "source" and project.git_remote_url:
            deploy_env_vars[ENV_REPO_URL] = project.git_remote_url

        config = DeploymentConfig(
            project_id=str(project.id),
            project_name=f"{project.slug}-{container.name}",
            framework=framework,
            deployment_mode=deployment_mode,
            env_vars=deploy_env_vars,
        )

        # Collect files for deployment
        files = await builder.collect_deployment_files(
            user_id=str(current_user.id),
            project_id=str(project.id),
            framework=framework,
            custom_output_dir=container.output_directory,
            collect_source=(deployment_mode == "source"),
            container_directory=resolved_directory,
            volume_name=project.slug,
            container_name=container.container_name,
            volume_id=project.volume_id,
        )

        provider_instance = DeploymentManager.get_provider(provider_name, provider_credentials)
        deploy_result = await _execute_provider_deploy(
            provider_instance, provider_name, files, config, container=container
        )

        # 11. Update deployment record
        deployment.status = "success" if deploy_result.success else "failed"
        deployment.deployment_id = deploy_result.deployment_id
        deployment.deployment_url = deploy_result.deployment_url
        deployment.error = deploy_result.error
        deployment.logs.extend(deploy_result.logs or [])
        deployment.completed_at = datetime.utcnow()
        await db.commit()
        await db.refresh(deployment)

        logger.info(f"Deployment {deployment.id} completed with status: {deployment.status}")

        return DeploymentResponse(
            id=deployment.id,
            project_id=deployment.project_id,
            user_id=deployment.user_id,
            provider=deployment.provider,
            deployment_id=deployment.deployment_id,
            deployment_url=deployment.deployment_url,
            status=deployment.status,
            logs=deployment.logs,
            error=deployment.error,
            created_at=deployment.created_at.isoformat(),
            updated_at=deployment.updated_at.isoformat(),
            completed_at=deployment.completed_at.isoformat()
            if deployment.completed_at
            else None,
        )

    except Exception as e:
        logger.error(f"Failed to deploy container {container.name}: {e}", exc_info=True)
        deployment.status = "failed"
        deployment.error = str(e)
        deployment.logs.append(f"Error: {str(e)}")
        deployment.completed_at = datetime.utcnow()
        await db.commit()
        await db.refresh(deployment)

        return DeploymentResponse(
            id=deployment.id,
            project_id=deployment.project_id,
            user_id=deployment.user_id,
            provider=deployment.provider,
            deployment_id=deployment.deployment_id,
            deployment_url=deployment.deployment_url,
            status=deployment.status,
            logs=deployment.logs,
            error=deployment.error,
            created_at=deployment.created_at.isoformat(),
            updated_at=deployment.updated_at.isoformat(),
            completed_at=deployment.completed_at.isoformat()
            if deployment.completed_at
            else None,
        )


@router.get("/{project_slug}/deployments", response_model=list[DeploymentResponse])
async def list_project_deployments(
    project_slug: str,
    provider: str | None = None,
    status_filter: str | None = None,
    limit: int = 20,
    offset: int = 0,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List deployments for a project.

    Args:
        project_slug: Project slug
        provider: Optional filter by provider
        status_filter: Optional filter by status
        limit: Maximum number of results
        offset: Pagination offset
        current_user: Current authenticated user
        db: Database session

    Returns:
        List of deployments
    """
    try:
        # Verify project ownership
        result = await db.execute(
            select(Project).where(
                and_(Project.slug == project_slug, Project.owner_id == current_user.id)
            )
        )
        project = result.scalar_one_or_none()

        if not project:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

        # Build query
        query = select(Deployment).where(Deployment.project_id == project.id)

        if provider:
            query = query.where(Deployment.provider == provider.lower())

        if status_filter:
            query = query.where(Deployment.status == status_filter)

        query = query.order_by(desc(Deployment.created_at)).limit(limit).offset(offset)

        # Execute query
        result = await db.execute(query)
        deployments = result.scalars().all()

        # Convert to response
        return [
            DeploymentResponse(
                id=d.id,
                project_id=d.project_id,
                user_id=d.user_id,
                provider=d.provider,
                deployment_id=d.deployment_id,
                deployment_url=d.deployment_url,
                status=d.status,
                logs=d.logs,
                error=d.error,
                created_at=d.created_at.isoformat(),
                updated_at=d.updated_at.isoformat(),
                completed_at=d.completed_at.isoformat() if d.completed_at else None,
            )
            for d in deployments
        ]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list deployments: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve deployments",
        ) from e


@router.get("/deployment/{deployment_id}", response_model=DeploymentResponse)
async def get_deployment(
    deployment_id: UUID,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get deployment details.

    Args:
        deployment_id: Deployment ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        Deployment information
    """
    try:
        # Fetch and verify ownership
        result = await db.execute(
            select(Deployment).where(
                and_(Deployment.id == deployment_id, Deployment.user_id == current_user.id)
            )
        )
        deployment = result.scalar_one_or_none()

        if not deployment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found"
            )

        return DeploymentResponse(
            id=deployment.id,
            project_id=deployment.project_id,
            user_id=deployment.user_id,
            provider=deployment.provider,
            deployment_id=deployment.deployment_id,
            deployment_url=deployment.deployment_url,
            status=deployment.status,
            logs=deployment.logs,
            error=deployment.error,
            created_at=deployment.created_at.isoformat(),
            updated_at=deployment.updated_at.isoformat(),
            completed_at=deployment.completed_at.isoformat() if deployment.completed_at else None,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get deployment: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve deployment",
        ) from e


@router.get("/deployment/{deployment_id}/status", response_model=DeploymentStatusResponse)
async def get_deployment_status(
    deployment_id: UUID,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Check deployment status with live provider status.

    This endpoint queries the provider for the latest deployment status
    and updates the database record.

    Args:
        deployment_id: Deployment ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        Current deployment status
    """
    try:
        # Fetch and verify ownership
        result = await db.execute(
            select(Deployment).where(
                and_(Deployment.id == deployment_id, Deployment.user_id == current_user.id)
            )
        )
        deployment = result.scalar_one_or_none()

        if not deployment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found"
            )

        # If deployment doesn't have a provider deployment_id, return current status
        if not deployment.deployment_id:
            return DeploymentStatusResponse(
                status=deployment.status,
                deployment_url=deployment.deployment_url,
                provider_status=None,
                updated_at=deployment.updated_at.isoformat(),
            )

        # Fetch credentials and check provider status
        credential = await get_credential_for_deployment(
            db, current_user.id, deployment.project_id, deployment.provider
        )

        encryption_service = get_deployment_encryption_service()
        decrypted_token = encryption_service.decrypt(credential.access_token_encrypted)
        provider_credentials = prepare_provider_credentials(
            deployment.provider, decrypted_token, credential.provider_metadata
        )

        # Get provider and check status
        provider = DeploymentManager.get_provider(deployment.provider, provider_credentials)
        provider_status = await provider.get_deployment_status(deployment.deployment_id)

        # Update deployment record if status changed
        if provider_status.get("status") and provider_status["status"] != deployment.status:
            if deployment.deployment_metadata is None:
                deployment.deployment_metadata = {}
            deployment.deployment_metadata["provider_status"] = provider_status
            await db.commit()

        return DeploymentStatusResponse(
            status=deployment.status,
            deployment_url=deployment.deployment_url,
            provider_status=provider_status,
            updated_at=deployment.updated_at.isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get deployment status: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to check deployment status",
        ) from e


@router.get("/deployment/{deployment_id}/logs", response_model=list[str])
async def get_deployment_logs(
    deployment_id: UUID,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get deployment logs.

    Fetches logs from both the database and the provider (if available).

    Args:
        deployment_id: Deployment ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        List of log messages
    """
    try:
        # Fetch and verify ownership
        result = await db.execute(
            select(Deployment).where(
                and_(Deployment.id == deployment_id, Deployment.user_id == current_user.id)
            )
        )
        deployment = result.scalar_one_or_none()

        if not deployment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found"
            )

        # Start with stored logs
        all_logs = deployment.logs or []

        # Try to fetch provider logs if deployment_id exists
        if deployment.deployment_id:
            try:
                credential = await get_credential_for_deployment(
                    db, current_user.id, deployment.project_id, deployment.provider
                )

                encryption_service = get_deployment_encryption_service()
                decrypted_token = encryption_service.decrypt(credential.access_token_encrypted)
                provider_credentials = prepare_provider_credentials(
                    deployment.provider, decrypted_token, credential.provider_metadata
                )

                provider = DeploymentManager.get_provider(deployment.provider, provider_credentials)
                provider_logs = await provider.get_deployment_logs(deployment.deployment_id)

                if provider_logs:
                    all_logs.extend(["", "=== Provider Logs ===", ""])
                    all_logs.extend(provider_logs)

            except Exception as e:
                logger.warning(f"Failed to fetch provider logs: {e}")
                all_logs.append(f"Note: Failed to fetch provider logs: {str(e)}")

        return all_logs

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get deployment logs: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve logs"
        ) from e


@router.delete("/deployment/{deployment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_deployment(
    deployment_id: UUID,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a deployment.

    This will attempt to delete the deployment from the provider
    and mark it as deleted in the database.

    Args:
        deployment_id: Deployment ID
        current_user: Current authenticated user
        db: Database session
    """
    try:
        # Fetch and verify ownership
        result = await db.execute(
            select(Deployment).where(
                and_(Deployment.id == deployment_id, Deployment.user_id == current_user.id)
            )
        )
        deployment = result.scalar_one_or_none()

        if not deployment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found"
            )

        # Try to delete from provider
        if deployment.deployment_id:
            try:
                credential = await get_credential_for_deployment(
                    db, current_user.id, deployment.project_id, deployment.provider
                )

                encryption_service = get_deployment_encryption_service()
                decrypted_token = encryption_service.decrypt(credential.access_token_encrypted)
                provider_credentials = prepare_provider_credentials(
                    deployment.provider, decrypted_token, credential.provider_metadata
                )

                provider = DeploymentManager.get_provider(deployment.provider, provider_credentials)
                await provider.delete_deployment(
                    deployment.deployment_id,
                    **({"metadata": deployment.deployment_metadata} if deployment.deployment_metadata else {}),
                )

                logger.info(
                    f"Deleted deployment {deployment_id} from provider {deployment.provider}"
                )

            except Exception as e:
                logger.warning(f"Failed to delete from provider: {e}")
                # Continue with database deletion even if provider deletion fails

        # Delete from database
        await db.delete(deployment)
        await db.commit()

        logger.info(f"Deleted deployment record {deployment_id}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete deployment: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete deployment"
        ) from e
