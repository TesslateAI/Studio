"""
Magic-link (passwordless) login endpoints.

Three endpoints:
  POST /api/auth/magic-link/request   — email a link + 6-digit code
  POST /api/auth/magic-link/consume   — consume the clicked link, return JWT
  POST /api/auth/magic-link/verify    — verify the typed 6-digit code

Flow:
  1. User enters email, we create one EmailVerificationCode row (purpose="magic_login")
     and email both a clickable link and the code.
  2. Whichever path the user takes first consumes the row and invalidates the other.
  3. On success we issue the standard access+refresh token pair.

Security:
  - /request ALWAYS returns 200 {"ok": true} to prevent email enumeration
  - /request is rate-limited per known-user: 5 requests per 10 minutes
  - OAuth-only users (no password) can use this flow — treat magic-link as equivalent
    to password+2FA (it proves email possession)
  - Magic link bypasses 2FA by design (possession of email == a full factor)
  - Gated by the magic_link_login feature flag
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..compliance import enforce_email_compliance
from ..database import get_db
from ..models_auth import User
from ..schemas_auth import LoginResponse, MagicLinkRequest, MagicLinkVerifyRequest
from ..services.auth_tokens import issue_token_pair
from ..services.email_service import get_email_service
from ..services.feature_flags import get_feature_flags
from ..services.magic_link_service import (
    build_magic_link_url,
    check_rate_limit,
    consume_link_token,
    create_magic_link,
    verify_code,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _ensure_enabled() -> None:
    """Guard every endpoint with the feature flag. Raise 404 if disabled."""
    if not get_feature_flags().enabled("magic_link_login"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not Found",
        )


@router.post("/request")
async def request_magic_link(
    body: MagicLinkRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Send a sign-in email to the requested address.

    Always returns 200 {"ok": true} regardless of whether the email exists or
    whether the send succeeded. This prevents enumeration and avoids leaking
    rate-limit state to attackers.
    """
    _ensure_enabled()

    # Normalize + sanity-check (reject blocked domains if compliance is configured)
    email = body.email.strip().lower()
    try:
        enforce_email_compliance(email)
    except HTTPException:
        # Still 200 — don't leak that the address was blocked
        return {"ok": True}

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    # Unknown user → silently succeed (enumeration protection). No signup via magic link.
    if user is None:
        return {"ok": True}

    # Inactive user → silently succeed (don't leak account state)
    if not user.is_active:
        return {"ok": True}

    # Rate limit by user_id (5 requests / 10 min)
    if not await check_rate_limit(db, user.id):
        logger.warning(f"Magic-link rate limit hit for user_id={user.id}")
        return {"ok": True}

    code, link_token = await create_magic_link(db, user.id)
    await db.commit()

    link_url = build_magic_link_url(link_token)

    email_service = get_email_service()
    asyncio.create_task(email_service.send_magic_link(user.email, link_url, code))

    return {"ok": True}


class MagicLinkConsumeBody(BaseModel):
    token: str = Field(..., description="Signed magic-link token from the email URL")


@router.post("/consume")
async def consume_magic_link(
    body: MagicLinkConsumeBody,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """
    Consume a signed magic-link token from the emailed URL.

    POST (not GET) on purpose: email-security scanners (Gmail Safelinks,
    Outlook ATP, Slack unfurl, etc.) pre-fetch URLs with GET/HEAD to inspect
    for phishing. If /consume were GET, the scanner would consume the
    single-use token before the user ever clicks, and the user would see
    "invalid or expired" on arrival. POST requires an explicit button click
    in the frontend — scanners don't execute JS or click buttons.

    On success, sets the refresh cookie and returns the access_token so the
    frontend page at /auth/magic can store it and navigate the user.

    On failure, returns 401 with a generic message — the frontend page shows
    "this link is invalid or expired" without leaking specifics.
    """
    _ensure_enabled()

    user_id = await consume_link_token(db, body.token)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired sign-in link",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired sign-in link",
        )

    access_token = await issue_token_pair(db, user, response, request)
    await db.commit()

    return LoginResponse(access_token=access_token)


@router.post("/verify")
async def verify_magic_link_code(
    body: MagicLinkVerifyRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """
    Verify a 6-digit code entered manually from the email.

    Returns 401 on bad code (generic message). Returns access_token on success.
    """
    _ensure_enabled()

    email = body.email.strip().lower()

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        # Generic error — don't leak account existence
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired code",
        )

    valid = await verify_code(db, user.id, body.code)
    if not valid:
        await db.commit()  # persist attempt counter
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired code",
        )

    access_token = await issue_token_pair(db, user, response, request)
    await db.commit()

    return LoginResponse(access_token=access_token)
