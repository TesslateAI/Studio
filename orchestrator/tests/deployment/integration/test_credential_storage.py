"""
Integration tests for deployment credential storage workflow.

Tests the complete flow of encrypting, storing, and retrieving deployment credentials
using both the encryption service and the model layer (with mocked database operations).
"""

import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock
from cryptography.fernet import Fernet

from app.models import DeploymentCredential
from app.services.deployment_encryption import (
    DeploymentEncryptionService,
    get_deployment_encryption_service,
    reset_deployment_encryption_service,
)


@pytest.mark.integration
class TestCredentialStorageWorkflow:
    """Integration tests for the complete credential storage workflow."""

    @pytest.fixture(autouse=True)
    def reset_service(self):
        """Reset encryption service before each test."""
        reset_deployment_encryption_service()
        yield
        reset_deployment_encryption_service()

    @pytest.fixture
    def encryption_service(self):
        """Create encryption service for testing."""
        test_key = Fernet.generate_key().decode()
        return DeploymentEncryptionService(encryption_key=test_key)

    def test_store_and_retrieve_credential_flow(self, encryption_service):
        """Test the complete flow of storing and retrieving an encrypted credential."""
        # Step 1: User provides their API token
        plaintext_token = "vercel_api_token_abc123xyz"

        # Step 2: Encrypt the credential before storage
        encrypted_token = encryption_service.encrypt(plaintext_token)

        # Step 3: Create model instance with encrypted credential
        user_id = uuid4()
        credential = DeploymentCredential(
            id=uuid4(),
            user_id=user_id,
            provider="vercel",
            access_token_encrypted=encrypted_token,
            provider_metadata={"team_id": "team_123"},
        )

        # Step 4: Verify credential is stored with encryption
        assert credential.access_token_encrypted != plaintext_token
        assert credential.provider_metadata["team_id"] == "team_123"

        # Step 5: Simulate retrieval and decryption
        decrypted_token = encryption_service.decrypt(credential.access_token_encrypted)

        # Verify the complete round trip
        assert decrypted_token == plaintext_token

    def test_multiple_providers_workflow(self, encryption_service):
        """Test storing credentials for multiple providers."""
        user_id = uuid4()
        providers = {
            "vercel": {
                "token": "vercel_token_xyz",
                "provider_metadata": {"team_id": "vercel_team"},
            },
            "netlify": {
                "token": "netlify_token_abc",
                "provider_metadata": {"site_id": "netlify_site"},
            },
            "cloudflare": {
                "token": "cloudflare_token_123",
                "provider_metadata": {"account_id": "cf_account", "dispatch_namespace": "my-apps"},
            },
        }

        credentials = []
        for provider_name, provider_data in providers.items():
            encrypted_token = encryption_service.encrypt(provider_data["token"])

            credential = DeploymentCredential(
                id=uuid4(),
                user_id=user_id,
                provider=provider_name,
                access_token_encrypted=encrypted_token,
                provider_metadata=provider_data["provider_metadata"],
            )
            credentials.append(credential)

        # Verify all credentials
        assert len(credentials) == 3

        for credential in credentials:
            decrypted_token = encryption_service.decrypt(credential.access_token_encrypted)
            original_data = providers[credential.provider]

            assert decrypted_token == original_data["token"]
            assert credential.provider_metadata == original_data["provider_metadata"]

    def test_default_and_override_workflow(self, encryption_service):
        """Test the workflow of storing default credentials and project-specific overrides."""
        user_id = uuid4()
        project_id = uuid4()

        # Step 1: Store user's default Vercel credential
        default_token = "vercel_default_token_user_level"
        encrypted_default = encryption_service.encrypt(default_token)

        default_credential = DeploymentCredential(
            id=uuid4(),
            user_id=user_id,
            provider="vercel",
            access_token_encrypted=encrypted_default,
            provider_metadata={"team_id": "default_team"},
        )

        # Step 2: Store project-specific override
        override_token = "vercel_override_token_project_specific"
        encrypted_override = encryption_service.encrypt(override_token)

        override_credential = DeploymentCredential(
            id=uuid4(),
            user_id=user_id,
            project_id=project_id,
            provider="vercel",
            access_token_encrypted=encrypted_override,
            provider_metadata={"team_id": "project_team"},
        )

        # Step 3: Verify default credential
        decrypted_default = encryption_service.decrypt(default_credential.access_token_encrypted)
        assert decrypted_default == default_token
        assert default_credential.provider_metadata["team_id"] == "default_team"
        assert default_credential.project_id is None

        # Step 4: Verify project-specific override
        decrypted_override = encryption_service.decrypt(override_credential.access_token_encrypted)
        assert decrypted_override == override_token
        assert override_credential.provider_metadata["team_id"] == "project_team"
        assert override_credential.project_id == project_id

    def test_credential_update_workflow(self, encryption_service):
        """Test updating an existing credential with a new token."""
        user_id = uuid4()

        # Create initial credential
        old_token = "old_cloudflare_token"
        encrypted_old = encryption_service.encrypt(old_token)

        credential = DeploymentCredential(
            id=uuid4(),
            user_id=user_id,
            provider="cloudflare",
            access_token_encrypted=encrypted_old,
            provider_metadata={"account_id": "account_123"},
        )

        # Verify initial state
        assert encryption_service.decrypt(credential.access_token_encrypted) == old_token

        # Update with new token (simulating token refresh)
        new_token = "new_cloudflare_token_refreshed"
        encrypted_new = encryption_service.encrypt(new_token)

        credential.access_token_encrypted = encrypted_new
        credential.provider_metadata = {"account_id": "account_456"}

        # Verify the update
        decrypted_token = encryption_service.decrypt(credential.access_token_encrypted)
        assert decrypted_token == new_token
        assert credential.provider_metadata["account_id"] == "account_456"

    def test_retrieve_credentials_for_deployment(self, encryption_service):
        """Test the workflow of retrieving credentials when preparing to deploy."""
        user_id = uuid4()

        # Setup: User has credentials for multiple providers
        credentials_data = {
            "vercel": "vercel_token_for_deployment",
            "cloudflare": "cloudflare_token_for_deployment",
        }

        credentials = []
        for provider, token in credentials_data.items():
            encrypted = encryption_service.encrypt(token)
            credential = DeploymentCredential(
                id=uuid4(),
                user_id=user_id,
                provider=provider,
                access_token_encrypted=encrypted,
            )
            credentials.append(credential)

        # Simulate deployment: Find credential for specific provider
        target_provider = "cloudflare"
        target_credential = next(
            cred for cred in credentials if cred.provider == target_provider
        )

        # Decrypt for deployment use
        decrypted_token = encryption_service.decrypt(target_credential.access_token_encrypted)

        assert decrypted_token == credentials_data[target_provider]

    def test_key_rotation_scenario(self):
        """Test scenario where encryption key is rotated (requires re-encryption)."""
        # Encrypt with old key
        old_key = Fernet.generate_key().decode()
        old_service = DeploymentEncryptionService(encryption_key=old_key)

        token = "sensitive_api_token"
        encrypted_old = old_service.encrypt(token)

        # Store with old encryption
        credential = DeploymentCredential(
            id=uuid4(),
            user_id=uuid4(),
            provider="vercel",
            access_token_encrypted=encrypted_old,
        )

        # Verify we can decrypt with old key
        assert old_service.decrypt(credential.access_token_encrypted) == token

        # Simulate key rotation: decrypt with old key, re-encrypt with new key
        new_key = Fernet.generate_key().decode()
        new_service = DeploymentEncryptionService(encryption_key=new_key)

        # Decrypt with old key
        decrypted = old_service.decrypt(credential.access_token_encrypted)

        # Re-encrypt with new key
        encrypted_new = new_service.encrypt(decrypted)

        # Update credential
        credential.access_token_encrypted = encrypted_new

        # Verify we can now decrypt with new key
        final_decrypted = new_service.decrypt(credential.access_token_encrypted)
        assert final_decrypted == token

    def test_concurrent_provider_setup(self, encryption_service):
        """Test setting up credentials for multiple providers."""
        user_id = uuid4()

        providers_setup = [
            ("vercel", "vercel_token_1", {"team_id": "team_1"}),
            ("netlify", "netlify_token_2", {"site_id": "site_2"}),
            ("cloudflare", "cf_token_3", {"account_id": "acc_3"}),
        ]

        credentials = []
        for provider, token, metadata in providers_setup:
            encrypted = encryption_service.encrypt(token)
            credential = DeploymentCredential(
                id=uuid4(),
                user_id=user_id,
                provider=provider,
                access_token_encrypted=encrypted,
                metadata=metadata,
            )
            credentials.append(credential)

        # Verify all providers are set up
        assert len(credentials) == 3

        # Verify each can be decrypted
        for credential in credentials:
            decrypted = encryption_service.decrypt(credential.access_token_encrypted)
            assert len(decrypted) > 0

    def test_project_isolation(self, encryption_service):
        """Test that project-specific credentials are properly isolated."""
        user_id = uuid4()
        project1_id = uuid4()
        project2_id = uuid4()

        # Store different credentials for each project
        token1 = "project1_vercel_token"
        encrypted1 = encryption_service.encrypt(token1)
        credential1 = DeploymentCredential(
            id=uuid4(),
            user_id=user_id,
            project_id=project1_id,
            provider="vercel",
            access_token_encrypted=encrypted1,
        )

        token2 = "project2_vercel_token"
        encrypted2 = encryption_service.encrypt(token2)
        credential2 = DeploymentCredential(
            id=uuid4(),
            user_id=user_id,
            project_id=project2_id,
            provider="vercel",
            access_token_encrypted=encrypted2,
        )

        # Verify isolation
        decrypted1 = encryption_service.decrypt(credential1.access_token_encrypted)
        decrypted2 = encryption_service.decrypt(credential2.access_token_encrypted)

        assert decrypted1 == token1
        assert decrypted2 == token2
        assert decrypted1 != decrypted2
        assert credential1.project_id != credential2.project_id

    def test_global_service_consistency(self, monkeypatch):
        """Test that the global singleton service maintains consistency."""
        # Set up a test key in settings
        test_key = Fernet.generate_key().decode()

        class MockSettings:
            deployment_encryption_key = test_key
            secret_key = "test_secret"

        monkeypatch.setattr(
            "app.services.deployment_encryption.get_settings", lambda: MockSettings()
        )

        # Get global service instance
        service1 = get_deployment_encryption_service()

        # Store a credential using the global service
        token = "global_service_token"
        encrypted = service1.encrypt(token)

        credential = DeploymentCredential(
            id=uuid4(),
            user_id=uuid4(),
            provider="vercel",
            access_token_encrypted=encrypted,
        )

        # Get the global service again (should be same instance)
        service2 = get_deployment_encryption_service()

        # Decrypt using the second reference
        decrypted = service2.decrypt(credential.access_token_encrypted)

        assert decrypted == token
        assert service1 is service2  # Same instance

    def test_provider_metadata_variations(self, encryption_service):
        """Test different metadata structures for different providers."""
        user_id = uuid4()

        # Vercel with team info
        vercel_cred = DeploymentCredential(
            id=uuid4(),
            user_id=user_id,
            provider="vercel",
            access_token_encrypted=encryption_service.encrypt("vercel_token"),
            provider_metadata={"team_id": "team_123", "team_name": "My Team"},
        )

        # Cloudflare with account and namespace
        cloudflare_cred = DeploymentCredential(
            id=uuid4(),
            user_id=user_id,
            provider="cloudflare",
            access_token_encrypted=encryption_service.encrypt("cf_token"),
            provider_metadata={"account_id": "acc_456", "dispatch_namespace": "my-apps"},
        )

        # Netlify with minimal metadata
        netlify_cred = DeploymentCredential(
            id=uuid4(),
            user_id=user_id,
            provider="netlify",
            access_token_encrypted=encryption_service.encrypt("netlify_token"),
            provider_metadata={},  # No additional metadata needed
        )

        # Verify all credentials work correctly with their metadata
        assert vercel_cred.provider_metadata["team_id"] == "team_123"
        assert cloudflare_cred.provider_metadata["dispatch_namespace"] == "my-apps"
        assert netlify_cred.provider_metadata == {}

    def test_error_handling_in_workflow(self, encryption_service):
        """Test error handling during credential encryption/decryption workflow."""
        # Test with invalid encrypted data
        credential = DeploymentCredential(
            id=uuid4(),
            user_id=uuid4(),
            provider="vercel",
            access_token_encrypted="invalid_encrypted_data",
        )

        # Attempting to decrypt should raise an error
        from app.services.deployment_encryption import DeploymentEncryptionError

        with pytest.raises(DeploymentEncryptionError):
            encryption_service.decrypt(credential.access_token_encrypted)

    def test_empty_token_handling(self, encryption_service):
        """Test handling of empty tokens in the workflow."""
        # Encrypting empty string should return empty string
        encrypted_empty = encryption_service.encrypt("")
        assert encrypted_empty == ""

        # Can create credential with empty encrypted token
        credential = DeploymentCredential(
            id=uuid4(),
            user_id=uuid4(),
            provider="vercel",
            access_token_encrypted=encrypted_empty,
        )

        # Decrypting empty string should return empty string
        decrypted = encryption_service.decrypt(credential.access_token_encrypted)
        assert decrypted == ""
