"""
Deployments API Router.

This module provides API endpoints for deploying projects to various providers
(Cloudflare Workers, Vercel, Netlify, etc.) with support for builds, status tracking,
and deployment management.
"""

import logging
import json
from typing import List, Optional, Dict
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc
from pydantic import BaseModel, Field

from ..database import get_db
from ..models import Deployment, DeploymentCredential, Project, User, Container
from ..users import current_active_user
from ..services.deployment_encryption import get_deployment_encryption_service, DeploymentEncryptionError
from ..services.deployment.manager import DeploymentManager
from ..services.deployment.base import DeploymentConfig
from ..services.deployment.builder import get_deployment_builder, BuildError
from ..services.framework_detector import FrameworkDetector
from ..utils.async_subprocess import run_async

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/deployments", tags=["deployments"])


# ============================================================================
# Request/Response Models
# ============================================================================

class DeploymentRequest(BaseModel):
    """Request to deploy a project."""
    provider: str = Field(..., description="Deployment provider (cloudflare, vercel, netlify)")
    deployment_mode: Optional[str] = Field(
        None,
        description="Deployment mode: 'source' (provider builds) or 'pre-built' (upload built files). Default varies by provider."
    )
    custom_domain: Optional[str] = Field(None, description="Custom domain")
    env_vars: Dict[str, str] = Field(default_factory=dict, description="Environment variables")
    build_command: Optional[str] = Field(None, description="Custom build command override")
    framework: Optional[str] = Field(None, description="Framework override (auto-detected if not provided)")


class DeploymentResponse(BaseModel):
    """Response containing deployment information."""
    id: UUID
    project_id: UUID
    user_id: UUID
    provider: str
    deployment_id: Optional[str]
    deployment_url: Optional[str]
    status: str
    logs: Optional[List[str]]
    error: Optional[str]
    created_at: str
    updated_at: str
    completed_at: Optional[str]

    class Config:
        from_attributes = True


class DeploymentStatusResponse(BaseModel):
    """Response for deployment status check."""
    status: str
    deployment_url: Optional[str]
    provider_status: Optional[Dict]
    updated_at: str


# ============================================================================
# Helper Functions
# ============================================================================

async def get_credential_for_deployment(
    db: AsyncSession,
    user_id: UUID,
    project_id: UUID,
    provider: str
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
                DeploymentCredential.project_id == project_id
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
                DeploymentCredential.project_id.is_(None)
            )
        )
    )
    credential = result.scalar_one_or_none()

    if not credential:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No credentials found for {provider}. Please connect your account in settings."
        )

    logger.debug(f"Using default user credential for {provider}")
    return credential


def prepare_provider_credentials(
    provider: str,
    decrypted_token: str,
    metadata: Optional[dict]
) -> Dict[str, str]:
    """
    Prepare credentials dict for a provider.

    Args:
        provider: Provider name
        decrypted_token: Decrypted access token
        metadata: Credential metadata

    Returns:
        Provider-specific credentials dict
    """
    credentials = {}

    if provider == "cloudflare":
        credentials["api_token"] = decrypted_token
        if metadata and "account_id" in metadata:
            credentials["account_id"] = metadata["account_id"]
        if metadata and "dispatch_namespace" in metadata:
            credentials["dispatch_namespace"] = metadata["dispatch_namespace"]

    elif provider == "vercel":
        credentials["token"] = decrypted_token
        if metadata and "team_id" in metadata:
            credentials["team_id"] = metadata["team_id"]

    elif provider == "netlify":
        credentials["token"] = decrypted_token

    else:
        # Default: just pass token
        credentials["token"] = decrypted_token

    return credentials


# ============================================================================
# API Endpoints
# ============================================================================

