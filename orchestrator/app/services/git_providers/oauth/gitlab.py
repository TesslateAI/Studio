"""
GitLab OAuth Service.

Handles OAuth2 authentication flow with GitLab.
Supports both gitlab.com and self-hosted GitLab instances.
"""

import logging
import secrets
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from ....config import get_settings

logger = logging.getLogger(__name__)


class GitLabOAuthService:
    """Handles GitLab OAuth2 authentication flow."""

    DEFAULT_SCOPES = "read_user read_repository read_api"

    def __init__(self, base_url: str | None = None):
        """
        Initialize GitLab OAuth service.

        Args:
            base_url: Custom GitLab instance URL (default: gitlab.com)
        """
        self.settings = get_settings()
        self.client_id = self.settings.gitlab_client_id
        self.client_secret = self.settings.gitlab_client_secret
        self.redirect_uri = self.settings.gitlab_oauth_redirect_uri

        # Support self-hosted GitLab
        self.base_url = (
            base_url or self.settings.gitlab_api_base_url or "https://gitlab.com"
        ).rstrip("/")

        self.oauth_authorize_url = f"{self.base_url}/oauth/authorize"
        self.oauth_token_url = f"{self.base_url}/oauth/token"
        self.api_base_url = f"{self.base_url}/api/v4"

    @property
    def is_configured(self) -> bool:
        """Check if GitLab OAuth is properly configured."""
        return bool(self.client_id and self.client_secret)

    def generate_state(self) -> str:
        """Generate a secure random state parameter for CSRF protection."""
        return secrets.token_urlsafe(32)

    def get_authorization_url(self, state: str, scope: str = None) -> str:
        """
        Generate GitLab OAuth authorization URL.

        Args:
            state: CSRF protection state parameter
            scope: OAuth scopes to request

        Returns:
            Full authorization URL to redirect user to
        """
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "state": state,
            "scope": scope or self.DEFAULT_SCOPES,
        }

        return f"{self.oauth_authorize_url}?{urlencode(params)}"

    async def exchange_code_for_token(self, code: str) -> dict[str, Any]:
        """
        Exchange authorization code for access token.

        Args:
            code: Authorization code from GitLab callback

        Returns:
            Dictionary containing access_token, refresh_token, token_type, expires_at

        Raises:
            ValueError: If token exchange fails
        """
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.oauth_token_url,
                    data={
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "code": code,
                        "grant_type": "authorization_code",
                        "redirect_uri": self.redirect_uri,
                    },
                    headers={"Accept": "application/json"},
                    timeout=30.0,
                )

                response.raise_for_status()
                token_data = response.json()

                if "error" in token_data:
                    error_msg = token_data.get("error_description", token_data["error"])
                    logger.error(f"[GITLAB OAuth] Error: {error_msg}")
                    raise ValueError(f"OAuth error: {error_msg}")

                # GitLab provides expires_in (seconds)
                expires_in = token_data.get("expires_in", 7200)  # Default 2 hours
                token_data["expires_at"] = datetime.utcnow() + timedelta(seconds=expires_in)

                return token_data

            except httpx.HTTPStatusError as e:
                logger.error(f"[GITLAB OAuth] HTTP error during token exchange: {e}")
                raise
            except Exception as e:
                logger.error(f"[GITLAB OAuth] Failed to exchange code for token: {e}")
                raise

    async def refresh_token(self, refresh_token: str) -> dict[str, Any]:
        """
        Refresh an expired access token.

        GitLab supports refresh tokens, unlike GitHub.

        Args:
            refresh_token: The refresh token

        Returns:
            New token data with access_token, refresh_token, expires_at
        """
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.oauth_token_url,
                    data={
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "refresh_token": refresh_token,
                        "grant_type": "refresh_token",
                    },
                    headers={"Accept": "application/json"},
                    timeout=30.0,
                )

                response.raise_for_status()
                token_data = response.json()

                if "error" in token_data:
                    error_msg = token_data.get("error_description", token_data["error"])
                    raise ValueError(f"Token refresh error: {error_msg}")

                expires_in = token_data.get("expires_in", 7200)
                token_data["expires_at"] = datetime.utcnow() + timedelta(seconds=expires_in)

                return token_data

            except Exception as e:
                logger.error(f"[GITLAB OAuth] Failed to refresh token: {e}")
                raise

    async def get_user_info(self, access_token: str) -> dict[str, Any]:
        """
        Get GitLab user information using access token.

        Args:
            access_token: GitLab OAuth access token

        Returns:
            Dictionary containing user information
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.api_base_url}/user",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()

    async def get_user_emails(self, access_token: str) -> list:
        """
        Get user's email addresses from GitLab.

        Args:
            access_token: GitLab OAuth access token

        Returns:
            List of email dictionaries
        """
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"{self.api_base_url}/user/emails",
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=30.0,
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError:
                # Fallback to user info email
                try:
                    user_info = await self.get_user_info(access_token)
                    if user_info.get("email"):
                        return [{"email": user_info["email"], "primary": True}]
                except Exception:
                    pass
                return []

    async def revoke_token(self, access_token: str) -> bool:
        """
        Revoke a GitLab access token.

        Args:
            access_token: Token to revoke

        Returns:
            True if successful
        """
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.base_url}/oauth/revoke",
                    data={
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "token": access_token,
                    },
                    timeout=30.0,
                )
                return response.status_code == 200
            except Exception as e:
                logger.error(f"[GITLAB OAuth] Failed to revoke token: {e}")
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
_gitlab_oauth_service: GitLabOAuthService | None = None


def get_gitlab_oauth_service() -> GitLabOAuthService:
    """Get or create GitLab OAuth service instance."""
    global _gitlab_oauth_service
    if _gitlab_oauth_service is None:
        _gitlab_oauth_service = GitLabOAuthService()
    return _gitlab_oauth_service
