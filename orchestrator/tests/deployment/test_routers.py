"""
Tests for deployment routers.

This module tests the deployment API endpoints:
- Credential management
- OAuth flows
- Deployments
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from datetime import datetime, UTC

from app.routers import deployment_credentials, deployment_oauth, deployments
from app.models import DeploymentCredential, Deployment, Project, User
from app.services.deployment_encryption import DeploymentEncryptionService


class TestDeploymentCredentialsRouter:
    """Tests for deployment credentials API."""

    @pytest.mark.asyncio
    async def test_list_providers(self):
        """Test listing available deployment providers."""
        providers = await deployment_credentials.list_providers()

        assert len(providers) >= 3
        provider_names = {p["name"] for p in providers}
        assert "cloudflare" in provider_names
        assert "vercel" in provider_names
        assert "netlify" in provider_names

        for provider in providers:
            assert "name" in provider
            assert "display_name" in provider
            assert "auth_type" in provider
            assert "required_credentials" in provider

    @pytest.mark.asyncio
    async def test_create_credential(self, mock_db, mock_user):
        """Test creating a deployment credential."""
        request = deployment_credentials.CreateCredentialRequest(
            provider="vercel",
            access_token="test_token_12345",
            metadata=deployment_credentials.CredentialMetadata(
                team_id="team_abc123"
            )
        )

        with patch("app.routers.deployment_credentials.get_deployment_encryption_service") as mock_enc:
            mock_service = MagicMock()
            mock_service.encrypt.return_value = "encrypted_token"
            mock_enc.return_value = mock_service

            # Create a mock credential object with all required attributes
            mock_credential = MagicMock(spec=DeploymentCredential)
            mock_credential.id = uuid4()
            mock_credential.user_id = mock_user.id
            mock_credential.project_id = None
            mock_credential.provider = "vercel"
            mock_credential.access_token_encrypted = "encrypted_token"
            mock_credential.metadata = {"team_id": "team_abc123"}
            mock_credential.created_at = datetime.now()
            mock_credential.updated_at = datetime.now()

            # Mock database operations
            mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
            mock_db.commit = AsyncMock()
            mock_db.refresh = AsyncMock()
            mock_db.add = MagicMock()

            # Mock the credential object after add/refresh
            def mock_refresh_side_effect(obj):
                # Update the object with mock values
                if isinstance(obj, MagicMock):
                    obj.created_at = mock_credential.created_at
                    obj.updated_at = mock_credential.updated_at
                    obj.id = mock_credential.id

            mock_db.refresh.side_effect = mock_refresh_side_effect
            mock_db.rollback = AsyncMock()

            response = await deployment_credentials.create_credential(
                request=request,
                current_user=mock_user,
                db=mock_db
            )

            assert response.provider == "vercel"
            assert response.user_id == mock_user.id
            assert response.is_default is True
            mock_service.encrypt.assert_called_once_with("test_token_12345")

    @pytest.mark.asyncio
    async def test_create_credential_invalid_provider(self, mock_db, mock_user):
        """Test creating credential with invalid provider."""
        request = deployment_credentials.CreateCredentialRequest(
            provider="invalid_provider",
            access_token="test_token"
        )

        with pytest.raises(Exception):  # Should raise HTTPException
            await deployment_credentials.create_credential(
                request=request,
                current_user=mock_user,
                db=mock_db
            )

    @pytest.mark.asyncio
    async def test_test_credential_valid(self, mock_db, mock_user):
        """Test validating a credential."""
        credential_id = uuid4()
        mock_credential = MagicMock(spec=DeploymentCredential)
        mock_credential.id = credential_id
        mock_credential.user_id = mock_user.id
        mock_credential.provider = "vercel"
        mock_credential.access_token_encrypted = "encrypted_token"
        mock_credential.metadata = {"team_id": "team_123"}

        with patch("app.routers.deployment_credentials.get_deployment_encryption_service") as mock_enc:
            mock_service = MagicMock()
            mock_service.decrypt.return_value = "decrypted_token"
            mock_enc.return_value = mock_service

            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_credential
            mock_db.execute = AsyncMock(return_value=mock_result)

            response = await deployment_credentials.test_credential(
                credential_id=credential_id,
                current_user=mock_user,
                db=mock_db
            )

            assert response.valid is True
            assert response.provider_info is not None


class TestDeploymentOAuthRouter:
    """Tests for deployment OAuth endpoints."""

    @pytest.mark.asyncio
    async def test_vercel_authorize(self, mock_user):
        """Test initiating Vercel OAuth flow."""
        with patch("app.routers.deployment_oauth.get_settings") as mock_settings:
            settings = MagicMock()
            settings.vercel_client_id = "client_123"
            settings.vercel_oauth_redirect_uri = "http://localhost/callback"
            mock_settings.return_value = settings

            response = await deployment_oauth.vercel_authorize(
                project_id=None,
                current_user=mock_user
            )

            assert response.status_code == 307  # Redirect
            assert "vercel.com/oauth/authorize" in response.headers["location"]

    @pytest.mark.asyncio
    async def test_netlify_authorize(self, mock_user):
        """Test initiating Netlify OAuth flow."""
        with patch("app.routers.deployment_oauth.get_settings") as mock_settings:
            settings = MagicMock()
            settings.netlify_client_id = "client_123"
            settings.netlify_oauth_redirect_uri = "http://localhost/callback"
            mock_settings.return_value = settings

            response = await deployment_oauth.netlify_authorize(
                project_id=None,
                current_user=mock_user
            )

            assert response.status_code == 307  # Redirect
            assert "netlify.com/authorize" in response.headers["location"]


class TestDeploymentsRouter:
    """Tests for deployments API."""

    @pytest.mark.asyncio
    async def test_deploy_project_not_found(self, mock_db, mock_user):
        """Test deploying a non-existent project."""
        request = deployments.DeploymentRequest(
            provider="vercel"
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(Exception):  # Should raise HTTPException 404
            await deployments.deploy_project(
                project_slug="non-existent",
                request=request,
                current_user=mock_user,
                db=mock_db
            )

    @pytest.mark.asyncio
    async def test_list_project_deployments(self, mock_db, mock_user):
        """Test listing deployments for a project."""
        project_id = uuid4()
        mock_project = MagicMock(spec=Project)
        mock_project.id = project_id
        mock_project.slug = "test-project"

        mock_deployment = MagicMock(spec=Deployment)
        mock_deployment.id = uuid4()
        mock_deployment.project_id = project_id
        mock_deployment.user_id = mock_user.id
        mock_deployment.provider = "vercel"
        mock_deployment.status = "success"
        mock_deployment.deployment_url = "https://test.vercel.app"
        mock_deployment.created_at = datetime.now(UTC)
        mock_deployment.updated_at = datetime.now(UTC)
        mock_deployment.completed_at = datetime.now(UTC)
        mock_deployment.logs = ["Build started", "Build completed"]
        mock_deployment.error = None
        mock_deployment.deployment_id = "deploy_123"

        # Mock project query
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = mock_project

        # Mock deployments query
        mock_deployments_result = MagicMock()
        mock_deployments_result.scalars.return_value.all.return_value = [mock_deployment]

        async def mock_execute(query):
            # Return appropriate result based on query type
            if "Project" in str(query):
                return mock_project_result
            else:
                return mock_deployments_result

        mock_db.execute = AsyncMock(side_effect=mock_execute)

        response = await deployments.list_project_deployments(
            project_slug="test-project",
            current_user=mock_user,
            db=mock_db
        )

        assert len(response) == 1
        assert response[0].provider == "vercel"
        assert response[0].status == "success"

    @pytest.mark.asyncio
    async def test_get_deployment(self, mock_db, mock_user):
        """Test getting deployment details."""
        deployment_id = uuid4()
        mock_deployment = MagicMock(spec=Deployment)
        mock_deployment.id = deployment_id
        mock_deployment.user_id = mock_user.id
        mock_deployment.provider = "vercel"
        mock_deployment.status = "success"
        mock_deployment.deployment_url = "https://test.vercel.app"
        mock_deployment.created_at = datetime.now(UTC)
        mock_deployment.updated_at = datetime.now(UTC)
        mock_deployment.completed_at = datetime.now(UTC)
        mock_deployment.logs = ["Build completed"]
        mock_deployment.error = None
        mock_deployment.deployment_id = "deploy_123"
        mock_deployment.project_id = uuid4()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_deployment
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await deployments.get_deployment(
            deployment_id=deployment_id,
            current_user=mock_user,
            db=mock_db
        )

        assert response.id == deployment_id
        assert response.provider == "vercel"
        assert response.status == "success"


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_user():
    """Create a mock user."""
    user = MagicMock(spec=User)
    user.id = uuid4()
    user.email = "test@example.com"
    return user


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    return MagicMock()
