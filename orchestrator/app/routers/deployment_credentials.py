"""
Deployment Credentials API Router.

This module provides API endpoints for managing deployment provider credentials
(Cloudflare, Vercel, Netlify, etc.) with secure encryption and storage.
"""

import logging
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from pydantic import BaseModel, Field

from ..database import get_db
from ..models import DeploymentCredential, User, Project
from ..users import current_active_user
from ..services.deployment_encryption import get_deployment_encryption_service, DeploymentEncryptionError
from ..services.deployment.manager import DeploymentManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/deployment-credentials", tags=["deployment-credentials"])


# ============================================================================
# Request/Response Models
# ============================================================================

class CredentialMetadata(BaseModel):
    """Provider-specific metadata (team_id, account_id, etc.)."""
    team_id: Optional[str] = Field(None, description="Team ID (Vercel)")
    account_id: Optional[str] = Field(None, description="Account ID (Cloudflare)")
    dispatch_namespace: Optional[str] = Field(None, description="Dispatch namespace (Cloudflare)")
    account_name: Optional[str] = Field(None, description="Account name for display")


class CreateCredentialRequest(BaseModel):
    """Request to create a new deployment credential."""
    provider: str = Field(..., description="Provider name (cloudflare, vercel, netlify)")
    access_token: str = Field(..., description="API token or access token")
    metadata: Optional[CredentialMetadata] = Field(None, description="Provider-specific metadata")
    project_id: Optional[UUID] = Field(None, description="Project ID for project-specific credential override")


class UpdateCredentialRequest(BaseModel):
    """Request to update an existing credential."""
    access_token: Optional[str] = Field(None, description="New API token (if changing)")
    metadata: Optional[CredentialMetadata] = Field(None, description="Updated metadata")


class CredentialResponse(BaseModel):
    """Response containing credential information (WITHOUT the token)."""
    id: UUID
    user_id: UUID
    project_id: Optional[UUID]
    provider: str
    metadata: Optional[dict]
    created_at: str
    updated_at: str
    is_default: bool = Field(..., description="True if this is the user's default credential for this provider")

    class Config:
        from_attributes = True


class ProviderInfo(BaseModel):
    """Information about an available deployment provider."""
    name: str
    display_name: str
    description: str
    auth_type: str
    required_credentials: List[str]
    optional_credentials: List[str]


class TestCredentialResponse(BaseModel):
    """Response from credential testing."""
    valid: bool
    error: Optional[str] = None
    provider_info: Optional[dict] = None


class CredentialListResponse(BaseModel):
    """Response containing list of credentials."""
    credentials: List[CredentialResponse]


class ProviderListResponse(BaseModel):
    """Response containing list of providers."""
    providers: List[ProviderInfo]


# ============================================================================
# API Endpoints
# ============================================================================

@router.get("/providers", response_model=ProviderListResponse)
async def list_providers():
    """
    List all available deployment providers.

    Returns provider metadata including authentication requirements.
    This is a public endpoint (no authentication required).
    """
    try:
        providers = DeploymentManager.list_available_providers()
        return {"providers": providers}
    except Exception as e:
        logger.error(f"Failed to list providers: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve provider list"
        )


