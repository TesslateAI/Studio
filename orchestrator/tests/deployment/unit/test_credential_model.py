"""
Unit tests for DeploymentCredential and Deployment models.

Tests model structure, field definitions, and basic model instantiation.
"""

import pytest
from datetime import datetime
from uuid import uuid4

from app.models import DeploymentCredential, Deployment


@pytest.mark.unit
class TestDeploymentCredentialModel:
    """Test suite for DeploymentCredential model structure."""

    def test_model_has_required_fields(self):
        """Test that DeploymentCredential model has all required fields."""
        required_fields = [
            'id', 'user_id', 'project_id', 'provider',
            'access_token_encrypted', 'provider_metadata',
            'created_at', 'updated_at'
        ]

        for field in required_fields:
            assert hasattr(DeploymentCredential, field), f"Missing field: {field}"

    def test_create_deployment_credential_instance(self):
        """Test creating a DeploymentCredential instance."""
        user_id = uuid4()
        credential_id = uuid4()

        credential = DeploymentCredential(
            id=credential_id,
            user_id=user_id,
            provider="vercel",
            access_token_encrypted="encrypted_token_123",
            provider_metadata={"team_id": "team_abc"},
        )

        assert credential.id == credential_id
        assert credential.user_id == user_id
        assert credential.provider == "vercel"
        assert credential.access_token_encrypted == "encrypted_token_123"
        assert credential.provider_metadata == {"team_id": "team_abc"}
        assert credential.project_id is None  # Default credential

    def test_create_project_specific_credential(self):
        """Test creating a project-specific credential instance."""
        user_id = uuid4()
        project_id = uuid4()
        credential_id = uuid4()

        credential = DeploymentCredential(
            id=credential_id,
            user_id=user_id,
            project_id=project_id,
            provider="cloudflare",
            access_token_encrypted="encrypted_cloudflare_token",
            provider_metadata={"account_id": "cf_account_123"},
        )

        assert credential.project_id == project_id
        assert credential.provider == "cloudflare"
        assert credential.provider_metadata["account_id"] == "cf_account_123"

    def test_metadata_can_be_complex_json(self):
        """Test that metadata can store complex JSON structures."""
        complex_metadata = {
            "team_id": "team_123",
            "account_id": "account_456",
            "settings": {
                "auto_deploy": True,
                "environment": "production",
            },
            "tags": ["frontend", "production"],
        }

        credential = DeploymentCredential(
            id=uuid4(),
            user_id=uuid4(),
            provider="vercel",
            access_token_encrypted="token",
            provider_metadata=complex_metadata,
        )

        assert credential.provider_metadata == complex_metadata
        assert credential.provider_metadata["settings"]["auto_deploy"] is True
        assert "frontend" in credential.provider_metadata["tags"]

    def test_multiple_providers_different_instances(self):
        """Test creating instances for different providers."""
        user_id = uuid4()
        providers = ["vercel", "netlify", "cloudflare"]

        credentials = []
        for provider in providers:
            credential = DeploymentCredential(
                id=uuid4(),
                user_id=user_id,
                provider=provider,
                access_token_encrypted=f"token_{provider}",
            )
            credentials.append(credential)

        assert len(credentials) == 3
        saved_providers = {cred.provider for cred in credentials}
        assert saved_providers == set(providers)

    def test_table_name_is_correct(self):
        """Test that the table name is correctly set."""
        assert DeploymentCredential.__tablename__ == "deployment_credentials"

    def test_relationship_attributes_exist(self):
        """Test that relationship attributes are defined."""
        assert hasattr(DeploymentCredential, 'user')
        assert hasattr(DeploymentCredential, 'project')


