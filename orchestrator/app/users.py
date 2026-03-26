"""
FastAPI-Users configuration with dual authentication strategy.

This module sets up:
1. Database adapters for User, OAuthAccount, and AccessToken
2. User manager with custom logic (referral codes, slugs, etc.)
3. Dual authentication strategies:
   - Cookie-based JWT (with CSRF protection) for web frontend
   - Bearer token JWT for API clients
4. FastAPI-Users instance with all auth routes
"""

import uuid
from datetime import UTC, datetime

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin
from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    CookieTransport,
    JWTStrategy,
)
from fastapi_users.db import SQLAlchemyUserDatabase
from fastapi_users.exceptions import UserAlreadyExists
from fastapi_users_db_sqlalchemy.access_token import (
    SQLAlchemyAccessTokenDatabase,
)
from nanoid import generate
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from .config import get_settings
from .database import get_db
from .models_auth import AccessToken, OAuthAccount, User
from .schemas_auth import UserCreate

settings = get_settings()

# Secret key for JWT
SECRET = settings.secret_key


# ============================================================================
# Database Adapters
# ============================================================================


async def get_user_db(session: AsyncSession = Depends(get_db)):
    """Dependency to get the User database adapter."""
    yield SQLAlchemyUserDatabase(session, User, OAuthAccount)


async def get_access_token_db(session: AsyncSession = Depends(get_db)):
    """Dependency to get the AccessToken database adapter (for bearer strategy)."""
    yield SQLAlchemyAccessTokenDatabase(session, AccessToken)


