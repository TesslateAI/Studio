"""
Deployment Encryption Service for securely storing and retrieving deployment credentials.
Uses Fernet symmetric encryption for token storage.

This service provides encryption/decryption functionality for deployment provider credentials
(Cloudflare, Vercel, Netlify, etc.) with comprehensive error handling and debug logging.
"""
import logging
import base64
import hashlib
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken

from ..config import get_settings

logger = logging.getLogger(__name__)


class DeploymentEncryptionError(Exception):
    """Base exception for deployment encryption errors."""
    pass


class DeploymentEncryptionService:
    """
    Manages encryption/decryption of deployment provider credentials.

    This service uses Fernet symmetric encryption to securely store API tokens
    and access keys for various deployment providers.
    """

    def __init__(self, encryption_key: Optional[str] = None):
        """
        Initialize the deployment encryption service.

        Args:
            encryption_key: Base64-encoded Fernet key. If None, derives key from settings.

        Raises:
            DeploymentEncryptionError: If encryption key is invalid or missing.
        """
        settings = get_settings()

        try:
            # Use provided key or derive from settings
            if encryption_key:
                logger.debug("Using provided encryption key for deployment credentials")
                key = encryption_key.encode()
            elif settings.deployment_encryption_key:
                logger.debug("Using DEPLOYMENT_ENCRYPTION_KEY from settings")
                key = settings.deployment_encryption_key.encode()
            else:
                # Derive a Fernet key from the secret key (ensure it's 32 bytes URL-safe base64)
                logger.debug("Deriving deployment encryption key from SECRET_KEY")
                if not settings.secret_key:
                    raise DeploymentEncryptionError(
                        "No encryption key available. Set DEPLOYMENT_ENCRYPTION_KEY or SECRET_KEY."
                    )

                # Hash the secret key to get consistent 32 bytes
                hashed = hashlib.sha256(settings.secret_key.encode()).digest()
                key = base64.urlsafe_b64encode(hashed)
                logger.debug("Successfully derived encryption key from SECRET_KEY")

            self.cipher_suite = Fernet(key)
            logger.info("Deployment encryption service initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize deployment encryption service: {e}", exc_info=True)
            raise DeploymentEncryptionError(f"Encryption service initialization failed: {e}") from e

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a plaintext string using Fernet symmetric encryption.

        Args:
            plaintext: The plaintext credential/token to encrypt

        Returns:
            Base64-encoded encrypted token

        Raises:
            DeploymentEncryptionError: If encryption fails
        """
        if not plaintext:
            logger.debug("Attempted to encrypt empty string, returning empty")
            return ""

        try:
            logger.debug(f"Encrypting credential (length: {len(plaintext)} chars)")
            encrypted = self.cipher_suite.encrypt(plaintext.encode())
            result = encrypted.decode()
            logger.debug(f"Successfully encrypted credential (encrypted length: {len(result)} chars)")
            return result

        except Exception as e:
            logger.error(f"Encryption failed: {e}", exc_info=True)
            raise DeploymentEncryptionError(f"Failed to encrypt credential: {e}") from e

    def decrypt(self, encrypted_text: str) -> str:
        """
        Decrypt an encrypted credential.

        Args:
            encrypted_text: The encrypted credential to decrypt

        Returns:
            Plaintext credential/token

        Raises:
            DeploymentEncryptionError: If decryption fails (e.g., invalid key, corrupted data)
        """
        if not encrypted_text:
            logger.debug("Attempted to decrypt empty string, returning empty")
            return ""

        try:
            logger.debug(f"Decrypting credential (encrypted length: {len(encrypted_text)} chars)")
            decrypted = self.cipher_suite.decrypt(encrypted_text.encode())
            result = decrypted.decode()
            logger.debug(f"Successfully decrypted credential (plaintext length: {len(result)} chars)")
            return result

        except InvalidToken as e:
            logger.error("Decryption failed: Invalid token or wrong encryption key", exc_info=True)
            raise DeploymentEncryptionError(
                "Failed to decrypt credential. The encryption key may have changed or the data is corrupted."
            ) from e
        except Exception as e:
            logger.error(f"Decryption failed with unexpected error: {e}", exc_info=True)
            raise DeploymentEncryptionError(f"Failed to decrypt credential: {e}") from e

    @staticmethod
    def generate_key() -> str:
        """
        Generate a new Fernet encryption key.

        Returns:
            Base64-encoded Fernet key suitable for use as DEPLOYMENT_ENCRYPTION_KEY

        Example:
            >>> key = DeploymentEncryptionService.generate_key()
            >>> print(f"DEPLOYMENT_ENCRYPTION_KEY={key}")
        """
        key = Fernet.generate_key()
        result = key.decode()
        logger.info("Generated new Fernet encryption key")
        logger.debug(f"New key length: {len(result)} chars")
        return result

    def validate_key(self) -> bool:
        """
        Validate that the encryption key works by performing a round-trip encryption/decryption.

        Returns:
            True if the key is valid and working

        Raises:
            DeploymentEncryptionError: If validation fails
        """
        try:
            logger.debug("Validating encryption key with round-trip test")
            test_string = "test_validation_12345"
            encrypted = self.encrypt(test_string)
            decrypted = self.decrypt(encrypted)

            if decrypted != test_string:
                logger.error("Key validation failed: decrypted value does not match original")
                raise DeploymentEncryptionError("Encryption key validation failed: data mismatch")

            logger.info("Encryption key validated successfully")
            return True

        except Exception as e:
            logger.error(f"Encryption key validation failed: {e}", exc_info=True)
            raise DeploymentEncryptionError(f"Encryption key validation failed: {e}") from e


# Global singleton instance
_deployment_encryption_service: Optional[DeploymentEncryptionService] = None


def get_deployment_encryption_service(encryption_key: Optional[str] = None) -> DeploymentEncryptionService:
    """
    Get or create the global deployment encryption service instance.

    Args:
        encryption_key: Optional custom encryption key. If provided for the first time,
                       it will be used to initialize the global instance.

    Returns:
        The global DeploymentEncryptionService instance

    Raises:
        DeploymentEncryptionError: If service initialization fails
    """
    global _deployment_encryption_service

    if _deployment_encryption_service is None:
        logger.debug("Initializing global deployment encryption service")
        _deployment_encryption_service = DeploymentEncryptionService(encryption_key=encryption_key)
        logger.info("Global deployment encryption service created")

    return _deployment_encryption_service


def reset_deployment_encryption_service():
    """
    Reset the global deployment encryption service instance.

    This is primarily useful for testing or when the encryption key changes.
    """
    global _deployment_encryption_service
    logger.warning("Resetting global deployment encryption service")
    _deployment_encryption_service = None
