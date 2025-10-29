"""
GitHub OAuth Service
Handles OAuth2 authentication flow with GitHub
"""
import secrets
import httpx
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from urllib.parse import urlencode
import logging
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from .credential_manager import get_credential_manager

logger = logging.getLogger(__name__)


class GitHubOAuthService:
    """Handles GitHub OAuth2 authentication flow."""

    GITHUB_OAUTH_URL = "https://github.com/login/oauth/authorize"
    GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
    GITHUB_API_BASE = "https://api.github.com"

    def __init__(self):
        self.settings = get_settings()
        self.client_id = self.settings.github_client_id
        self.client_secret = self.settings.github_client_secret
        self.redirect_uri = self.settings.github_oauth_redirect_uri

    def generate_state(self) -> str:
        """Generate a secure random state parameter for CSRF protection."""
        return secrets.token_urlsafe(32)

    def get_authorization_url(self, state: str, scope: str = "repo user:email") -> str:
        """
        Generate GitHub OAuth authorization URL.

        Args:
            state: CSRF protection state parameter
            scope: OAuth scopes to request (default: "repo user:email")

        Returns:
            Full authorization URL to redirect user to
        """
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": scope,
            "state": state,
            "allow_signup": "true"
        }

        return f"{self.GITHUB_OAUTH_URL}?{urlencode(params)}"

    async def exchange_code_for_token(self, code: str, state: str) -> Dict[str, Any]:
        """
        Exchange authorization code for access token.

        Args:
            code: Authorization code from GitHub callback
            state: State parameter for validation

        Returns:
            Dictionary containing access_token, token_type, and scope

        Raises:
            HTTPException: If token exchange fails
        """
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.GITHUB_TOKEN_URL,
                    data={
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "code": code,
                        "redirect_uri": self.redirect_uri
                    },
                    headers={
                        "Accept": "application/json"
                    }
                )

                response.raise_for_status()
                token_data = response.json()

                if "error" in token_data:
                    logger.error(f"GitHub OAuth error: {token_data.get('error_description', token_data['error'])}")
                    raise ValueError(f"OAuth error: {token_data.get('error_description', 'Unknown error')}")

                # GitHub doesn't provide expires_in by default, but we'll set a reasonable expiry
                # Access tokens don't expire unless revoked, but we'll set a long expiry for safety
                token_data["expires_at"] = datetime.utcnow() + timedelta(days=365)

                return token_data

            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error during token exchange: {e}")
                raise
            except Exception as e:
                logger.error(f"Failed to exchange code for token: {e}")
                raise

    async def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """
        Get GitHub user information using access token.

        Args:
            access_token: GitHub OAuth access token

        Returns:
            Dictionary containing user information
        """
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"{self.GITHUB_API_BASE}/user",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/vnd.github.v3+json"
                    }
                )

                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as e:
                logger.error(f"Failed to get user info: {e}")
                raise

    async def get_user_emails(self, access_token: str) -> list:
        """
        Get user's email addresses from GitHub.

        Args:
            access_token: GitHub OAuth access token

        Returns:
            List of email addresses
        """
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"{self.GITHUB_API_BASE}/user/emails",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/vnd.github.v3+json"
                    }
                )

                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as e:
                logger.error(f"Failed to get user emails: {e}")
                if e.response.status_code == 404:
                    return []  # User might not have granted email scope
                raise

    async def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        """
        Refresh an expired access token.

        Note: GitHub OAuth tokens don't expire by default, but this method
        is here for future compatibility if GitHub adds refresh token support.

        Args:
            refresh_token: Refresh token

        Returns:
            New token data
        """
        # GitHub doesn't currently support refresh tokens for OAuth Apps
        # This is a placeholder for future compatibility
        logger.warning("GitHub OAuth doesn't support refresh tokens. Token will need to be re-authorized.")
        raise NotImplementedError("GitHub OAuth doesn't support refresh tokens")

    async def revoke_token(self, access_token: str) -> bool:
        """
        Revoke a GitHub access token.

        Args:
            access_token: Token to revoke

        Returns:
            True if successful
        """
        async with httpx.AsyncClient() as client:
            try:
                # GitHub requires Basic auth with client credentials for token revocation
                response = await client.delete(
                    f"https://api.github.com/applications/{self.client_id}/token",
                    auth=(self.client_id, self.client_secret),
                    json={"access_token": access_token}
                )

                return response.status_code == 204

            except Exception as e:
                logger.error(f"Failed to revoke token: {e}")
                return False

    def validate_state(self, state: str, stored_state: str) -> bool:
        """
        Validate OAuth state parameter for CSRF protection.

        Args:
            state: State parameter from callback
            stored_state: State parameter stored in session

        Returns:
            True if states match
        """
        return secrets.compare_digest(state, stored_state)


# Singleton instance
_oauth_service: Optional[GitHubOAuthService] = None


def get_github_oauth_service() -> GitHubOAuthService:
    """Get or create GitHub OAuth service instance."""
    global _oauth_service
    if _oauth_service is None:
        _oauth_service = GitHubOAuthService()
    return _oauth_service