@router.get("/", response_model=CredentialListResponse)
async def list_credentials(
    provider: Optional[str] = None,
    project_id: Optional[UUID] = None,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List deployment credentials for the current user.

    Args:
        provider: Optional filter by provider name
        project_id: Optional filter by project ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        List of credentials (WITHOUT access tokens)
    """
    try:
        # Build query
        query = select(DeploymentCredential).where(
            DeploymentCredential.user_id == current_user.id
        )

        if provider:
            query = query.where(DeploymentCredential.provider == provider.lower())

        if project_id:
            query = query.where(DeploymentCredential.project_id == project_id)

        # Execute query
        result = await db.execute(query)
        credentials = result.scalars().all()

        # Convert to response format
        responses = []
        for cred in credentials:
            responses.append(CredentialResponse(
                id=cred.id,
                user_id=cred.user_id,
                project_id=cred.project_id,
                provider=cred.provider,
                metadata=cred.provider_metadata,
                created_at=cred.created_at.isoformat(),
                updated_at=cred.updated_at.isoformat(),
                is_default=(cred.project_id is None)
            ))

        logger.info(f"User {current_user.id} listed {len(responses)} deployment credentials")
        return {"credentials": responses}

    except Exception as e:
        logger.error(f"Failed to list credentials: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve credentials"
        )


@router.post("/", response_model=CredentialResponse, status_code=status.HTTP_201_CREATED)
async def create_credential(
    request: CreateCredentialRequest,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new deployment credential.

    This endpoint encrypts and stores deployment provider credentials.
    If a credential already exists for this user/provider/project combination,
    it will be updated (upsert logic).

    Args:
        request: Credential creation request
        current_user: Current authenticated user
        db: Database session

    Returns:
        Created credential information (WITHOUT access token)
    """
    try:
        # Validate provider
        provider_lower = request.provider.lower()
        if not DeploymentManager.is_provider_available(provider_lower):
            available = ", ".join(DeploymentManager._providers.keys())
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown provider: {request.provider}. Available: {available}"
            )

        # Validate project ownership if project_id is provided
        if request.project_id:
            project_result = await db.execute(
                select(Project).where(
                    and_(
                        Project.id == request.project_id,
                        Project.owner_id == current_user.id
                    )
                )
            )
            project = project_result.scalar_one_or_none()
            if not project:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Project not found or access denied"
                )

        # Encrypt the access token
        encryption_service = get_deployment_encryption_service()
        encrypted_token = encryption_service.encrypt(request.access_token)

        # Check for existing credential (upsert logic)
        existing_result = await db.execute(
            select(DeploymentCredential).where(
                and_(
                    DeploymentCredential.user_id == current_user.id,
                    DeploymentCredential.provider == provider_lower,
                    DeploymentCredential.project_id == request.project_id
                )
            )
        )
        existing = existing_result.scalar_one_or_none()

        if existing:
            # Update existing credential
            existing.access_token_encrypted = encrypted_token
            existing.provider_metadata = request.metadata.model_dump() if request.metadata else None
            await db.commit()
            await db.refresh(existing)

            logger.info(f"Updated deployment credential {existing.id} for user {current_user.id}, provider {provider_lower}")

            return CredentialResponse(
                id=existing.id,
                user_id=existing.user_id,
                project_id=existing.project_id,
                provider=existing.provider,
                metadata=existing.provider_metadata,
                created_at=existing.created_at.isoformat(),
                updated_at=existing.updated_at.isoformat(),
                is_default=(existing.project_id is None)
            )
        else:
            # Create new credential
            credential = DeploymentCredential(
                user_id=current_user.id,
                project_id=request.project_id,
                provider=provider_lower,
                access_token_encrypted=encrypted_token,
                provider_metadata=request.metadata.model_dump() if request.metadata else None
            )

            db.add(credential)
            await db.commit()
            await db.refresh(credential)

            logger.info(f"Created deployment credential {credential.id} for user {current_user.id}, provider {provider_lower}")

            return CredentialResponse(
                id=credential.id,
                user_id=credential.user_id,
                project_id=credential.project_id,
                provider=credential.provider,
                metadata=credential.provider_metadata,
                created_at=credential.created_at.isoformat(),
                updated_at=credential.updated_at.isoformat(),
                is_default=(credential.project_id is None)
            )

    except HTTPException:
        raise
    except DeploymentEncryptionError as e:
        logger.error(f"Encryption error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to encrypt credential"
        )
    except Exception as e:
        logger.error(f"Failed to create credential: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create credential"
        )


