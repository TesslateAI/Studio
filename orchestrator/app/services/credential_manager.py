from uuid import UUID
"""
Credential Manager for securely storing and retrieving GitHub credentials.
Uses Fernet symmetric encryption for token storage.
"""
from cryptography.fernet import Fernet
from datetime import datetime
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import GitHubCredential
from ..config import get_settings


class CredentialManager:
    """Manages encryption/decryption of GitHub credentials."""

    def __init__(self, encryption_key: Optional[str] = None):
        """
        Initialize the credential manager with an encryption key.

        Args:
            encryption_key: Base64-encoded Fernet key. If None, uses the key from settings.
        """
        settings = get_settings()

        # Use provided key or generate from secret_key
        if encryption_key:
            key = encryption_key.encode()
        else:
            # Derive a Fernet key from the secret key (ensure it's 32 bytes URL-safe base64)
            import base64
            import hashlib

            # Hash the secret key to get consistent 32 bytes
            hashed = hashlib.sha256(settings.secret_key.encode()).digest()
            key = base64.urlsafe_b64encode(hashed)

        self.cipher_suite = Fernet(key)

    def encrypt_token(self, token: str) -> str:
        """
        Encrypt a token using Fernet symmetric encryption.

        Args:
            token: The plaintext token to encrypt

        Returns:
            Base64-encoded encrypted token
        """
        if not token:
            return ""

        encrypted = self.cipher_suite.encrypt(token.encode())
        return encrypted.decode()

    def decrypt_token(self, encrypted_token: str) -> str:
        """
        Decrypt an encrypted token.

        Args:
            encrypted_token: The encrypted token to decrypt

        Returns:
            Plaintext token
        """
        if not encrypted_token:
            return ""

        decrypted = self.cipher_suite.decrypt(encrypted_token.encode())
        return decrypted.decode()

    async def store_oauth_token(
        self,
        db: AsyncSession,
        user_id: UUID,
        access_token: str,
        refresh_token: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        github_username: Optional[str] = None,
        github_email: Optional[str] = None,
        github_user_id: Optional[str] = None
    ) -> GitHubCredential:
        """
        Store OAuth tokens for a user (encrypted).

        Args:
            db: Database session
            user_id: User ID
            access_token: GitHub OAuth access token
            refresh_token: GitHub OAuth refresh token (optional)
            expires_at: Token expiration datetime
            github_username: GitHub username
            github_email: GitHub email
            github_user_id: GitHub user ID

        Returns:
            GitHubCredential object
        """
        # Check if credentials already exist
        result = await db.execute(
            select(GitHubCredential).where(GitHubCredential.user_id == user_id)
        )
        credential = result.scalar_one_or_none()

        # Encrypt tokens
        encrypted_access = self.encrypt_token(access_token)
        encrypted_refresh = self.encrypt_token(refresh_token) if refresh_token else None

        if credential:
            # Update existing credentials
            credential.access_token = encrypted_access
            credential.refresh_token = encrypted_refresh
            credential.token_expires_at = expires_at
            credential.github_username = github_username or credential.github_username
            credential.github_email = github_email or credential.github_email
            credential.github_user_id = github_user_id or credential.github_user_id
            credential.updated_at = datetime.utcnow()
        else:
            # Create new credentials
            credential = GitHubCredential(
                user_id=user_id,
                access_token=encrypted_access,
                refresh_token=encrypted_refresh,
                token_expires_at=expires_at,
                github_username=github_username,
                github_email=github_email,
                github_user_id=github_user_id
            )
            db.add(credential)

        await db.commit()
        await db.refresh(credential)
        return credential


    async def get_credentials(
        self,
        db: AsyncSession,
        user_id: UUID
    ) -> Optional[dict]:
        """
        Get decrypted credentials for a user.

        Args:
            db: Database session
            user_id: User ID

        Returns:
            Dictionary with decrypted credentials or None if not found
        """
        result = await db.execute(
            select(GitHubCredential).where(GitHubCredential.user_id == user_id)
        )
        credential = result.scalar_one_or_none()

        if not credential:
            return None

        # Decrypt OAuth tokens only
        access_token = self.decrypt_token(credential.access_token) if credential.access_token else None
        refresh_token = self.decrypt_token(credential.refresh_token) if credential.refresh_token else None

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_expires_at": credential.token_expires_at,
            "github_username": credential.github_username,
            "github_email": credential.github_email,
            "github_user_id": credential.github_user_id,
            "scope": credential.scope
        }

    async def get_access_token(
        self,
        db: AsyncSession,
        user_id: UUID
    ) -> Optional[str]:
        """
        Get the decrypted OAuth access token for a user.

        Args:
            db: Database session
            user_id: User ID

        Returns:
            Decrypted OAuth access token, or None if not found
        """
        credentials = await self.get_credentials(db, user_id)
        if not credentials:
            return None

        # Return OAuth access token only
        return credentials.get("access_token")

    async def delete_credentials(
        self,
        db: AsyncSession,
        user_id: UUID
    ) -> bool:
        """
        Delete credentials for a user.

        Args:
            db: Database session
            user_id: User ID

        Returns:
            True if credentials were deleted, False if not found
        """
        result = await db.execute(
            select(GitHubCredential).where(GitHubCredential.user_id == user_id)
        )
        credential = result.scalar_one_or_none()

        if not credential:
            return False

        await db.delete(credential)
        await db.commit()
        return True

    async def has_credentials(
        self,
        db: AsyncSession,
        user_id: UUID
    ) -> bool:
        """
        Check if a user has stored credentials.

        Args:
            db: Database session
            user_id: User ID

        Returns:
            True if credentials exist, False otherwise
        """
        result = await db.execute(
            select(GitHubCredential).where(GitHubCredential.user_id == user_id)
        )
        credential = result.scalar_one_or_none()
        return credential is not None


# Global instance
_credential_manager: Optional[CredentialManager] = None


def get_credential_manager() -> CredentialManager:
    """Get or create the global credential manager instance."""
    global _credential_manager
    if _credential_manager is None:
        _credential_manager = CredentialManager()
    return _credential_manager
