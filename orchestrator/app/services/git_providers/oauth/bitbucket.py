"""
Bitbucket OAuth Service.

Handles OAuth2 authentication flow with Bitbucket Cloud.
"""
import secrets
import httpx
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from urllib.parse import urlencode
import base64
import logging

from ....config import get_settings

logger = logging.getLogger(__name__)


class BitbucketOAuthService:
    """Handles Bitbucket OAuth2 authentication flow."""

    OAUTH_AUTHORIZE_URL = "https://bitbucket.org/site/oauth2/authorize"
    OAUTH_TOKEN_URL = "https://bitbucket.org/site/oauth2/access_token"
    API_BASE_URL = "https://api.bitbucket.org/2.0"
    DEFAULT_SCOPES = "repository account"

    def __init__(self):
        self.settings = get_settings()
        self.client_id = self.settings.bitbucket_client_id
        self.client_secret = self.settings.bitbucket_client_secret
        self.redirect_uri = self.settings.bitbucket_oauth_redirect_uri

    @property
    def is_configured(self) -> bool:
        """Check if Bitbucket OAuth is properly configured."""
        return bool(self.client_id and self.client_secret)

    def generate_state(self) -> str:
        """Generate a secure random state parameter for CSRF protection."""
        return secrets.token_urlsafe(32)

    def get_authorization_url(self, state: str, scope: str = None) -> str:
        """
        Generate Bitbucket OAuth authorization URL.

        Args:
            state: CSRF protection state parameter
            scope: OAuth scopes to request (note: Bitbucket doesn't use scope in URL)

        Returns:
            Full authorization URL to redirect user to
        """
        # Note: Bitbucket OAuth2 doesn't use scope in the authorization URL
        # Scopes are configured in the OAuth consumer settings on Bitbucket
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "state": state
        }

        # Add redirect_uri if configured
        if self.redirect_uri:
            params["redirect_uri"] = self.redirect_uri

        return f"{self.OAUTH_AUTHORIZE_URL}?{urlencode(params)}"

    def _get_basic_auth_header(self) -> str:
        """Generate Basic auth header for Bitbucket token requests."""
        credentials = f"{self.client_id}:{self.client_secret}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return f"Basic {encoded}"

    async def exchange_code_for_token(self, code: str) -> Dict[str, Any]:
        """
        Exchange authorization code for access token.

        Args:
            code: Authorization code from Bitbucket callback

        Returns:
            Dictionary containing access_token, refresh_token, token_type, expires_at

        Raises:
            ValueError: If token exchange fails
        """
        async with httpx.AsyncClient() as client:
            try:
                # Bitbucket requires Basic auth for token exchange
                response = await client.post(
                    self.OAUTH_TOKEN_URL,
                    data={
                        "grant_type": "authorization_code",
                        "code": code
                    },
                    headers={
                        "Authorization": self._get_basic_auth_header(),
                        "Content-Type": "application/x-www-form-urlencoded"
                    },
                    timeout=30.0
                )

                response.raise_for_status()
                token_data = response.json()

                if "error" in token_data:
                    error_msg = token_data.get("error_description", token_data["error"])
                    logger.error(f"[BITBUCKET OAuth] Error: {error_msg}")
                    raise ValueError(f"OAuth error: {error_msg}")

                # Bitbucket provides expires_in (seconds), typically 2 hours
                expires_in = token_data.get("expires_in", 7200)
                token_data["expires_at"] = datetime.utcnow() + timedelta(seconds=expires_in)

                return token_data

            except httpx.HTTPStatusError as e:
                logger.error(f"[BITBUCKET OAuth] HTTP error during token exchange: {e}")
                raise
            except Exception as e:
                logger.error(f"[BITBUCKET OAuth] Failed to exchange code for token: {e}")
                raise

    async def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        """
        Refresh an expired access token.

        Bitbucket supports refresh tokens.

        Args:
            refresh_token: The refresh token

        Returns:
            New token data with access_token, refresh_token, expires_at
        """
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.OAUTH_TOKEN_URL,
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token
                    },
                    headers={
                        "Authorization": self._get_basic_auth_header(),
                        "Content-Type": "application/x-www-form-urlencoded"
                    },
                    timeout=30.0
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
                logger.error(f"[BITBUCKET OAuth] Failed to refresh token: {e}")
                raise

    async def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """
        Get Bitbucket user information using access token.

        Args:
            access_token: Bitbucket OAuth access token

        Returns:
            Dictionary containing user information
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.API_BASE_URL}/user",
                headers={
                    "Authorization": f"Bearer {access_token}"
                },
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()

    async def get_user_emails(self, access_token: str) -> list:
        """
        Get user's email addresses from Bitbucket.

        Args:
            access_token: Bitbucket OAuth access token

        Returns:
            List of email dictionaries
        """
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"{self.API_BASE_URL}/user/emails",
                    headers={
                        "Authorization": f"Bearer {access_token}"
                    },
                    timeout=30.0
                )
                response.raise_for_status()
                data = response.json()
                return data.get("values", [])
            except httpx.HTTPStatusError:
                return []

    async def revoke_token(self, access_token: str) -> bool:
        """
        Revoke a Bitbucket access token.

        Note: Bitbucket doesn't have a standard token revocation endpoint.
        Users need to revoke access from their Bitbucket settings.

        Args:
            access_token: Token to revoke

        Returns:
            True (always, as we can't actually revoke)
        """
        # Bitbucket doesn't support programmatic token revocation
        # Users must revoke access from their Bitbucket account settings
        logger.warning("[BITBUCKET OAuth] Token revocation not supported. User must revoke manually.")
        return True

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
_bitbucket_oauth_service: Optional[BitbucketOAuthService] = None


def get_bitbucket_oauth_service() -> BitbucketOAuthService:
    """Get or create Bitbucket OAuth service instance."""
    global _bitbucket_oauth_service
    if _bitbucket_oauth_service is None:
        _bitbucket_oauth_service = BitbucketOAuthService()
    return _bitbucket_oauth_service
