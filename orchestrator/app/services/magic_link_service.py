"""
Magic-link (passwordless) login service.

Two paths backed by one EmailVerificationCode row (purpose="magic_login"):
  1. Click a signed URL ({app_base_url}/auth/magic?token=...) to sign in
  2. Manually type the 6-digit code shown in the email

Both paths converge on the same row, so consuming one invalidates the other.

Security properties:
- Codes are bcrypt-hashed at rest (via existing `EmailVerificationCode.code_hash`)
- Link tokens are signed with `itsdangerous.URLSafeTimedSerializer` — NOT JWTs,
  cannot be used for API auth
- Attempt limit enforced on the code path (same mechanic as 2FA)
- Per-email rate limit enforced at /request (see check_rate_limit)
- Link consume is O(1) existence check — no attempt counter needed since the
  token carries a signature (forging it requires SECRET_KEY)
"""

import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_password_hash, verify_password
from ..config import get_settings
from ..models import EmailVerificationCode

logger = logging.getLogger(__name__)
settings = get_settings()

PURPOSE = "magic_login"

# Signed token for the clickable link. The `link_id` payload is the
# EmailVerificationCode row id — consuming marks the row used.
_link_token_serializer = URLSafeTimedSerializer(
    settings.secret_key,
    salt="magic-link-login",
)


def generate_code() -> str:
    """Generate a random N-digit numeric code using cryptographic randomness."""
    length = settings.magic_link_code_length
    upper = 10**length
    return str(secrets.randbelow(upper)).zfill(length)


async def check_rate_limit(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """
    Return True if the user is within the rate limit, False if exceeded.

    Counts EmailVerificationCode rows (any state) for this user+purpose
    created within the window. This catches both invalidated and active
    requests, so hammering /request cannot be used for email spam.
    """
    window = timedelta(seconds=settings.magic_link_rate_limit_window_seconds)
    cutoff = datetime.now(UTC) - window

    result = await db.execute(
        select(func.count(EmailVerificationCode.id)).where(
            and_(
                EmailVerificationCode.user_id == user_id,
                EmailVerificationCode.purpose == PURPOSE,
                EmailVerificationCode.created_at > cutoff,
            )
        )
    )
    count = result.scalar_one()
    return count < settings.magic_link_rate_limit_max_requests


async def create_magic_link(db: AsyncSession, user_id: uuid.UUID) -> tuple[str, str]:
    """
    Create a new magic-link record for a user and return (plaintext_code, link_token).

    Invalidates any previous unused records for the same user+purpose, then
    creates a new one. Caller is responsible for the email send.
    """
    # Invalidate previous unused codes for this user+purpose
    await db.execute(
        update(EmailVerificationCode)
        .where(
            and_(
                EmailVerificationCode.user_id == user_id,
                EmailVerificationCode.purpose == PURPOSE,
                EmailVerificationCode.used == False,  # noqa: E712
            )
        )
        .values(used=True)
    )

    plaintext_code = generate_code()
    code_hash = get_password_hash(plaintext_code)
    record_id = uuid.uuid4()

    record = EmailVerificationCode(
        id=record_id,
        user_id=user_id,
        code_hash=code_hash,
        purpose=PURPOSE,
        attempts=0,
        max_attempts=settings.magic_link_max_attempts,
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.magic_link_code_expiry_seconds),
        used=False,
    )
    db.add(record)
    await db.flush()

    link_token = _link_token_serializer.dumps(str(record_id))
    return plaintext_code, link_token


async def verify_code(db: AsyncSession, user_id: uuid.UUID, code: str) -> bool:
    """
    Verify a magic-link code for a user.

    Checks: hash match, not expired, not used, attempts not exceeded.
    On success, marks the record as used.
    On wrong code, increments attempts and invalidates after max.
    """
    now = datetime.now(UTC)

    result = await db.execute(
        select(EmailVerificationCode)
        .where(
            and_(
                EmailVerificationCode.user_id == user_id,
                EmailVerificationCode.purpose == PURPOSE,
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

    if record.attempts >= record.max_attempts:
        record.used = True
        await db.flush()
        return False

    if verify_password(code, record.code_hash):
        record.used = True
        await db.flush()
        return True

    record.attempts += 1
    if record.attempts >= record.max_attempts:
        record.used = True
    await db.flush()
    return False


async def consume_link_token(db: AsyncSession, token: str) -> uuid.UUID | None:
    """
    Consume a magic-link click token.

    Validates signature + expiry, looks up the referenced record, atomically
    marks it used, and returns the user_id.

    Returns None if:
    - Signature is invalid or expired
    - Record was not found
    - Record is already used (atomic mark-as-used prevents replay)
    - Record has expired

    Note: link path does not consult the attempt counter. Attempts only
    count wrong manual-code entries; a valid signed link always bypasses them.
    """
    max_age = settings.magic_link_token_expiry_seconds
    try:
        record_id_str = _link_token_serializer.loads(token, max_age=max_age)
        record_id = uuid.UUID(record_id_str)
    except (BadSignature, SignatureExpired, ValueError):
        return None

    now = datetime.now(UTC)

    # Atomic mark-as-used: only succeeds if record is still valid
    result = await db.execute(
        update(EmailVerificationCode)
        .where(
            and_(
                EmailVerificationCode.id == record_id,
                EmailVerificationCode.purpose == PURPOSE,
                EmailVerificationCode.used == False,  # noqa: E712
                EmailVerificationCode.expires_at > now,
            )
        )
        .values(used=True)
        .returning(EmailVerificationCode.user_id)
    )
    row = result.first()
    if row is None:
        return None
    return row[0]


def build_magic_link_url(link_token: str) -> str:
    """Build the absolute URL the user clicks in their email."""
    base = settings.get_app_base_url.rstrip("/")
    return f"{base}/auth/magic?token={link_token}"
