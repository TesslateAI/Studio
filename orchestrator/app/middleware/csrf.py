"""
CSRF (Cross-Site Request Forgery) protection middleware.

This middleware provides protection against CSRF attacks for cookie-based authentication.
It validates CSRF tokens on all state-changing operations (POST, PUT, DELETE, PATCH).

Token Flow:
1. GET /api/auth/csrf → Returns CSRF token in response + sets cookie
2. Client includes token in X-CSRF-Token header for POST/PUT/DELETE/PATCH
3. Middleware validates token matches cookie

Exempt Routes:
- Public auth endpoints (login, register, OAuth callbacks)
- Bearer token authenticated requests (CSRF not needed for stateless auth)
"""
import secrets
from typing import Callable

from fastapi import Request, Response, HTTPException, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from ..config import get_settings

settings = get_settings()

# Use a separate secret for CSRF or fall back to main secret
CSRF_SECRET = settings.csrf_secret_key or settings.secret_key
CSRF_TOKEN_MAX_AGE = settings.csrf_token_max_age  # From environment variable

# Cookie and header names
CSRF_COOKIE_NAME = "tesslate_csrf_token"
CSRF_HEADER_NAME = "x-csrf-token"

# Serializer for signing/verifying CSRF tokens
csrf_serializer = URLSafeTimedSerializer(CSRF_SECRET, salt="csrf")


# ============================================================================
# CSRF Token Functions
# ============================================================================

def generate_csrf_token() -> str:
    """
    Generate a new CSRF token.

    Returns a cryptographically secure signed token.
    """
    random_bytes = secrets.token_hex(32)
    return csrf_serializer.dumps(random_bytes)


def validate_csrf_token(token: str, max_age: int = CSRF_TOKEN_MAX_AGE) -> bool:
    """
    Validate a CSRF token.

    Args:
        token: The CSRF token to validate
        max_age: Maximum age of the token in seconds

    Returns:
        True if valid, False otherwise
    """
    try:
        csrf_serializer.loads(token, max_age=max_age)
        return True
    except (BadSignature, SignatureExpired):
        return False


# ============================================================================
# CSRF Middleware
# ============================================================================

class CSRFProtectionMiddleware(BaseHTTPMiddleware):
    """
    Middleware to protect against CSRF attacks.

    - Validates CSRF tokens on POST/PUT/DELETE/PATCH requests
    - Exempts public endpoints (auth, OAuth callbacks)
    - Exempts Bearer token authentication (stateless, no CSRF risk)
    """

    # Routes that don't require CSRF protection
    EXEMPT_PATHS = {
        "/api/auth/register",
        "/api/auth/login",
        "/api/auth/jwt/login",
        "/api/auth/cookie/login",
        "/api/auth/refresh",
        "/api/auth/csrf",  # CSRF token endpoint itself
        "/api/auth/google/callback",
        "/api/auth/github/callback",
        "/api/track-landing",  # Referral tracking endpoint
        "/api/webhooks/stripe",  # Stripe webhooks need to bypass CSRF
        "/docs",
        "/redoc",
        "/openapi.json",
    }

    # Methods that require CSRF protection
    PROTECTED_METHODS = {"POST", "PUT", "DELETE", "PATCH"}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Validate CSRF token on state-changing requests.
        """
        # Skip CSRF check for safe methods (GET, HEAD, OPTIONS)
        if request.method not in self.PROTECTED_METHODS:
            return await call_next(request)

        # Skip CSRF check for exempt paths
        path = request.url.path
        if any(path.startswith(exempt) for exempt in self.EXEMPT_PATHS):
            return await call_next(request)

        # Skip CSRF check if using Bearer token authentication
        # (Bearer token is stateless, not vulnerable to CSRF)
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            return await call_next(request)

        # Extract CSRF token from cookie
        csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)

        # Extract CSRF token from header
        csrf_header = request.headers.get(CSRF_HEADER_NAME)

        # Validate presence of both tokens
        if not csrf_cookie or not csrf_header:
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "detail": "CSRF token missing. Please include CSRF token in cookie and header."
                },
            )

        # Validate tokens match
        if csrf_cookie != csrf_header:
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"detail": "CSRF token mismatch. Please refresh the page and try again."},
            )

        # Validate token signature and expiration
        if not validate_csrf_token(csrf_cookie):
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"detail": "CSRF token invalid or expired. Please refresh the page and try again."},
            )

        # CSRF validation passed, proceed with request
        response = await call_next(request)
        return response


# ============================================================================
# CSRF Token Endpoint
# ============================================================================

def get_csrf_token_response() -> JSONResponse:
    """
    Generate and return a new CSRF token.

    Returns the token in both:
    1. JSON response body
    2. HTTP-only cookie

    This endpoint should be called by the frontend on page load.
    """
    token = generate_csrf_token()

    response = JSONResponse(
        content={"csrf_token": token},
        status_code=200,
    )

    # Set CSRF token in cookie
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        max_age=CSRF_TOKEN_MAX_AGE,
        httponly=True,  # Prevent JavaScript access
        secure=settings.cookie_secure,  # HTTPS only in production
        samesite=settings.cookie_samesite,
    )

    return response
