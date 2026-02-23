"""
JWT-based OAuth state tokens for non-login OAuth flows.

Replaces in-memory dict-based state storage with signed JWTs that:
- Survive server restarts (stateless)
- Work across K8s pods (no shared memory needed)
- Self-expire (10 min TTL)
- Are scoped by audience to prevent cross-flow token reuse

Used by: github.py (repo connect), git_providers.py, deployment_oauth.py
NOT used by: login OAuth (uses fastapi-users STATE_TOKEN_AUDIENCE)
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from ..config import get_settings

logger = logging.getLogger(__name__)

# Audience constants — prevent tokens from one flow being used in another
REPO_CONNECT_AUDIENCE = "tesslate:repo_connect"
DEPLOYMENT_OAUTH_AUDIENCE = "tesslate:deployment_oauth"

STATE_TOKEN_TTL_MINUTES = 10


def generate_oauth_state(
    user_id: str,
    flow: str,
    audience: str,
    extra: dict[str, Any] | None = None,
) -> str:
    """
    Generate a signed JWT state token for OAuth CSRF protection.

    Args:
        user_id: The user initiating the OAuth flow (str(UUID)).
        flow: Identifier for the flow (e.g. "github", "gitlab", "vercel").
        audience: JWT audience constant (REPO_CONNECT_AUDIENCE, etc.).
        extra: Additional claims to embed (e.g. scope, project_id).

    Returns:
        Encoded JWT string.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)

    payload: dict[str, Any] = {
        "sub": str(user_id),
        "flow": flow,
        "aud": audience,
        "iat": now,
        "exp": now + timedelta(minutes=STATE_TOKEN_TTL_MINUTES),
    }

    if extra:
        payload["data"] = extra

    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_oauth_state(
    token: str,
    audience: str,
) -> dict[str, Any] | None:
    """
    Decode and validate a JWT state token.

    Args:
        token: The JWT string from the OAuth callback.
        audience: Expected audience (must match the one used to generate).

    Returns:
        Decoded payload dict on success, None on any failure.
    """
    settings = get_settings()

    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=["HS256"],
            audience=audience,
        )
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("OAuth state token expired")
        return None
    except jwt.InvalidAudienceError:
        # Expected when login callback tries repo_connect audience on a login token
        logger.debug("OAuth state token audience mismatch (expected for cross-flow check)")
        return None
    except jwt.DecodeError:
        logger.debug("OAuth state token decode failed (not a valid JWT for this audience)")
        return None
    except Exception:
        logger.warning("OAuth state token validation failed", exc_info=True)
        return None
