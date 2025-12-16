"""
GitHub OAuth Service.

Handles OAuth2 authentication flow with GitHub.
Refactored from the original github_oauth.py.
"""
import secrets
import httpx
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from urllib.parse import urlencode
import logging

from ....config import get_settings

logger = logging.getLogger(__name__)


class GitHubOAuthService:
    """Handles GitHub OAuth2 authentication flow."""

    OAUTH_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
    OAUTH_TOKEN_URL = "https://github.com/login/oauth/access_token"
    API_BASE_URL = "https://api.github.com"
    DEFAULT_SCOPES = "repo user:email"

    def __init__(self):
        self.settings = get_settings()
        self.client_id = self.settings.github_client_id
        self.client_secret = self.settings.github_client_secret
        self.redirect_uri = self.settings.github_oauth_redirect_uri

    @property
    def is_configured(self) -> bool:
        """Check if GitHub OAuth is properly configured."""
        return bool(self.client_id and self.client_secret)

    def generate_state(self) -> str:
        """Generate a secure random state parameter for CSRF protection."""
        return secrets.token_urlsafe(32)

    def get_authorization_url(self, state: str, scope: str = None) -> str:
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
            "scope": scope or self.DEFAULT_SCOPES,
            "state": state,
            "allow_signup": "true"
        }

        return f"{self.OAUTH_AUTHORIZE_URL}?{urlencode(params)}"

    async def exchange_code_for_token(self, code: str) -> Dict[str, Any]:
        """
        Exchange authorization code for access token.

        Args:
            code: Authorization code from GitHub callback

        Returns:
            Dictionary containing access_token, token_type, scope, and expires_at

        Raises:
            ValueError: If token exchange fails
        """
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.OAUTH_TOKEN_URL,
                    data={
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "code": code,
                        "redirect_uri": self.redirect_uri
                    },
                    headers={
                        "Accept": "application/json"
                    },
                    timeout=30.0
                )

                response.raise_for_status()
                token_data = response.json()

                if "error" in token_data:
                    error_msg = token_data.get("error_description", token_data["error"])
                    logger.error(f"[GITHUB OAuth] Error: {error_msg}")
                    raise ValueError(f"OAuth error: {error_msg}")

                # GitHub doesn't provide expires_in by default
                # Access tokens don't expire unless revoked
                token_data["expires_at"] = datetime.utcnow() + timedelta(days=365)
                token_data["refresh_token"] = None  # GitHub OAuth Apps don't have refresh tokens

                return token_data

            except httpx.HTTPStatusError as e:
                logger.error(f"[GITHUB OAuth] HTTP error during token exchange: {e}")
                raise
            except Exception as e:
                logger.error(f"[GITHUB OAuth] Failed to exchange code for token: {e}")
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
            response = await client.get(
                f"{self.API_BASE_URL}/user",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github.v3+json"
                },
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()

    async def get_user_emails(self, access_token: str) -> list:
        """
        Get user's email addresses from GitHub.

        Args:
            access_token: GitHub OAuth access token

        Returns:
            List of email dictionaries
        """
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"{self.API_BASE_URL}/user/emails",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/vnd.github.v3+json"
                    },
                    timeout=30.0
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    return []  # User might not have granted email scope
                raise

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
                response = await client.delete(
                    f"https://api.github.com/applications/{self.client_id}/token",
                    auth=(self.client_id, self.client_secret),
                    json={"access_token": access_token},
                    timeout=30.0
                )
                return response.status_code == 204
            except Exception as e:
                logger.error(f"[GITHUB OAuth] Failed to revoke token: {e}")
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
_github_oauth_service: Optional[GitHubOAuthService] = None


def get_github_oauth_service() -> GitHubOAuthService:
    """Get or create GitHub OAuth service instance."""
    global _github_oauth_service
    if _github_oauth_service is None:
        _github_oauth_service = GitHubOAuthService()
    return _github_oauth_service
