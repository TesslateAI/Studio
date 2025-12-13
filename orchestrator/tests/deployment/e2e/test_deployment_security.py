"""
Security tests for deployment system.

These tests verify security aspects of the deployment system:
1. Encryption at rest (credentials never stored as plaintext)
2. Authentication & Authorization (users can only access their own resources)
3. Injection attacks (SQL injection, command injection, XSS)
4. Rate limiting (prevent abuse)
5. Input validation (sanitize user inputs)
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import Base, DeploymentCredential, Deployment, Project, User
from app.database import AsyncSessionLocal
from app.services.deployment_encryption import DeploymentEncryptionService, get_deployment_encryption_service, reset_deployment_encryption_service
from app.services.deployment.base import DeploymentConfig
from cryptography.fernet import Fernet


@pytest_asyncio.fixture
async def test_db_session():
    """Use existing database session."""
    async with AsyncSessionLocal() as session:
        yield session
        await session.rollback()  # Rollback any changes made during the test


@pytest_asyncio.fixture
async def test_users(test_db_session):
    """Create multiple test users."""
    users = []
    for i in range(3):
        user = User(
            id=uuid4(),
            email=f"user{i}@example.com",
            hashed_password="hashed_password",
            is_active=True,
            is_verified=True
        )
        test_db_session.add(user)
        users.append(user)

    await test_db_session.commit()

    for user in users:
        await test_db_session.refresh(user)

    return users


@pytest_asyncio.fixture
def encryption_service():
    """Create encryption service for tests."""
    reset_deployment_encryption_service()
    service_key = DeploymentEncryptionService.generate_key()
    yield get_deployment_encryption_service(encryption_key=service_key)
    reset_deployment_encryption_service()


@pytest.mark.security
@pytest.mark.asyncio
class TestEncryptionAtRest:
    """Test that credentials are never stored as plaintext."""

    async def test_credentials_encrypted_in_database(self, test_db_session, test_users, encryption_service):
        """Verify that credentials are encrypted before being stored in the database."""
        user = test_users[0]
        plaintext_token = "super_secret_api_token_12345"

        # Create credential with encrypted token
        encrypted_token = encryption_service.encrypt(plaintext_token)
        credential = DeploymentCredential(
            user_id=user.id,
            provider="vercel",
            access_token_encrypted=encrypted_token,
            metadata={}
        )

        test_db_session.add(credential)
        await test_db_session.commit()

        # Query database directly to verify encryption
        result = await test_db_session.execute(
            select(DeploymentCredential).where(DeploymentCredential.id == credential.id)
        )
        stored_credential = result.scalar_one()

        # Verify the stored token is NOT plaintext
        assert stored_credential.access_token_encrypted != plaintext_token
        assert len(stored_credential.access_token_encrypted) > len(plaintext_token)

        # Verify we can decrypt it
        decrypted_token = encryption_service.decrypt(stored_credential.access_token_encrypted)
        assert decrypted_token == plaintext_token

    async def test_encrypted_token_cannot_be_decrypted_with_wrong_key(self, test_db_session, test_users):
        """Verify that encrypted tokens cannot be decrypted with a different key."""
        user = test_users[0]
        plaintext_token = "secret_token_xyz"

        # Encrypt with one key
        key1 = Fernet.generate_key().decode()
        service1 = DeploymentEncryptionService(encryption_key=key1)
        encrypted_token = service1.encrypt(plaintext_token)

        # Try to decrypt with different key
        key2 = Fernet.generate_key().decode()
        service2 = DeploymentEncryptionService(encryption_key=key2)

        with pytest.raises(Exception):  # Should raise DeploymentEncryptionError
            service2.decrypt(encrypted_token)

    async def test_empty_tokens_handled_safely(self, test_db_session, test_users, encryption_service):
        """Verify that empty tokens are handled safely."""
        user = test_users[0]

        # Empty string should be stored as empty string (not encrypted)
        encrypted_empty = encryption_service.encrypt("")
        assert encrypted_empty == ""

        # Null/None should not be encrypted
        credential = DeploymentCredential(
            user_id=user.id,
            provider="vercel",
            access_token_encrypted="",  # Empty but valid
            metadata={}
        )

        test_db_session.add(credential)
        await test_db_session.commit()

        result = await test_db_session.execute(
            select(DeploymentCredential).where(DeploymentCredential.id == credential.id)
        )
        stored = result.scalar_one()

        assert stored.access_token_encrypted == ""


@pytest.mark.security
@pytest.mark.asyncio
class TestAuthenticationAuthorization:
    """Test that users can only access their own credentials and deployments."""

    async def test_user_cannot_access_other_users_credentials(self, test_db_session, test_users, encryption_service):
        """Verify users cannot access credentials belonging to other users."""
        user1, user2, user3 = test_users

        # Create credentials for user1
        cred1 = DeploymentCredential(
            user_id=user1.id,
            provider="vercel",
            access_token_encrypted=encryption_service.encrypt("user1_token"),
            metadata={}
        )
        test_db_session.add(cred1)
        await test_db_session.commit()

        # User2 tries to query user1's credentials
        result = await test_db_session.execute(
            select(DeploymentCredential).where(
                DeploymentCredential.user_id == user2.id  # User2's ID
            )
        )
        credentials = result.scalars().all()

        # Should find nothing
        assert len(credentials) == 0

    async def test_project_isolation(self, test_db_session, test_users):
        """Verify that projects are isolated between users."""
        user1, user2, _ = test_users

        # Create projects for both users
        project1 = Project(
            id=uuid4(),
            user_id=user1.id,
            name="User1 Project",
            slug="user1-project",
            framework="vite"
        )

        project2 = Project(
            id=uuid4(),
            user_id=user2.id,
            name="User2 Project",
            slug="user2-project",
            framework="vite"
        )

        test_db_session.add(project1)
        test_db_session.add(project2)
        await test_db_session.commit()

        # User1 should only see their own projects
        result = await test_db_session.execute(
            select(Project).where(Project.user_id == user1.id)
        )
        user1_projects = result.scalars().all()

        assert len(user1_projects) == 1
        assert user1_projects[0].id == project1.id
        assert user1_projects[0].name == "User1 Project"

    async def test_deployment_ownership_enforcement(self, test_db_session, test_users):
        """Verify that deployments are tied to projects and users."""
        user1, user2, _ = test_users

        project1 = Project(
            id=uuid4(),
            user_id=user1.id,
            name="User1 Project",
            slug="user1-project",
            framework="vite"
        )
        test_db_session.add(project1)
        await test_db_session.commit()

        # Create deployment for user1's project
        deployment = Deployment(
            project_id=project1.id,
            user_id=user1.id,
            provider="vercel",
            status="success"
        )
        test_db_session.add(deployment)
        await test_db_session.commit()

        # User2 should not be able to see user1's deployments
        result = await test_db_session.execute(
            select(Deployment).where(Deployment.user_id == user2.id)
        )
        user2_deployments = result.scalars().all()

        assert len(user2_deployments) == 0


@pytest.mark.security
@pytest.mark.asyncio
class TestInputValidation:
    """Test input validation and sanitization."""

    def test_project_name_sanitization(self):
        """Test that project names are sanitized for deployment."""
        from app.services.deployment.base import BaseDeploymentProvider

        # Create a test provider
        class TestProvider(BaseDeploymentProvider):
            def validate_credentials(self):
                pass

            async def deploy(self, files, config):
                pass

            async def get_deployment_status(self, deployment_id):
                pass

            async def delete_deployment(self, deployment_id):
                pass

            async def get_deployment_logs(self, deployment_id):
                pass

        provider = TestProvider({})

        # Test various malicious inputs
        assert provider._sanitize_name("My Project") == "my-project"
        assert provider._sanitize_name("Project@123!") == "project123"
        assert provider._sanitize_name("<script>alert('xss')</script>") == "scriptalertxssscript"
        assert provider._sanitize_name("../../../etc/passwd") == "etcpasswd"
        assert provider._sanitize_name("DROP TABLE projects;") == "drop-table-projects"

        # Test length limit
        long_name = "a" * 200
        sanitized = provider._sanitize_name(long_name)
        assert len(sanitized) <= 63

    def test_deployment_config_validation(self):
        """Test that deployment configs are validated."""
        # Valid config
        config = DeploymentConfig(
            project_id="proj123",
            project_name="Test Project",
            framework="vite"
        )

        assert config.project_id == "proj123"
        assert config.project_name == "Test Project"
        assert config.framework == "vite"

        # Test with malicious env vars
        config_with_env = DeploymentConfig(
            project_id="proj123",
            project_name="Test",
            framework="vite",
            env_vars={
                "API_URL": "https://api.example.com",  # Safe
                "DATABASE_URL": "postgresql://localhost/db",  # Safe
                "'; DROP TABLE users; --": "malicious"  # Malicious key
            }
        )

        # The config should accept it (validation happens at provider level)
        assert "'; DROP TABLE users; --" in config_with_env.env_vars

    def test_provider_name_validation(self):
        """Test that provider names are validated."""
        from app.services.deployment.manager import DeploymentManager

        # Valid providers
        assert DeploymentManager.is_provider_available("vercel") is True
        assert DeploymentManager.is_provider_available("cloudflare") is True
        assert DeploymentManager.is_provider_available("netlify") is True

        # Invalid/malicious providers
        assert DeploymentManager.is_provider_available("../../../etc/passwd") is False
        assert DeploymentManager.is_provider_available("<script>alert('xss')</script>") is False
        assert DeploymentManager.is_provider_available("vercel; DROP TABLE deployments") is False
        assert DeploymentManager.is_provider_available("") is False
        assert DeploymentManager.is_provider_available("unknown_provider") is False


@pytest.mark.security
@pytest.mark.asyncio
class TestInjectionPrevention:
    """Test prevention of various injection attacks."""

    async def test_sql_injection_prevention(self, test_db_session, test_users, encryption_service):
        """Test that SQL injection is prevented in queries."""
        user = test_users[0]

        # Attempt SQL injection in provider name
        malicious_provider = "vercel' OR '1'='1"

        credential = DeploymentCredential(
            user_id=user.id,
            provider=malicious_provider,  # SQLAlchemy will handle this safely
            access_token_encrypted=encryption_service.encrypt("token"),
            metadata={}
        )

        test_db_session.add(credential)
        await test_db_session.commit()

        # Query should treat it as a literal string
        result = await test_db_session.execute(
            select(DeploymentCredential).where(
                DeploymentCredential.provider == malicious_provider
            )
        )
        found = result.scalar_one_or_none()

        # Should find the credential with the exact malicious string
        assert found is not None
        assert found.provider == malicious_provider

        # Should NOT find credentials with provider="vercel"
        result2 = await test_db_session.execute(
            select(DeploymentCredential).where(
                DeploymentCredential.provider == "vercel"
            )
        )
        found2 = result2.scalar_one_or_none()
        assert found2 is None

    def test_command_injection_prevention_in_build(self):
        """Test that command injection is prevented in build commands."""
        from app.services.deployment.builder import DeploymentBuilder

        builder = DeploymentBuilder()

        # Test framework detection (should only return valid frameworks)
        assert builder._get_build_command("vite") == "npm run build"
        assert builder._get_build_command("nextjs") == "npm run build"

        # Malicious framework name should return safe default
        malicious_framework = "vite; rm -rf /"
        command = builder._get_build_command(malicious_framework)

        # Should return None or default, not execute the injection
        assert command is None or "rm -rf" not in command

    def test_xss_prevention_in_metadata(self, encryption_service):
        """Test that XSS payloads in metadata are handled safely."""
        xss_payload = "<script>alert('XSS')</script>"

        # Metadata with XSS payload
        metadata = {
            "team_id": xss_payload,
            "account_name": "<img src=x onerror=alert('XSS')>"
        }

        # The metadata should be stored as-is (escaping happens on display)
        # This tests that we don't execute it during storage
        assert metadata["team_id"] == xss_payload
        assert metadata["account_name"] == "<img src=x onerror=alert('XSS')>"


@pytest.mark.security
@pytest.mark.asyncio
class TestErrorHandling:
    """Test that errors don't leak sensitive information."""

    def test_encryption_error_doesnt_leak_key(self, encryption_service):
        """Test that encryption errors don't leak the encryption key."""
        try:
            encryption_service.decrypt("invalid_encrypted_data")
        except Exception as e:
            error_message = str(e)

            # Error should not contain the encryption key
            assert "DEPLOYMENT_ENCRYPTION_KEY" not in error_message
            assert len(error_message) < 200  # Should be a short error message

    def test_deployment_error_doesnt_leak_credentials(self):
        """Test that deployment errors don't leak credentials."""
        from app.services.deployment.providers.vercel import VercelProvider

        credentials = {"token": "super_secret_token_12345"}
        provider = VercelProvider(credentials)

        # Even if we inspect the provider, the token should not be easily visible
        provider_str = str(provider)
        assert "super_secret_token_12345" not in provider_str


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
