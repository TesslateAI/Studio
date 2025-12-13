"""
OAuth providers configuration for fastapi-users.

Supports:
- Google OAuth
- GitHub OAuth
- Graceful degradation if credentials not configured
"""
from typing import Any, List, Optional, cast
from httpx_oauth.clients.google import GoogleOAuth2
from httpx_oauth.clients.github import GitHubOAuth2
from httpx_oauth.exceptions import GetIdEmailError, GetProfileError

from .config import get_settings

settings = get_settings()


# ============================================================================
# Custom Google OAuth2 Client
# ============================================================================

class CustomGoogleOAuth2(GoogleOAuth2):
    """
    Custom Google OAuth2 client that uses the OpenID Connect userinfo endpoint.

    The default httpx_oauth GoogleOAuth2 client uses the People API which requires
    different scopes. This custom implementation uses the standard OpenID Connect
    endpoint that works with openid, email, and profile scopes.
    """

    async def get_id_email(self, token: str) -> tuple[str, Optional[str]]:
        """
        Get user ID and email using OpenID Connect userinfo endpoint.

        Uses: https://openidconnect.googleapis.com/v1/userinfo
        Works with scopes: openid, email, profile
        """
        try:
            async with self.get_httpx_client() as client:
                response = await client.get(
                    "https://openidconnect.googleapis.com/v1/userinfo",
                    headers={**self.request_headers, "Authorization": f"Bearer {token}"},
                )

                if response.status_code >= 400:
                    raise GetProfileError(response=response)

                profile = cast(dict[str, Any], response.json())
        except GetProfileError as e:
            raise GetIdEmailError(response=e.response) from e

        # OpenID Connect userinfo returns 'sub' for user ID and 'email' directly
        user_id = profile.get("sub")
        user_email = profile.get("email")

        return user_id, user_email


# ============================================================================
# OAuth Clients Configuration
# ============================================================================

def get_google_oauth_client() -> Optional[CustomGoogleOAuth2]:
    """
    Get Google OAuth client if configured, otherwise return None.

    Graceful degradation: If Google OAuth credentials are not set,
    the Google login option simply won't be available.

    Uses CustomGoogleOAuth2 which uses OpenID Connect userinfo endpoint
    instead of the People API.
    """
    if not settings.google_client_id or not settings.google_client_secret:
        print("⚠️  Google OAuth not configured (missing CLIENT_ID or CLIENT_SECRET)")
        return None

    try:
        return CustomGoogleOAuth2(
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            scopes=["openid", "email", "profile"],
        )
    except Exception as e:
        print(f"❌ Failed to initialize Google OAuth client: {e}")
        return None


def get_github_oauth_client() -> Optional[GitHubOAuth2]:
    """
    Get GitHub OAuth client if configured, otherwise return None.

    Graceful degradation: If GitHub OAuth credentials are not set,
    the GitHub login option simply won't be available.
    """
    if not settings.github_client_id or not settings.github_client_secret:
        print("⚠️  GitHub OAuth not configured (missing CLIENT_ID or CLIENT_SECRET)")
        return None

    try:
        return GitHubOAuth2(
            client_id=settings.github_client_id,
            client_secret=settings.github_client_secret,
            scopes=["user:email", "read:user"],  # Scopes for reading user profile
        )
    except Exception as e:
        print(f"❌ Failed to initialize GitHub OAuth client: {e}")
        return None


# ============================================================================
# OAuth Provider Registry
# ============================================================================

def get_available_oauth_clients() -> dict:
    """
    Get all available and configured OAuth clients.

    Returns a dict with provider names as keys and client instances as values.
    Only includes providers that are properly configured.
    """
    clients = {}

    # Try to add Google OAuth
    google_client = get_google_oauth_client()
    if google_client:
        clients["google"] = google_client
        print("✅ Google OAuth enabled")

    # Try to add GitHub OAuth
    github_client = get_github_oauth_client()
    if github_client:
        clients["github"] = github_client
        print("✅ GitHub OAuth enabled")

    if not clients:
        print("⚠️  No OAuth providers configured. Only username/password authentication available.")

    return clients


def get_oauth_client_names() -> List[str]:
    """Get list of available OAuth provider names."""
    return list(get_available_oauth_clients().keys())


# Initialize OAuth clients on module load
OAUTH_CLIENTS = get_available_oauth_clients()


# ============================================================================
# OAuth Configuration Helpers
# ============================================================================

def is_google_oauth_enabled() -> bool:
    """Check if Google OAuth is enabled and configured."""
    return "google" in OAUTH_CLIENTS


def is_github_oauth_enabled() -> bool:
    """Check if GitHub OAuth is enabled and configured."""
    return "github" in OAUTH_CLIENTS


def get_oauth_redirect_url(provider: str) -> Optional[str]:
    """
    Get the redirect URL for the given OAuth provider.

    Args:
        provider: OAuth provider name (google, github, etc.)

    Returns:
        Redirect URL or None if provider not configured
    """
    if provider == "google":
        return settings.google_oauth_redirect_uri if settings.google_oauth_redirect_uri else None
    elif provider == "github":
        return settings.github_oauth_redirect_uri if settings.github_oauth_redirect_uri else None
    return None
