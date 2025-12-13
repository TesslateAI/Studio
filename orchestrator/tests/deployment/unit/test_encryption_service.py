"""
Unit tests for DeploymentEncryptionService.

Tests encryption/decryption functionality, key management, and error handling
for deployment credential storage.
"""

import pytest
from cryptography.fernet import Fernet
import base64
import hashlib

from app.services.deployment_encryption import (
    DeploymentEncryptionService,
    DeploymentEncryptionError,
    get_deployment_encryption_service,
    reset_deployment_encryption_service,
)


@pytest.mark.unit
class TestDeploymentEncryptionService:
    """Test suite for DeploymentEncryptionService."""

    @pytest.fixture
    def test_key(self):
        """Generate a test Fernet key."""
        return Fernet.generate_key().decode()

    @pytest.fixture
    def encryption_service(self, test_key):
        """Create encryption service instance for testing."""
        return DeploymentEncryptionService(encryption_key=test_key)

    @pytest.fixture(autouse=True)
    def reset_global_service(self):
        """Reset global service instance before each test."""
        reset_deployment_encryption_service()
        yield
        reset_deployment_encryption_service()

    def test_initialization_with_provided_key(self, test_key):
        """Test service initialization with a provided encryption key."""
        service = DeploymentEncryptionService(encryption_key=test_key)
        assert service.cipher_suite is not None

    def test_initialization_with_settings_key(self, monkeypatch):
        """Test service initialization using DEPLOYMENT_ENCRYPTION_KEY from settings."""
        test_key = Fernet.generate_key().decode()

        # Mock settings to return our test key
        class MockSettings:
            deployment_encryption_key = test_key
            secret_key = "test_secret"

        monkeypatch.setattr("app.services.deployment_encryption.get_settings", lambda: MockSettings())

        service = DeploymentEncryptionService()
        assert service.cipher_suite is not None

    def test_initialization_with_derived_key(self, monkeypatch):
        """Test service initialization with key derived from SECRET_KEY."""
        secret = "my_secret_key_for_testing"

        class MockSettings:
            deployment_encryption_key = None
            secret_key = secret

        monkeypatch.setattr("app.services.deployment_encryption.get_settings", lambda: MockSettings())

        service = DeploymentEncryptionService()
        assert service.cipher_suite is not None

    def test_initialization_fails_without_key(self, monkeypatch):
        """Test that initialization fails when no encryption key is available."""
        class MockSettings:
            deployment_encryption_key = None
            secret_key = None

        monkeypatch.setattr("app.services.deployment_encryption.get_settings", lambda: MockSettings())

        with pytest.raises(DeploymentEncryptionError, match="No encryption key available"):
            DeploymentEncryptionService()

    def test_encrypt_plaintext(self, encryption_service):
        """Test encrypting a plaintext credential."""
        plaintext = "my_api_token_12345"
        encrypted = encryption_service.encrypt(plaintext)

        assert encrypted is not None
        assert encrypted != plaintext
        assert len(encrypted) > 0

    def test_encrypt_empty_string(self, encryption_service):
        """Test encrypting an empty string returns empty string."""
        result = encryption_service.encrypt("")
        assert result == ""

    def test_decrypt_encrypted_text(self, encryption_service):
        """Test decrypting an encrypted credential."""
        plaintext = "cloudflare_api_token_xyz"
        encrypted = encryption_service.encrypt(plaintext)
        decrypted = encryption_service.decrypt(encrypted)

        assert decrypted == plaintext

    def test_decrypt_empty_string(self, encryption_service):
        """Test decrypting an empty string returns empty string."""
        result = encryption_service.decrypt("")
        assert result == ""

    def test_encrypt_decrypt_round_trip(self, encryption_service):
        """Test complete round trip of encryption and decryption."""
        test_credentials = [
            "vercel_token_abc123",
            "netlify_token_xyz789",
            "cloudflare_api_key_with_special_chars!@#$%",
            "very_long_token_" + "x" * 1000,
        ]

        for credential in test_credentials:
            encrypted = encryption_service.encrypt(credential)
            decrypted = encryption_service.decrypt(encrypted)
            assert decrypted == credential

    def test_decrypt_with_wrong_key_fails(self, test_key):
        """Test that decryption fails when using the wrong key."""
        # Encrypt with one key
        service1 = DeploymentEncryptionService(encryption_key=test_key)
        encrypted = service1.encrypt("secret_token")

        # Try to decrypt with a different key
        different_key = Fernet.generate_key().decode()
        service2 = DeploymentEncryptionService(encryption_key=different_key)

        with pytest.raises(DeploymentEncryptionError, match="Failed to decrypt credential"):
            service2.decrypt(encrypted)

    def test_decrypt_invalid_data_fails(self, encryption_service):
        """Test that decrypting invalid/corrupted data fails."""
        invalid_data = "this_is_not_valid_encrypted_data"

        with pytest.raises(DeploymentEncryptionError, match="Failed to decrypt credential"):
            encryption_service.decrypt(invalid_data)

    def test_generate_key(self):
        """Test generating a new Fernet key."""
        key1 = DeploymentEncryptionService.generate_key()
        key2 = DeploymentEncryptionService.generate_key()

        assert key1 is not None
        assert key2 is not None
        assert key1 != key2  # Keys should be random
        assert len(key1) > 0

        # Verify the generated key is valid by using it
        service = DeploymentEncryptionService(encryption_key=key1)
        plaintext = "test"
        encrypted = service.encrypt(plaintext)
        decrypted = service.decrypt(encrypted)
        assert decrypted == plaintext

    def test_validate_key_success(self, encryption_service):
        """Test key validation succeeds with a valid key."""
        result = encryption_service.validate_key()
        assert result is True

    def test_validate_key_fails_with_corrupted_cipher(self, test_key):
        """Test key validation fails if cipher is corrupted."""
        service = DeploymentEncryptionService(encryption_key=test_key)

        # Corrupt the cipher suite
        service.cipher_suite = None

        with pytest.raises(DeploymentEncryptionError, match="Encryption key validation failed"):
            service.validate_key()

    def test_encryption_preserves_unicode(self, encryption_service):
        """Test that encryption properly handles unicode characters."""
        unicode_credentials = [
            "token_with_emoji_🔐",
            "日本語トークン",
            "مفتاح_عربي",
            "Ключ_кириллица",
        ]

        for credential in unicode_credentials:
            encrypted = encryption_service.encrypt(credential)
            decrypted = encryption_service.decrypt(encrypted)
            assert decrypted == credential

    def test_encryption_is_deterministic_per_call(self, encryption_service):
        """Test that encrypting the same data twice produces different ciphertexts (due to IV)."""
        plaintext = "same_token_12345"
        encrypted1 = encryption_service.encrypt(plaintext)
        encrypted2 = encryption_service.encrypt(plaintext)

        # Fernet uses random IV, so encrypted outputs should differ
        assert encrypted1 != encrypted2

        # But both should decrypt to the same plaintext
        assert encryption_service.decrypt(encrypted1) == plaintext
        assert encryption_service.decrypt(encrypted2) == plaintext


