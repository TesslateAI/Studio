"""
Git URL utilities — sanitization and runtime token injection.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse, urlunparse
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Canonical SaaS hostnames only — self-hosted instances (e.g. gitlab.corp.com)
# can't be enumerated here; callers that need self-hosted support must pass
# the provider type explicitly instead of relying on URL inference.
_HOST_TO_PROVIDER: dict[str, str] = {
    "github.com": "github",
    "gitlab.com": "gitlab",
    "bitbucket.org": "bitbucket",
}


def strip_git_credentials(url: str | None) -> str | None:
    """Return a token-free copy of a git clone URL.

    Removes userinfo (e.g. ``token@`` or ``oauth2:token@``) from the netloc so
    the URL is safe to store, log, or return via API.  Non-HTTP(S) URLs and
    ``None`` are returned unchanged.
    """
    if not url:
        return url
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return url
        # parsed.hostname strips userinfo and port; parsed.netloc would keep them.
        clean = parsed._replace(netloc=parsed.hostname or "")
        return urlunparse(clean)
    except Exception:
        return url


def infer_provider_from_url(url: str) -> str | None:
    """Return the provider name for a git clone URL, or None if unrecognised."""
    try:
        host = urlparse(url).hostname or ""
        # Support self-hosted GitLab (any non-github/bitbucket host defaults to gitlab)
        return _HOST_TO_PROVIDER.get(host)
    except Exception:
        return None


async def build_authenticated_git_url(
    clean_url: str,
    user_id: UUID,
    db: AsyncSession,
) -> str:
    """Return an authenticated git clone URL for *clean_url* by looking up the
    user's stored OAuth token at runtime.

    Falls back to *clean_url* unchanged if no credentials are found (public
    repos, misconfigured users, etc.) so callers never receive ``None``.
    """
    # Lazy imports: these modules import url_utils themselves, so top-level
    # imports here would create a circular dependency at module load time.
    from .base import GitProviderType
    from .credential_service import get_git_provider_credential_service
    from .manager import get_git_provider_manager

    provider_name = infer_provider_from_url(clean_url)
    if not provider_name:
        return clean_url

    try:
        provider_type = GitProviderType(provider_name)
        credential_service = get_git_provider_credential_service()
        access_token = await credential_service.get_access_token(db, user_id, provider_type)
        if not access_token:
            return clean_url

        provider_manager = get_git_provider_manager()
        provider_class = provider_manager.get_provider_class(provider_type)

        # parse_repo_url extracts owner/repo from the clean URL
        repo_info = provider_class.parse_repo_url(clean_url)
        if not repo_info:
            return clean_url

        return provider_class.format_clone_url(repo_info["owner"], repo_info["repo"], access_token)
    except Exception:
        # Intentionally broad — a broken credential lookup must never block a
        # clone attempt; public repos and misconfigured tokens both fall through.
        logger.debug("Failed to build authenticated git URL for %s, using clean URL", clean_url)
        return clean_url