@router.put("/{credential_id}", response_model=CredentialResponse)
async def update_credential(
    credential_id: UUID,
    request: UpdateCredentialRequest,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Update an existing deployment credential.

    Args:
        credential_id: ID of credential to update
        request: Update request
        current_user: Current authenticated user
        db: Database session

    Returns:
        Updated credential information
    """
    try:
        # Fetch and verify ownership
        result = await db.execute(
            select(DeploymentCredential).where(
                and_(
                    DeploymentCredential.id == credential_id,
                    DeploymentCredential.user_id == current_user.id
                )
            )
        )
        credential = result.scalar_one_or_none()

        if not credential:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Credential not found"
            )

        # Update token if provided
        if request.access_token:
            encryption_service = get_deployment_encryption_service()
            credential.access_token_encrypted = encryption_service.encrypt(request.access_token)

        # Update metadata if provided
        if request.metadata:
            credential.provider_metadata = request.metadata.model_dump()

        await db.commit()
        await db.refresh(credential)

        logger.info(f"Updated deployment credential {credential_id} for user {current_user.id}")

        return CredentialResponse(
            id=credential.id,
            user_id=credential.user_id,
            project_id=credential.project_id,
            provider=credential.provider,
            metadata=credential.provider_metadata,
            created_at=credential.created_at.isoformat(),
            updated_at=credential.updated_at.isoformat(),
            is_default=(credential.project_id is None)
        )

    except HTTPException:
        raise
    except DeploymentEncryptionError as e:
        logger.error(f"Encryption error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to encrypt credential"
        )
    except Exception as e:
        logger.error(f"Failed to update credential: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update credential"
        )


@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(
    credential_id: UUID,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a deployment credential.

    Args:
        credential_id: ID of credential to delete
        current_user: Current authenticated user
        db: Database session
    """
    try:
        # Fetch and verify ownership
        result = await db.execute(
            select(DeploymentCredential).where(
                and_(
                    DeploymentCredential.id == credential_id,
                    DeploymentCredential.user_id == current_user.id
                )
            )
        )
        credential = result.scalar_one_or_none()

        if not credential:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Credential not found"
            )

        # Delete the credential
        await db.delete(credential)
        await db.commit()

        logger.info(f"Deleted deployment credential {credential_id} for user {current_user.id}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete credential: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete credential"
        )


@router.post("/test/{credential_id}", response_model=TestCredentialResponse)
async def test_credential(
    credential_id: UUID,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Test if a deployment credential is valid by making a test API call to the provider.

    Args:
        credential_id: ID of credential to test
        current_user: Current authenticated user
        db: Database session

    Returns:
        Test result with validity status
    """
    try:
        # Fetch and verify ownership
        result = await db.execute(
            select(DeploymentCredential).where(
                and_(
                    DeploymentCredential.id == credential_id,
                    DeploymentCredential.user_id == current_user.id
                )
            )
        )
        credential = result.scalar_one_or_none()

        if not credential:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Credential not found"
            )

        # Decrypt token
        encryption_service = get_deployment_encryption_service()
        access_token = encryption_service.decrypt(credential.access_token_encrypted)

        # Prepare credentials dict for provider
        provider_credentials = {"token": access_token}

        # Add metadata to credentials
        if credential.provider_metadata:
            if credential.provider == "cloudflare":
                provider_credentials["api_token"] = access_token
                if "account_id" in credential.provider_metadata:
                    provider_credentials["account_id"] = credential.provider_metadata["account_id"]
            elif credential.provider in ["vercel", "netlify"]:
                if "team_id" in credential.provider_metadata:
                    provider_credentials["team_id"] = credential.provider_metadata["team_id"]

        # Get provider instance and test credentials with real API call
        try:
            provider = DeploymentManager.get_provider(credential.provider, provider_credentials)

            # Call the provider's test_credentials method to make a real API call
            provider_info = await provider.test_credentials()

            logger.info(f"Credential {credential_id} test successful for provider {credential.provider}")

            return TestCredentialResponse(
                valid=True,
                provider_info=provider_info
            )

        except ValueError as e:
            logger.warning(f"Credential {credential_id} validation failed: {e}")
            return TestCredentialResponse(
                valid=False,
                error=str(e)
            )

    except HTTPException:
        raise
    except DeploymentEncryptionError as e:
        logger.error(f"Decryption error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to decrypt credential"
        )
    except Exception as e:
        logger.error(f"Failed to test credential: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to test credential"
        )