@pytest.mark.unit
class TestDeploymentModel:
    """Test suite for Deployment model structure."""

    def test_model_has_required_fields(self):
        """Test that Deployment model has all required fields."""
        required_fields = [
            'id', 'project_id', 'user_id', 'provider',
            'deployment_id', 'deployment_url', 'status',
            'error', 'logs', 'deployment_metadata',
            'created_at', 'updated_at', 'completed_at'
        ]

        for field in required_fields:
            assert hasattr(Deployment, field), f"Missing field: {field}"

    def test_create_deployment_instance(self):
        """Test creating a Deployment instance."""
        deployment_id = uuid4()
        project_id = uuid4()
        user_id = uuid4()

        deployment = Deployment(
            id=deployment_id,
            project_id=project_id,
            user_id=user_id,
            provider="vercel",
            deployment_id="vercel_deploy_123",
            deployment_url="https://my-app.vercel.app",
            status="success",
        )

        assert deployment.id == deployment_id
        assert deployment.provider == "vercel"
        assert deployment.status == "success"
        assert deployment.deployment_url == "https://my-app.vercel.app"

    def test_deployment_with_logs(self):
        """Test creating a deployment instance with logs."""
        logs = [
            "Building application...",
            "Installing dependencies...",
            "Deploying to Vercel...",
            "Deployment successful!",
        ]

        deployment = Deployment(
            id=uuid4(),
            project_id=uuid4(),
            user_id=uuid4(),
            provider="vercel",
            status="success",
            logs=logs,
        )

        assert deployment.logs == logs
        assert len(deployment.logs) == 4

    def test_deployment_with_metadata(self):
        """Test creating a deployment instance with metadata."""
        metadata = {
            "build_time": 45.2,
            "framework": "vite",
            "node_version": "18.17.0",
            "deployment_region": "us-east-1",
        }

        deployment = Deployment(
            id=uuid4(),
            project_id=uuid4(),
            user_id=uuid4(),
            provider="cloudflare",
            status="success",
            deployment_metadata=metadata,
        )

        assert deployment.deployment_metadata == metadata
        assert deployment.deployment_metadata["build_time"] == 45.2

    def test_deployment_status_values(self):
        """Test different deployment status values."""
        statuses = ["pending", "building", "deploying", "success", "failed"]

        for status in statuses:
            deployment = Deployment(
                id=uuid4(),
                project_id=uuid4(),
                user_id=uuid4(),
                provider="netlify",
                status=status,
            )
            assert deployment.status == status

    def test_deployment_failure_with_error(self):
        """Test creating a deployment instance with error message."""
        error_message = "Build failed: Module not found 'missing-package'"

        deployment = Deployment(
            id=uuid4(),
            project_id=uuid4(),
            user_id=uuid4(),
            provider="vercel",
            status="failed",
            error=error_message,
        )

        assert deployment.status == "failed"
        assert deployment.error == error_message

    def test_table_name_is_correct(self):
        """Test that the table name is correctly set."""
        assert Deployment.__tablename__ == "deployments"

    def test_relationship_attributes_exist(self):
        """Test that relationship attributes are defined."""
        assert hasattr(Deployment, 'project')
        assert hasattr(Deployment, 'user')


@pytest.mark.unit
class TestDeploymentModelConstraints:
    """Test suite for model constraints and validation."""

    def test_deployment_credential_requires_user_id(self):
        """Test that user_id is required for DeploymentCredential."""
        # This test just verifies the field is defined as non-nullable
        # Actual database constraint testing requires integration tests
        from sqlalchemy.inspection import inspect

        mapper = inspect(DeploymentCredential)
        user_id_column = mapper.columns['user_id']

        assert not user_id_column.nullable

    def test_deployment_credential_requires_provider(self):
        """Test that provider is required for DeploymentCredential."""
        from sqlalchemy.inspection import inspect

        mapper = inspect(DeploymentCredential)
        provider_column = mapper.columns['provider']

        assert not provider_column.nullable

    def test_deployment_credential_requires_encrypted_token(self):
        """Test that access_token_encrypted is required for DeploymentCredential."""
        from sqlalchemy.inspection import inspect

        mapper = inspect(DeploymentCredential)
        token_column = mapper.columns['access_token_encrypted']

        assert not token_column.nullable

    def test_deployment_credential_project_id_nullable(self):
        """Test that project_id is nullable (for default credentials)."""
        from sqlalchemy.inspection import inspect

        mapper = inspect(DeploymentCredential)
        project_id_column = mapper.columns['project_id']

        assert project_id_column.nullable

    def test_deployment_requires_provider(self):
        """Test that provider is required for Deployment."""
        from sqlalchemy.inspection import inspect

        mapper = inspect(Deployment)
        provider_column = mapper.columns['provider']

        assert not provider_column.nullable

    def test_deployment_requires_status(self):
        """Test that status is required for Deployment."""
        from sqlalchemy.inspection import inspect

        mapper = inspect(Deployment)
        status_column = mapper.columns['status']

        assert not status_column.nullable
