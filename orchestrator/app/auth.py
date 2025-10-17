from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
import bcrypt
import secrets
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from .database import get_db
from .models import User, RefreshToken
from .config import get_settings

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def verify_password(plain_password, hashed_password):
    # Use bcrypt directly to avoid passlib issues
    try:
        # bcrypt has a 72-byte limit, truncate if necessary
        password_bytes = plain_password.encode('utf-8')[:72]
        return bcrypt.checkpw(password_bytes, hashed_password.encode('utf-8'))
    except Exception:
        # Fallback to passlib
        if len(plain_password.encode('utf-8')) > 72:
            plain_password = plain_password.encode('utf-8')[:72].decode('utf-8', errors='ignore')
        return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    # Use bcrypt directly to avoid passlib issues
    try:
        # bcrypt has a 72-byte limit, truncate if necessary
        password_bytes = password.encode('utf-8')[:72]
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password_bytes, salt)
        return hashed.decode('utf-8')
    except Exception:
        # Fallback to passlib
        if len(password.encode('utf-8')) > 72:
            password = password.encode('utf-8')[:72].decode('utf-8', errors='ignore')
        return pwd_context.hash(password)

async def authenticate_user(db: AsyncSession, username_or_email: str, password: str):
    """Authenticate user by username or email and password."""
    # Try to find user by username or email
    from sqlalchemy import or_
    result = await db.execute(
        select(User).where(
            or_(User.username == username_or_email, User.email == username_or_email)
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        return False
    if not verify_password(password, user.hashed_password):
        return False
    return user

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
    return encoded_jwt

async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception
    return user

async def get_current_active_user(current_user: User = Depends(get_current_user)):
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


async def create_refresh_token(user: User, db: AsyncSession) -> str:
    """
    Create a new refresh token for a user.

    Best practice: Refresh tokens should be:
    - Long-lived (7-30 days)
    - Stored securely in database
    - Revocable
    - Single-use (rotate on refresh)
    """
    # Generate secure random token
    token = secrets.token_urlsafe(32)

    # Set expiration (14 days)
    expires_at = datetime.now(timezone.utc) + timedelta(days=14)

    # Store in database
    db_token = RefreshToken(
        token=token,
        user_id=user.id,
        expires_at=expires_at
    )
    db.add(db_token)
    await db.commit()

    return token


async def validate_refresh_token(token: str, db: AsyncSession) -> Optional[User]:
    """
    Validate a refresh token and return the associated user.

    Returns None if token is invalid, expired, or revoked.
    """
    # Query for the refresh token
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token == token,
            RefreshToken.revoked == False
        )
    )
    db_token = result.scalar_one_or_none()

    if not db_token:
        return None

    # Check if token is expired
    current_time = datetime.now(timezone.utc)
    if current_time > db_token.expires_at:
        # Clean up expired token
        db_token.revoked = True
        await db.commit()
        return None

    # Get user
    result = await db.execute(
        select(User).where(User.id == db_token.user_id)
    )
    user = result.scalar_one_or_none()

    return user


async def revoke_refresh_token(token: str, db: AsyncSession) -> bool:
    """
    Revoke a refresh token (best practice: rotate on use).

    Returns True if token was found and revoked, False otherwise.
    """
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token == token)
    )
    db_token = result.scalar_one_or_none()

    if db_token:
        db_token.revoked = True
        await db.commit()
        return True

    return False


async def cleanup_expired_tokens(db: AsyncSession) -> int:
    """Clean up expired refresh tokens (call periodically)."""
    from sqlalchemy import delete

    result = await db.execute(
        delete(RefreshToken).where(
            RefreshToken.expires_at < datetime.now(timezone.utc)
        )
    )
    await db.commit()

    return result.rowcount