# ============================================================================
# User Manager
# ============================================================================


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    """
    Custom user manager with Tesslate Studio-specific logic.

    Handles:
    - User registration with custom fields (name, username, slug, referral)
    - Automatic slug generation
    - Referral tracking
    - LiteLLM user provisioning
    - Password validation
    """

    reset_password_token_secret = SECRET
    verification_token_secret = SECRET

    async def on_after_register(self, user: User, request: Request | None = None):
        """Called after successful user registration."""
        import logging

        logger = logging.getLogger(__name__)

        logger.info(f"User {user.id} has registered: {user.email}")

        # Create Stripe customer
        try:
            from .services.stripe_service import stripe_service

            customer = await stripe_service.create_customer(
                email=user.email,
                name=user.name,
                metadata={"user_id": str(user.id), "username": user.username},
            )

            if customer:
                user.stripe_customer_id = customer["id"]
                await self.user_db.session.commit()
                logger.info(f"Created Stripe customer for user {user.username}: {customer['id']}")
        except Exception as e:
            logger.error(f"Failed to create Stripe customer for user {user.username}: {e}")
            logger.warning(f"User {user.username} registered WITHOUT Stripe customer")

        # Initialize LiteLLM user key
        try:
            from .services.litellm_service import litellm_service

            litellm_result = await litellm_service.create_user_key(
                user_id=user.id, username=user.username
            )

            # Update user with LiteLLM details
            user.litellm_api_key = litellm_result["api_key"]
            user.litellm_user_id = litellm_result["litellm_user_id"]
            await self.user_db.session.commit()

            logger.info(f"Created LiteLLM key for user {user.username}")
        except Exception as e:
            logger.error(f"Failed to create LiteLLM key for user {user.username}: {e}")
            logger.warning(f"User {user.username} registered WITHOUT LiteLLM key")

        # Grant signup bonus credits and initialize daily credits
        try:
            from datetime import timedelta

            user.signup_bonus_credits = settings.signup_bonus_credits
            user.signup_bonus_expires_at = datetime.now(UTC) + timedelta(
                days=settings.signup_bonus_expiry_days
            )
            # Initialize daily credits for free tier
            tier = user.subscription_tier or "free"
            if tier == "free":
                user.daily_credits = settings.tier_daily_credits_free
                user.daily_credits_reset_date = datetime.now(UTC)
            user.support_tier = settings.get_support_tier(tier)
            await self.user_db.session.commit()
            logger.info(
                f"Granted {settings.signup_bonus_credits} signup bonus credits to {user.username} "
                f"(expires in {settings.signup_bonus_expiry_days} days)"
            )
        except Exception as e:
            logger.error(f"Failed to grant signup bonus to {user.username}: {e}")

        # Auto-add default agents (Tesslate Agent) to new users
        try:
            from sqlalchemy import select

            from .models import MarketplaceAgent, UserPurchasedAgent

            # Default agents to add to every new user
            default_agent_slugs = ["tesslate-agent"]

            for slug in default_agent_slugs:
                result = await self.user_db.session.execute(
                    select(MarketplaceAgent).where(MarketplaceAgent.slug == slug)
                )
                agent = result.scalar_one_or_none()

                if agent:
                    purchase = UserPurchasedAgent(
                        user_id=user.id, agent_id=agent.id, purchase_type="free", is_active=True
                    )
                    self.user_db.session.add(purchase)
                    logger.info(f"Auto-added {agent.name} to user {user.username}")
                else:
                    logger.warning(f"{slug} not found - user registered without this default agent")

            await self.user_db.session.commit()
        except Exception as e:
            logger.error(f"Failed to add default agents to user {user.username}: {e}")

        # Auto-add default themes (default-dark, default-light) to new users
        try:
            from sqlalchemy import select

            from .models import Theme, UserLibraryTheme

            default_theme_ids = ["default-dark", "default-light"]

            for theme_id in default_theme_ids:
                result = await self.user_db.session.execute(
                    select(Theme).where(Theme.id == theme_id)
                )
                theme = result.scalar_one_or_none()

                if theme:
                    library_entry = UserLibraryTheme(
                        user_id=user.id, theme_id=theme.id, purchase_type="free", is_active=True
                    )
                    self.user_db.session.add(library_entry)
                    logger.info(f"Auto-added theme {theme.name} to user {user.username}")
                else:
                    logger.warning(
                        f"Theme {theme_id} not found - user registered without this default theme"
                    )

            await self.user_db.session.commit()
        except Exception as e:
            logger.error(f"Failed to add default themes to user {user.username}: {e}")

        # Send Discord signup notification
        try:
            from .services.discord_service import discord_service

            await discord_service.send_signup_notification(
                username=user.username, email=user.email, name=user.name, user_id=str(user.id)
            )
        except Exception as e:
            logger.error(f"Failed to send Discord signup notification: {e}")

        # Track referral conversion if referred_by is set
        if user.referred_by:
            try:
                from .referral_db import save_conversion
                from .services.discord_service import discord_service
                from .services.ntfy_service import ntfy_service

                save_conversion(
                    user.referred_by, str(user.id), user.username, user.email, user.name
                )

                await discord_service.send_referral_conversion_notification(
                    referred_by=user.referred_by,
                    new_user_name=user.name,
                    new_user_username=user.username,
                    new_user_email=user.email,
                    user_id=str(user.id),
                )

                await ntfy_service.send_referral_conversion(user.referred_by, user.username)
                logger.info(f"Tracked referral conversion: {user.referred_by} -> {user.username}")
            except Exception as e:
                logger.error(f"Failed to track referral conversion: {e}")

        # Create personal team (RBAC)
        await self._create_personal_team(user)

        # Auto-accept any pending team invitations matching this email
        await self._auto_accept_pending_invites(user)

    async def _create_personal_team(self, user):
        """Create a personal team for a newly registered user."""
        import logging

        logger = logging.getLogger(__name__)
        try:
            from .models_team import Team, TeamMembership

            import uuid as _uuid

            team_id = _uuid.uuid4()
            team = Team(
                id=team_id,
                name=f"{user.name}'s Team",
                slug=f"{user.slug}-team",
                is_personal=True,
                created_by_id=user.id,
                subscription_tier=user.subscription_tier or "free",
                daily_credits=user.daily_credits or 0,
                signup_bonus_credits=user.signup_bonus_credits or 0,
                signup_bonus_expires_at=user.signup_bonus_expires_at,
            )
            self.user_db.session.add(team)
            await self.user_db.session.flush()

            membership = TeamMembership(
                team_id=team_id,
                user_id=user.id,
                role="admin",
            )
            self.user_db.session.add(membership)
            user.default_team_id = team_id
            await self.user_db.session.commit()
            logger.info(f"Created personal team for user {user.username}: {team.slug}")
        except Exception as e:
            logger.error(f"Failed to create personal team for {user.username}: {e}")

    async def _auto_accept_pending_invites(self, user):
        """Auto-accept any pending team invitations matching this user's email."""
        import logging

        logger = logging.getLogger(__name__)
        try:
            from datetime import UTC, datetime

            from sqlalchemy import and_, select

            from .models_team import TeamInvitation, TeamMembership

            result = await self.user_db.session.execute(
                select(TeamInvitation).where(
                    and_(
                        TeamInvitation.email == user.email,
                        TeamInvitation.accepted_at.is_(None),
                        TeamInvitation.revoked_at.is_(None),
                        TeamInvitation.expires_at > datetime.now(UTC),
                    )
                )
            )
            invites = result.scalars().all()
            for invite in invites:
                if invite.max_uses is not None and invite.use_count >= invite.max_uses:
                    continue
                membership = TeamMembership(
                    team_id=invite.team_id,
                    user_id=user.id,
                    role=invite.role,
                    invited_by_id=invite.invited_by_id,
                )
                self.user_db.session.add(membership)
                invite.accepted_at = datetime.now(UTC)
                invite.accepted_by_id = user.id
                invite.use_count += 1
            if invites:
                await self.user_db.session.commit()
                logger.info(f"Auto-accepted {len(invites)} pending invite(s) for {user.email}")
        except Exception as e:
            logger.error(f"Failed to auto-accept invites for {user.email}: {e}")

    async def on_after_login(
        self, user: User, request: Request | None = None, response: Response | None = None
    ):
        """Called after successful user login."""
        import logging

        logger = logging.getLogger(__name__)

        logger.info(f"User {user.id} has logged in: {user.email}")

        # Send Discord login notification
        try:
            from .services.discord_service import discord_service

            await discord_service.send_login_notification(
                username=user.username, email=user.email, user_id=str(user.id)
            )
        except Exception as e:
            logger.error(f"Failed to send Discord login notification: {e}")

    async def on_after_forgot_password(
        self, user: User, token: str, request: Request | None = None
    ):
        """Called after forgot password request. Sends a password reset email."""
        import asyncio
        import logging

        logger = logging.getLogger(__name__)

        reset_url = f"{settings.get_app_base_url}/reset-password?token={token}"
        logger.info(f"Password reset requested for user {user.id} ({user.email})")

        try:
            from .services.email_service import get_email_service

            email_service = get_email_service()
            asyncio.create_task(email_service.send_password_reset(user.email, reset_url))
        except Exception as e:
            logger.error(f"Failed to send password reset email to {user.email}: {e}")

    async def on_after_request_verify(self, user: User, token: str, request: Request | None = None):
        """Called after email verification request."""
        print(f"Verification requested for user {user.id}. Verification token: {token}")
        # TODO: Send verification email

    async def create(
        self,
        user_create: UserCreate,
        safe: bool = False,
        request: Request | None = None,
    ) -> User:
        """
        Create a new user with custom fields.

        Extends the base create method to:
        - Generate a unique slug from username
        - Generate a referral code
        - Track referrer if provided
        """
        from .compliance import enforce_email_compliance

        enforce_email_compliance(user_create.email)

        # Call parent create to handle password hashing and validation
        await self.validate_password(user_create.password, user_create)

        # Create user dict with all fields
        user_dict = user_create.model_dump()

        # Hash password
        password = user_dict.pop("password")
        user_dict["hashed_password"] = self.password_helper.hash(password)

        # Auto-generate username from email if not provided
        if not user_dict.get("username"):
            email_username = user_dict["email"].split("@")[0]
            base_username = (
                email_username.lower().replace(".", "").replace("+", "").replace("-", "")[:20]
            )
            username_suffix = generate(size=6)
            user_dict["username"] = f"{base_username}_{username_suffix}"

        # Generate unique slug from username (e.g., "john-doe-a3x9k2")
        base_slug = user_dict["username"].lower().replace("_", "-").replace(" ", "-")
        slug_suffix = generate(size=6)  # Generate 6-character nanoid
        user_dict["slug"] = f"{base_slug}-{slug_suffix}"

        # Generate referral code (8-character nanoid)
        user_dict["referral_code"] = generate(size=8).upper()

        # Track referrer if provided
        if user_create.referral_code:
            # TODO: Validate referral code exists and mark conversion
            user_dict["referred_by"] = user_create.referral_code

        # Create user in database
        user = User(**user_dict)
        self.user_db.session.add(user)
        try:
            await self.user_db.session.commit()
            await self.user_db.session.refresh(user)
        except IntegrityError as e:
            await self.user_db.session.rollback()
            # Check if it's a duplicate email constraint violation
            if "ix_users_email" in str(e.orig):
                raise UserAlreadyExists() from e
            # Re-raise other integrity errors
            raise

        await self.on_after_register(user, request)

        return user

    async def oauth_callback(
        self,
        oauth_name: str,
        access_token: str,
        account_id: str,
        account_email: str,
        expires_at: int | None = None,
        refresh_token: str | None = None,
        request: Request | None = None,
        *,
        associate_by_email: bool = False,
        is_verified_by_default: bool = False,
        avatar_url: str | None = None,
    ) -> User:
        """
        Handle OAuth callback and create/update user.

        Overrides the default method to properly handle our custom fields:
        - name: Extract from OAuth profile or generate from email
        - username: Generate from email
        - slug: Generate unique slug
        """
        import logging

        from .compliance import enforce_email_compliance

        logger = logging.getLogger(__name__)

        enforce_email_compliance(account_email)

        # Try to get existing user by OAuth account
        # get_by_oauth_account returns the User object directly, not the OAuthAccount
        user = await self.user_db.get_by_oauth_account(oauth_name, account_id)

        if user:
            logger.info(f"Found existing OAuth account for {oauth_name} user {account_id}")
            # Backfill avatar if not already set
            if avatar_url and not user.avatar_url:
                user.avatar_url = avatar_url
                await self.user_db.session.commit()
            return user

        # Try to find by email if associate_by_email is True
        if associate_by_email:
            try:
                user = await self.user_db.get_by_email(account_email)
                if user:
                    logger.info(f"Associating existing user {user.id} with {oauth_name} account")
                    # Backfill avatar if not already set
                    if avatar_url and not user.avatar_url:
                        user.avatar_url = avatar_url
                    # Create OAuth account link
                    await self.user_db.add_oauth_account(
                        user,
                        {
                            "oauth_name": oauth_name,
                            "account_id": account_id,
                            "account_email": account_email,
                            "access_token": access_token,
                            "expires_at": expires_at,
                            "refresh_token": refresh_token,
                        },
                    )
                    return user
            except Exception as e:
                logger.debug(f"User not found by email: {e}")

        # Create new user from OAuth data
        # Generate username from email (everything before @)
        email_username = account_email.split("@")[0]
        base_username = (
            email_username.lower().replace(".", "").replace("+", "").replace("-", "")[:20]
        )

        # Make username unique by appending nanoid
        username_suffix = generate(size=6)
        username = f"{base_username}_{username_suffix}"

        # Generate slug
        base_slug = username.lower().replace("_", "-")
        slug_suffix = generate(size=6)
        slug = f"{base_slug}-{slug_suffix}"

        # Generate referral code
        referral_code = generate(size=8).upper()

        # Extract name from email as fallback
        name = email_username.replace(".", " ").replace("_", " ").title()

        logger.info(
            f"Creating new user from {oauth_name} OAuth: email={account_email}, name={name}, username={username}"
        )

        # Create user with required fields
        user_dict = {
            "email": account_email,
            "name": name,
            "username": username,
            "slug": slug,
            "referral_code": referral_code,
            "is_active": True,
            "is_superuser": False,
            "is_verified": is_verified_by_default,
            # OAuth users don't have passwords - generate a random one they can't use
            "hashed_password": self.password_helper.hash(generate(size=32)),
            "subscription_tier": "free",
            "total_spend": 0,
            "bundled_credits": 0,
            "purchased_credits": 0,
            "avatar_url": avatar_url,
        }

        user = User(**user_dict)
        self.user_db.session.add(user)
        await self.user_db.session.commit()
        await self.user_db.session.refresh(user)

        # Create OAuth account link
        await self.user_db.add_oauth_account(
            user,
            {
                "oauth_name": oauth_name,
                "account_id": account_id,
                "account_email": account_email,
                "access_token": access_token,
                "expires_at": expires_at,
                "refresh_token": refresh_token,
            },
        )

        # Call post-registration hooks
        await self.on_after_register(user, request)

        return user

    async def validate_password(self, password: str, user: UserCreate | User) -> None:
        """
        Validate password meets requirements.

        Requirements:
        - Minimum 6 characters (for bcrypt compatibility)
        - Maximum 72 characters (bcrypt limit)
        """
        if len(password) < 6:
            raise ValueError("Password must be at least 6 characters long")
        if len(password) > 72:
            raise ValueError("Password must be at most 72 characters long (bcrypt limit)")

        # Check password is not just the email or username
        if hasattr(user, "email") and user.email and password.lower() == user.email.lower():
            raise ValueError("Password cannot be the same as your email")
        if (
            hasattr(user, "username")
            and user.username
            and password.lower() == user.username.lower()
        ):
            raise ValueError("Password cannot be the same as your username")


