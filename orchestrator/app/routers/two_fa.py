"""
Two-factor authentication endpoints.

Email 2FA is mandatory for all email/password logins.
OAuth logins (Google/GitHub) bypass 2FA.

Provides:
- Custom login endpoint that always requires email verification
- 2FA code verification during login
- 2FA code resend during login
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, Form, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_db
from ..schemas_auth import (
    LoginResponse,
    TwoFAVerifyRequest,
)
from ..services.email_service import get_email_service
from ..services.two_fa_service import (
    cleanup_expired_codes,
    create_temp_token,
    create_verification_code,
    validate_temp_token,
    verify_code,
)
from ..users import get_jwt_strategy, get_user_manager

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter()


# ==========================================================================
# Custom Login (replaces direct fastapi-users JWT login for email/password)
# ==========================================================================


@router.post("/login", response_model=LoginResponse)
async def custom_login(
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user_manager=Depends(get_user_manager),
):
    """
    Custom login that always requires email 2FA before issuing JWT.

    Accepts form-encoded username (email) and password,
    matching the fastapi-users login format.
    """
    from sqlalchemy import select

    from ..models_auth import User

    # Authenticate credentials
    result = await db.execute(select(User).where(User.email == username))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LOGIN_BAD_CREDENTIALS",
        )

    # Use fastapi-users password helper (supports argon2 hashes)
    verified, _updated_hash = user_manager.password_helper.verify_and_update(
        password, user.hashed_password
    )
    if not verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LOGIN_BAD_CREDENTIALS",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LOGIN_BAD_CREDENTIALS",
        )

    # If 2FA is disabled globally, issue JWT directly
    if not settings.two_fa_enabled:
        strategy = get_jwt_strategy()
        token = await strategy.write_token(user)
        return LoginResponse(access_token=token)

    # Generate code and return temp token (mandatory 2FA)
    code = await create_verification_code(db, user.id, "2fa_login")
    await db.commit()

    # Send code via email (fire-and-forget, non-blocking)
    email_service = get_email_service()
    asyncio.create_task(email_service.send_2fa_code(user.email, code))

    temp_token = create_temp_token(user.id)

    return LoginResponse(
        requires_2fa=True,
        temp_token=temp_token,
        method="email",
    )


# ==========================================================================
# 2FA Verification (during login — no auth required, uses temp_token)
# ==========================================================================


@router.post("/2fa/verify", response_model=LoginResponse)
async def verify_2fa(
    body: TwoFAVerifyRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Verify 2FA code during login.

    Uses temp_token (not JWT) to identify the user.
    On success, returns a real JWT access_token.
    """
    from sqlalchemy import select

    from ..models_auth import User

    # Validate temp token
    user_id = validate_temp_token(body.temp_token)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired verification session",
        )

    # Verify the code
    valid = await verify_code(db, user_id, body.code, "2fa_login")
    if not valid:
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired code",
        )

    await db.commit()

    # Fetch user and issue JWT
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired verification session",
        )

    strategy = get_jwt_strategy()
    token = await strategy.write_token(user)

    # Opportunistic cleanup
    asyncio.create_task(_cleanup_codes())

    return LoginResponse(access_token=token)


# ==========================================================================
# 2FA Resend (during login — uses temp_token)
# ==========================================================================


@router.post("/2fa/resend")
async def resend_2fa_code(
    temp_token: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Resend the 2FA code during login. Uses temp_token to identify the user.
    """
    from sqlalchemy import select

    from ..models_auth import User

    user_id = validate_temp_token(temp_token)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired verification session",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired verification session",
        )

    code = await create_verification_code(db, user.id, "2fa_login")
    await db.commit()

    email_service = get_email_service()
    asyncio.create_task(email_service.send_2fa_code(user.email, code))

    return {"detail": "Verification code resent"}


# ==========================================================================
# Helper
# ==========================================================================


async def _cleanup_codes():
    """Background cleanup of expired codes."""
    try:
        from ..database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            await cleanup_expired_codes(session)
            await session.commit()
    except Exception as e:
        logger.debug(f"Code cleanup error (non-critical): {e}")
