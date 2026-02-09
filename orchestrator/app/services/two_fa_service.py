"""
Two-factor authentication service.

Handles OTP generation, verification, and temporary token management
for email-based 2FA.
"""

import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_password_hash, verify_password
from ..config import get_settings
from ..models import EmailVerificationCode

logger = logging.getLogger(__name__)
settings = get_settings()

# Serializer for temporary 2FA tokens (NOT JWTs — cannot be used for API auth)
_temp_token_serializer = URLSafeTimedSerializer(
    settings.secret_key,
    salt="2fa-temp-token",
)


def generate_code() -> str:
    """Generate a random 6-digit numeric code using cryptographic randomness."""
    length = settings.two_fa_code_length
    upper = 10**length
    code_int = secrets.randbelow(upper)
    return str(code_int).zfill(length)


async def create_verification_code(db: AsyncSession, user_id: uuid.UUID, purpose: str) -> str:
    """
    Create a new verification code for a user.

    Invalidates any previous unused codes for the same user+purpose,
    then creates a new one.

    Returns the plaintext code (caller sends it via email).
    """
    # Invalidate previous unused codes for this user+purpose
    await db.execute(
        update(EmailVerificationCode)
        .where(
            and_(
                EmailVerificationCode.user_id == user_id,
                EmailVerificationCode.purpose == purpose,
                EmailVerificationCode.used == False,  # noqa: E712
            )
        )
        .values(used=True)
    )

    # Generate and store new code
    plaintext_code = generate_code()
    code_hash = get_password_hash(plaintext_code)

    record = EmailVerificationCode(
        id=uuid.uuid4(),
        user_id=user_id,
        code_hash=code_hash,
        purpose=purpose,
        attempts=0,
        max_attempts=settings.two_fa_max_attempts,
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.two_fa_code_expiry_seconds),
        used=False,
    )
    db.add(record)
    await db.flush()

    return plaintext_code


async def verify_code(db: AsyncSession, user_id: uuid.UUID, code: str, purpose: str) -> bool:
    """
    Verify a 2FA code for a user.

    Checks: hash match, not expired, not used, attempts not exceeded.
    On success, marks the code as used.
    On failure, increments attempts.
    """
    now = datetime.now(UTC)

    result = await db.execute(
        select(EmailVerificationCode)
        .where(
            and_(
                EmailVerificationCode.user_id == user_id,
                EmailVerificationCode.purpose == purpose,
                EmailVerificationCode.used == False,  # noqa: E712
                EmailVerificationCode.expires_at > now,
            )
        )
        .order_by(EmailVerificationCode.created_at.desc())
        .limit(1)
    )
    record = result.scalar_one_or_none()

    if record is None:
        return False

    # Check attempt limit
    if record.attempts >= record.max_attempts:
        record.used = True  # Invalidate
        await db.flush()
        return False

    # Verify code hash
    if verify_password(code, record.code_hash):
        record.used = True
        await db.flush()
        return True

    # Wrong code — increment attempts
    record.attempts += 1
    if record.attempts >= record.max_attempts:
        record.used = True  # Invalidate after max attempts
    await db.flush()
    return False


def create_temp_token(user_id: uuid.UUID) -> str:
    """
    Create a signed temporary token for the 2FA verification step.

    This token is NOT a JWT and cannot be used for API authentication.
    It simply carries the user_id through the 2FA verification flow.
    """
    return _temp_token_serializer.dumps(str(user_id))


def validate_temp_token(token: str) -> uuid.UUID | None:
    """
    Validate a temporary 2FA token and extract the user_id.

    Returns the user_id UUID or None if invalid/expired.
    """
    try:
        user_id_str = _temp_token_serializer.loads(
            token, max_age=settings.two_fa_temp_token_expiry_seconds
        )
        return uuid.UUID(user_id_str)
    except (BadSignature, SignatureExpired, ValueError):
        return None


async def cleanup_expired_codes(db: AsyncSession) -> int:
    """
    Delete expired and used verification codes older than 1 hour.

    Called opportunistically to keep the table clean.
    Returns the number of deleted rows.
    """
    cutoff = datetime.now(UTC) - timedelta(hours=1)
    result = await db.execute(
        EmailVerificationCode.__table__.delete().where(EmailVerificationCode.created_at < cutoff)
    )
    return result.rowcount
