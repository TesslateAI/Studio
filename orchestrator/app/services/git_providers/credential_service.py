"""
Git Provider Credential Service.

Unified credential storage and retrieval for all Git providers.
Uses Fernet symmetric encryption for token storage.
"""

import base64
import hashlib
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from cryptography.fernet import Fernet
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from ...models import GitProviderCredential
from .base import GitProviderType

logger = logging.getLogger(__name__)


class GitProviderCredentialService:
    """
    Manages encryption/decryption and storage of Git provider credentials.

    Supports GitHub, GitLab, and Bitbucket OAuth credentials.
    """

    def __init__(self, encryption_key: str | None = None):
        """
        Initialize the credential service with an encryption key.

        Args:
            encryption_key: Base64-encoded Fernet key. If None, derives from secret_key.
        """
        settings = get_settings()

        # Use provided key or derive from secret_key
        if encryption_key:
            key = encryption_key.encode()
        else:
            # Derive a Fernet key from the secret key (ensure it's 32 bytes URL-safe base64)
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

    async def store_credential(
        self,
        db: AsyncSession,
        user_id: UUID,
        provider: GitProviderType,
        access_token: str,
        refresh_token: str | None = None,
        expires_at: datetime | None = None,
        provider_username: str = "",
        provider_email: str | None = None,
        provider_user_id: str | None = None,
        scope: str | None = None,
    ) -> GitProviderCredential:
        """
        Store OAuth credentials for a user and provider (encrypted).

        Upserts - updates if exists, creates if not.

        Args:
            db: Database session
            user_id: User ID
            provider: Git provider type
            access_token: OAuth access token
            refresh_token: OAuth refresh token (optional)
            expires_at: Token expiration datetime
            provider_username: Username on the provider
            provider_email: Email on the provider
            provider_user_id: User ID on the provider
            scope: Granted OAuth scopes

        Returns:
            GitProviderCredential object
        """
        # Check if credentials already exist for this user and provider
        result = await db.execute(
            select(GitProviderCredential).where(
                and_(
                    GitProviderCredential.user_id == user_id,
                    GitProviderCredential.provider == provider.value,
                )
            )
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
            credential.provider_username = provider_username or credential.provider_username
            credential.provider_email = provider_email or credential.provider_email
            credential.provider_user_id = provider_user_id or credential.provider_user_id
            credential.scope = scope or credential.scope
            credential.updated_at = datetime.utcnow()
            logger.info(
                f"[GIT CREDENTIALS] Updated {provider.value} credentials for user {user_id}"
            )
        else:
            # Create new credentials
            credential = GitProviderCredential(
                user_id=user_id,
                provider=provider.value,
                access_token=encrypted_access,
                refresh_token=encrypted_refresh,
                token_expires_at=expires_at,
                provider_username=provider_username,
                provider_email=provider_email,
                provider_user_id=provider_user_id,
                scope=scope,
            )
            db.add(credential)
            logger.info(
                f"[GIT CREDENTIALS] Created {provider.value} credentials for user {user_id}"
            )

        await db.commit()
        await db.refresh(credential)
        return credential

    async def get_credential(
        self, db: AsyncSession, user_id: UUID, provider: GitProviderType
    ) -> dict[str, Any] | None:
        """
        Get decrypted credentials for a user and provider.

        Args:
            db: Database session
            user_id: User ID
            provider: Git provider type

        Returns:
            Dictionary with decrypted credentials or None if not found
        """
        result = await db.execute(
            select(GitProviderCredential).where(
                and_(
                    GitProviderCredential.user_id == user_id,
                    GitProviderCredential.provider == provider.value,
                )
            )
        )
        credential = result.scalar_one_or_none()

        if not credential:
            return None

        # Decrypt tokens
        access_token = (
            self.decrypt_token(credential.access_token) if credential.access_token else None
        )
        refresh_token = (
            self.decrypt_token(credential.refresh_token) if credential.refresh_token else None
        )

        return {
            "id": str(credential.id),
            "provider": credential.provider,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_expires_at": credential.token_expires_at,
            "provider_username": credential.provider_username,
            "provider_email": credential.provider_email,
            "provider_user_id": credential.provider_user_id,
            "scope": credential.scope,
            "created_at": credential.created_at,
            "updated_at": credential.updated_at,
        }

    async def get_access_token(
        self, db: AsyncSession, user_id: UUID, provider: GitProviderType
    ) -> str | None:
        """
        Get the decrypted OAuth access token for a user and provider.

        Args:
            db: Database session
            user_id: User ID
            provider: Git provider type

        Returns:
            Decrypted OAuth access token, or None if not found
        """
        credentials = await self.get_credential(db, user_id, provider)
        if not credentials:
            return None
        return credentials.get("access_token")

    async def get_all_credentials(
        self, db: AsyncSession, user_id: UUID
    ) -> dict[str, dict[str, Any]]:
        """
        Get all provider credentials for a user.

        Args:
            db: Database session
            user_id: User ID

        Returns:
            Dictionary mapping provider names to credential info
        """
        result = await db.execute(
            select(GitProviderCredential).where(GitProviderCredential.user_id == user_id)
        )
        credentials = result.scalars().all()

        provider_creds = {}
        for cred in credentials:
            provider_creds[cred.provider] = {
                "connected": True,
                "provider_username": cred.provider_username,
                "provider_email": cred.provider_email,
                "scope": cred.scope,
                "token_expires_at": cred.token_expires_at,
            }

        return provider_creds

    async def delete_credential(
        self, db: AsyncSession, user_id: UUID, provider: GitProviderType
    ) -> bool:
        """
        Delete credentials for a user and provider.

        Args:
            db: Database session
            user_id: User ID
            provider: Git provider type

        Returns:
            True if credentials were deleted, False if not found
        """
        result = await db.execute(
            select(GitProviderCredential).where(
                and_(
                    GitProviderCredential.user_id == user_id,
                    GitProviderCredential.provider == provider.value,
                )
            )
        )
        credential = result.scalar_one_or_none()

        if not credential:
            return False

        await db.delete(credential)
        await db.commit()
        logger.info(f"[GIT CREDENTIALS] Deleted {provider.value} credentials for user {user_id}")
        return True

    async def has_credential(
        self, db: AsyncSession, user_id: UUID, provider: GitProviderType
    ) -> bool:
        """
        Check if a user has stored credentials for a provider.

        Args:
            db: Database session
            user_id: User ID
            provider: Git provider type

        Returns:
            True if credentials exist, False otherwise
        """
        result = await db.execute(
            select(GitProviderCredential).where(
                and_(
                    GitProviderCredential.user_id == user_id,
                    GitProviderCredential.provider == provider.value,
                )
            )
        )
        credential = result.scalar_one_or_none()
        return credential is not None

    async def is_token_expired(
        self, db: AsyncSession, user_id: UUID, provider: GitProviderType, buffer_seconds: int = 300
    ) -> bool:
        """
        Check if a token is expired or will expire soon.

        Args:
            db: Database session
            user_id: User ID
            provider: Git provider type
            buffer_seconds: Consider expired if within this many seconds of expiration

        Returns:
            True if token is expired or will expire soon
        """
        credentials = await self.get_credential(db, user_id, provider)
        if not credentials or not credentials.get("token_expires_at"):
            return False  # No expiration set (like GitHub)

        expires_at = credentials["token_expires_at"]
        from datetime import timedelta

        return datetime.utcnow() + timedelta(seconds=buffer_seconds) >= expires_at

    async def update_tokens(
        self,
        db: AsyncSession,
        user_id: UUID,
        provider: GitProviderType,
        access_token: str,
        refresh_token: str | None = None,
        expires_at: datetime | None = None,
    ) -> bool:
        """
        Update tokens for an existing credential (used for token refresh).

        Args:
            db: Database session
            user_id: User ID
            provider: Git provider type
            access_token: New access token
            refresh_token: New refresh token (optional)
            expires_at: New expiration time

        Returns:
            True if updated, False if credential not found
        """
        result = await db.execute(
            select(GitProviderCredential).where(
                and_(
                    GitProviderCredential.user_id == user_id,
                    GitProviderCredential.provider == provider.value,
                )
            )
        )
        credential = result.scalar_one_or_none()

        if not credential:
            return False

        credential.access_token = self.encrypt_token(access_token)
        if refresh_token:
            credential.refresh_token = self.encrypt_token(refresh_token)
        if expires_at:
            credential.token_expires_at = expires_at
        credential.updated_at = datetime.utcnow()

        await db.commit()
        logger.info(f"[GIT CREDENTIALS] Refreshed {provider.value} tokens for user {user_id}")
        return True


# Global instance
_git_provider_credential_service: GitProviderCredentialService | None = None


def get_git_provider_credential_service() -> GitProviderCredentialService:
    """Get or create the global credential service instance."""
    global _git_provider_credential_service
    if _git_provider_credential_service is None:
        _git_provider_credential_service = GitProviderCredentialService()
    return _git_provider_credential_service