@pytest.mark.unit
class TestDeploymentEncryptionServiceSingleton:
    """Test suite for global singleton service management."""

    @pytest.fixture(autouse=True)
    def reset_global_service(self):
        """Reset global service instance before and after each test."""
        reset_deployment_encryption_service()
        yield
        reset_deployment_encryption_service()

    def test_get_global_service_creates_instance(self, monkeypatch):
        """Test that get_deployment_encryption_service creates a global instance."""
        test_key = Fernet.generate_key().decode()

        class MockSettings:
            deployment_encryption_key = test_key
            secret_key = "test_secret"

        monkeypatch.setattr("app.services.deployment_encryption.get_settings", lambda: MockSettings())

        service1 = get_deployment_encryption_service()
        service2 = get_deployment_encryption_service()

        # Should return the same instance
        assert service1 is service2

    def test_get_global_service_with_custom_key(self):
        """Test that providing a custom key on first call uses that key."""
        test_key = Fernet.generate_key().decode()

        service = get_deployment_encryption_service(encryption_key=test_key)
        assert service is not None

        # Verify the key works
        plaintext = "test_credential"
        encrypted = service.encrypt(plaintext)
        decrypted = service.decrypt(encrypted)
        assert decrypted == plaintext

    def test_reset_global_service(self, monkeypatch):
        """Test that resetting the global service creates a new instance."""
        test_key = Fernet.generate_key().decode()

        class MockSettings:
            deployment_encryption_key = test_key
            secret_key = "test_secret"

        monkeypatch.setattr("app.services.deployment_encryption.get_settings", lambda: MockSettings())

        service1 = get_deployment_encryption_service()

        reset_deployment_encryption_service()

        service2 = get_deployment_encryption_service()

        # Should be different instances
        assert service1 is not service2


@pytest.mark.unit
class TestDeploymentEncryptionEdgeCases:
    """Test edge cases and error conditions for encryption service."""

    @pytest.fixture
    def encryption_service(self):
        """Create encryption service with a test key."""
        test_key = Fernet.generate_key().decode()
        return DeploymentEncryptionService(encryption_key=test_key)

    def test_encrypt_very_long_credential(self, encryption_service):
        """Test encrypting a very long credential."""
        long_credential = "x" * 100000  # 100KB credential
        encrypted = encryption_service.encrypt(long_credential)
        decrypted = encryption_service.decrypt(encrypted)
        assert decrypted == long_credential

    def test_encrypt_special_characters(self, encryption_service):
        """Test encrypting credentials with special characters."""
        special_credentials = [
            "token!@#$%^&*()_+-=[]{}|;':\",./<>?",
            "token\nwith\nnewlines",
            "token\twith\ttabs",
            "token with spaces",
        ]

        for credential in special_credentials:
            encrypted = encryption_service.encrypt(credential)
            decrypted = encryption_service.decrypt(encrypted)
            assert decrypted == credential

    def test_encryption_with_null_bytes(self, encryption_service):
        """Test that encryption handles null bytes correctly."""
        credential_with_null = "token\x00with\x00nulls"
        encrypted = encryption_service.encrypt(credential_with_null)
        decrypted = encryption_service.decrypt(encrypted)
        assert decrypted == credential_with_null

    def test_decrypt_truncated_ciphertext_fails(self, encryption_service):
        """Test that decrypting truncated ciphertext fails gracefully."""
        plaintext = "valid_token"
        encrypted = encryption_service.encrypt(plaintext)

        # Truncate the encrypted data
        truncated = encrypted[:len(encrypted) // 2]

        with pytest.raises(DeploymentEncryptionError):
            encryption_service.decrypt(truncated)

    def test_decrypt_modified_ciphertext_fails(self, encryption_service):
        """Test that decrypting modified ciphertext fails (integrity check)."""
        plaintext = "valid_token"
        encrypted = encryption_service.encrypt(plaintext)

        # Modify a byte in the middle of the encrypted data
        encrypted_bytes = bytearray(encrypted.encode())
        if len(encrypted_bytes) > 10:
            encrypted_bytes[10] ^= 0xFF  # Flip all bits of one byte
        modified = bytes(encrypted_bytes).decode('latin1')

        with pytest.raises(DeploymentEncryptionError):
            encryption_service.decrypt(modified)