@router.post("/{project_slug}/deploy", response_model=DeploymentResponse)
async def deploy_project(
    project_slug: str,
    request: DeploymentRequest,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
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

        # 2. Fetch credentials
        provider_lower = request.provider.lower()
        credential = await get_credential_for_deployment(
            db, current_user.id, project.id, provider_lower
        )

        # 3. Decrypt credentials
        encryption_service = get_deployment_encryption_service()
        decrypted_token = encryption_service.decrypt(credential.access_token_encrypted)
        provider_credentials = prepare_provider_credentials(
            provider_lower,
            decrypted_token,
            credential.metadata
        )

        # 4. Create deployment record (status: building)
        deployment = Deployment(
            project_id=project.id,
            user_id=current_user.id,
            provider=provider_lower,
            status="building",
            logs=["Deployment started"],
            metadata={}
        )
        db.add(deployment)
        await db.commit()
        await db.refresh(deployment)

        logger.info(f"Created deployment {deployment.id} for project {project.slug}")

        # 5. Detect framework with caching
        builder = get_deployment_builder()
        project_path = builder._get_project_path(str(current_user.id), str(project.id))

        # Initialize project settings if not exists
        if not project.settings:
            project.settings = {}

        # Priority: request > cached > auto-detect
        framework = request.framework
        framework_was_detected = False

        if not framework:
            # Try cached framework first
            if project.settings.get("framework"):
                framework = project.settings["framework"]
                logger.info(f"Using cached framework: {framework}")
            else:
                # Fallback: Auto-detect from package.json
                import os
                package_json_path = os.path.join(project_path, "package.json")
                if os.path.exists(package_json_path):
                    with open(package_json_path, 'r') as f:
                        package_json_content = f.read()
                    framework, _ = FrameworkDetector.detect_from_package_json(package_json_content)
                    logger.info(f"Auto-detected framework: {framework}")
                else:
                    framework = "vite"
                    logger.warning("No package.json found, defaulting to vite")

                # Cache the detected framework
                project.settings["framework"] = framework
                framework_was_detected = True
                await db.commit()

        # 6. Determine deployment mode (source vs pre-built)
        # Default modes per provider:
        # - Vercel: source (has Git/CLI integration for builds)
        # - Cloudflare: pre-built (upload to Workers)
        # - Netlify: pre-built (file upload API doesn't trigger builds)
        deployment_mode = request.deployment_mode
        if not deployment_mode:
            # Set sensible defaults per provider
            default_modes = {
                "vercel": "source",
                "netlify": "pre-built",
                "cloudflare": "pre-built"
            }
            deployment_mode = default_modes.get(provider_lower, "pre-built")
            deployment.logs.append(f"Using default deployment mode for {provider_lower}: {deployment_mode}")
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
            build_directory = primary_container.directory

            deployment.logs.append(f"Multi-container project: building in container '{primary_container.name}' ({build_container_name})")
            logger.info(f"Using container {build_container_name} for build (directory: {build_directory})")
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

            result = await run_async(
                ["docker", "inspect", "--format", "{{.State.Running}}", build_container_name],
                capture_output=True,
                text=True,
                timeout=10
            )

            is_running = result.stdout.strip() == "true"

            if not is_running:
                error_msg = f"Container {build_container_name} is not running. Please start your project containers first."
                deployment.status = "failed"
                deployment.error = error_msg
                deployment.completed_at = datetime.utcnow()
                await db.commit()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=error_msg
                )

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
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg
            )

        # 8. Run build (skip if source mode - provider will build)
        use_source_deployment = (deployment_mode == "source")

        if use_source_deployment:
            deployment.logs.append(f"Skipping local build - {provider_lower} will build remotely (framework: {framework})")
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
                    custom_build_command=request.build_command,
                    project_settings=project.settings,
                    container_name=build_container_name,
                    volume_name=project.slug  # Use project.slug for shared volume path
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
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Build failed: {str(e)}"
                )

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
            project_settings=project.settings,
            collect_source=use_source_deployment,
            container_directory=build_directory,
            volume_name=project.slug  # Use project.slug for shared volume path
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
            build_command=request.build_command,
            env_vars=request.env_vars,
            custom_domain=request.custom_domain
        )

        provider = DeploymentManager.get_provider(provider_lower, provider_credentials)
        result = await provider.deploy(files, config)

        # 11. Update deployment record
        if result.success:
            deployment.status = "success"
            deployment.deployment_id = result.deployment_id
            deployment.deployment_url = result.deployment_url
            # For JSON fields, we need to create a new list to trigger SQLAlchemy's change detection
            deployment.logs = deployment.logs + result.logs
            deployment.metadata = result.metadata
            deployment.completed_at = datetime.utcnow()

            logger.info(
                f"Deployment {deployment.id} succeeded: {result.deployment_url}"
            )
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
            completed_at=deployment.completed_at.isoformat() if deployment.completed_at else None
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
            detail="Failed to decrypt credentials"
        )
    except Exception as e:
        logger.error(f"Deployment failed: {e}", exc_info=True)
        if deployment:
            deployment.status = "failed"
            deployment.error = str(e)
            deployment.completed_at = datetime.utcnow()
            await db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Deployment failed: {str(e)}"
        )