async def get_user_manager(user_db: SQLAlchemyUserDatabase = Depends(get_user_db)):
    """Dependency to get the user manager."""
    yield UserManager(user_db)


# ============================================================================
# Authentication Strategies
# ============================================================================

# Cookie Transport (for web frontend with CSRF protection)
cookie_transport = CookieTransport(
    cookie_max_age=settings.access_token_expire_minutes * 60,
    cookie_name="tesslate_auth",
    cookie_secure=settings.cookie_secure,  # From environment variable
    cookie_httponly=True,  # Prevent XSS attacks
    cookie_samesite=settings.cookie_samesite,  # From environment variable
    cookie_domain=settings.cookie_domain
    if settings.cookie_domain
    else None,  # From environment variable
)

# Bearer Transport (for API clients)
bearer_transport = BearerTransport(tokenUrl="auth/jwt/login")


def get_jwt_strategy() -> JWTStrategy:
    """
    JWT strategy for stateless authentication.

    Custom strategy that includes is_admin field in token payload.
    """
    from datetime import datetime, timedelta

    from jose import jwt as jose_jwt

    class CustomJWTStrategy(JWTStrategy):
        async def write_token(self, user: User) -> str:
            """Override to include is_admin in token payload."""
            data = {
                "sub": str(user.id),
                "aud": self.token_audience,
                "is_admin": user.is_superuser,  # Add is_admin field
            }

            # Add expiration
            data["exp"] = datetime.now(UTC) + timedelta(seconds=self.lifetime_seconds)

            # Encode the JWT token
            return jose_jwt.encode(data, self.secret, algorithm=self.algorithm)

    return CustomJWTStrategy(
        secret=SECRET,
        lifetime_seconds=settings.access_token_expire_minutes * 60,
        algorithm=settings.algorithm,
    )


# Authentication backends
cookie_backend = AuthenticationBackend(
    name="cookie",
    transport=cookie_transport,
    get_strategy=get_jwt_strategy,
)

bearer_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)

# ============================================================================
# FastAPI-Users Instance
# ============================================================================

fastapi_users = FastAPIUsers[User, uuid.UUID](
    get_user_manager,
    [bearer_backend, cookie_backend],  # Bearer token takes priority over cookie auth
)

# Dependency to get current user (from either cookie or bearer token)
current_active_user = fastapi_users.current_user(active=True)

# Dependency to get current superuser
current_superuser = fastapi_users.current_user(active=True, superuser=True)

# Optional user (returns None if not authenticated)
current_optional_user = fastapi_users.current_user(optional=True)
