from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
import bcrypt
import secrets
import logging
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from .database import get_db
from .models import User
from .config import get_settings

logger = logging.getLogger(__name__)

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
    logger.info(f"[AUTH] get_current_user called with token: {token[:20]}..." if token else "[AUTH] get_current_user called with no token")

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        logger.info("[AUTH] Attempting to decode JWT token")
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        logger.info(f"[AUTH] JWT decoded successfully. Payload: {payload}")

        username: str = payload.get("sub")
        logger.info(f"[AUTH] Extracted username from token: {username}")

        if username is None:
            logger.error("[AUTH] Username is None in token payload")
            raise credentials_exception
    except JWTError as e:
        logger.error(f"[AUTH] JWT decode failed: {str(e)}")
        raise credentials_exception

    logger.info(f"[AUTH] Querying database for user: {username}")
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if user is None:
        logger.error(f"[AUTH] User not found in database: {username}")
        raise credentials_exception

    logger.info(f"[AUTH] User authenticated successfully: {username} (id: {user.id})")
    return user

async def get_current_active_user(current_user: User = Depends(get_current_user)):
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


async def verify_token_for_user(token: str, db: AsyncSession) -> Optional[User]:
    """
    Verify a JWT token and return the user (for WebSocket authentication).
    Returns None if token is invalid.
    """
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        username: str = payload.get("sub")
        if username is None:
            return None
    except JWTError:
        return None

    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    return user