@router.get("/{project_slug}/deployments", response_model=List[DeploymentResponse])
async def list_project_deployments(
    project_slug: str,
    provider: Optional[str] = None,
    status_filter: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
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
                completed_at=d.completed_at.isoformat() if d.completed_at else None
            )
            for d in deployments
        ]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list deployments: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve deployments"
        )


@router.get("/deployment/{deployment_id}", response_model=DeploymentResponse)
async def get_deployment(
    deployment_id: UUID,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
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
                and_(
                    Deployment.id == deployment_id,
                    Deployment.user_id == current_user.id
                )
            )
        )
        deployment = result.scalar_one_or_none()

        if not deployment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Deployment not found"
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
            completed_at=deployment.completed_at.isoformat() if deployment.completed_at else None
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get deployment: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve deployment"
        )


@router.get("/deployment/{deployment_id}/status", response_model=DeploymentStatusResponse)
async def get_deployment_status(
    deployment_id: UUID,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
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
                and_(
                    Deployment.id == deployment_id,
                    Deployment.user_id == current_user.id
                )
            )
        )
        deployment = result.scalar_one_or_none()

        if not deployment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Deployment not found"
            )

        # If deployment doesn't have a provider deployment_id, return current status
        if not deployment.deployment_id:
            return DeploymentStatusResponse(
                status=deployment.status,
                deployment_url=deployment.deployment_url,
                provider_status=None,
                updated_at=deployment.updated_at.isoformat()
            )

        # Fetch credentials and check provider status
        credential = await get_credential_for_deployment(
            db, current_user.id, deployment.project_id, deployment.provider
        )

        encryption_service = get_deployment_encryption_service()
        decrypted_token = encryption_service.decrypt(credential.access_token_encrypted)
        provider_credentials = prepare_provider_credentials(
            deployment.provider,
            decrypted_token,
            credential.metadata
        )

        # Get provider and check status
        provider = DeploymentManager.get_provider(deployment.provider, provider_credentials)
        provider_status = await provider.get_deployment_status(deployment.deployment_id)

        # Update deployment record if status changed
        if provider_status.get("status") and provider_status["status"] != deployment.status:
            deployment.metadata["provider_status"] = provider_status
            await db.commit()

        return DeploymentStatusResponse(
            status=deployment.status,
            deployment_url=deployment.deployment_url,
            provider_status=provider_status,
            updated_at=deployment.updated_at.isoformat()
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get deployment status: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to check deployment status"
        )


@router.get("/deployment/{deployment_id}/logs", response_model=List[str])
async def get_deployment_logs(
    deployment_id: UUID,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
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
                and_(
                    Deployment.id == deployment_id,
                    Deployment.user_id == current_user.id
                )
            )
        )
        deployment = result.scalar_one_or_none()

        if not deployment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Deployment not found"
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
                    deployment.provider,
                    decrypted_token,
                    credential.metadata
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
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve logs"
        )


@router.delete("/deployment/{deployment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_deployment(
    deployment_id: UUID,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
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
                and_(
                    Deployment.id == deployment_id,
                    Deployment.user_id == current_user.id
                )
            )
        )
        deployment = result.scalar_one_or_none()

        if not deployment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Deployment not found"
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
                    deployment.provider,
                    decrypted_token,
                    credential.metadata
                )

                provider = DeploymentManager.get_provider(deployment.provider, provider_credentials)
                await provider.delete_deployment(deployment.deployment_id)

                logger.info(f"Deleted deployment {deployment_id} from provider {deployment.provider}")

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
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete deployment"
        )
