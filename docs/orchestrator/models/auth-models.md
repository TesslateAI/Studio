# Authentication & Credentials Models

This document covers models related to user authentication, OAuth integration, Git provider credentials, and deployment service credentials.

## Authentication Models

**File**: `c:\Users\Smirk\Downloads\Tesslate-Studio\orchestrator\app\models_auth.py`

OpenSail uses [FastAPI-Users](https://fastapi-users.github.io/fastapi-users/) for authentication, which provides a robust, battle-tested authentication system with support for email/password and OAuth providers.

---

## User Model

The User model is the central identity model, extending FastAPI-Users' `SQLAlchemyBaseUserTable` with Tesslate-specific features.

### Schema

```python
class User(SQLAlchemyBaseUserTable[uuid.UUID], Base):
    __tablename__ = "users"

    # FastAPI-Users base fields (inherited)
    id: UUID                    # Primary key
    email: str                  # Unique, indexed
    hashed_password: str        # Bcrypt hashed
    is_active: bool             # Account active?
    is_verified: bool           # Email verified?
    is_superuser: bool          # Admin privileges?

    # Identity
    name: str                   # Display name
    username: str               # Login identifier (unique)
    slug: str                   # URL-safe identifier (unique)

    # Subscription & billing
    subscription_tier: str      # free, basic, pro, ultra
    stripe_customer_id: str     # Stripe customer ID
    stripe_subscription_id: str # Active subscription
    total_spend: int            # Lifetime spend in cents
    deployed_projects_count: int # Deployed projects

    # Multi-source credit system (replaces old credits_balance)
    bundled_credits: int        # Monthly allowance, resets on billing date
    purchased_credits: int      # Never expire
    credits_reset_date: datetime # When bundled credits reset
    signup_bonus_credits: int   # Expires after N days
    signup_bonus_expires_at: datetime # When signup bonus expires
    daily_credits: int          # Free tier daily allowance
    daily_credits_reset_date: datetime # When daily credits reset
    support_tier: str           # "community" | "email" | "priority"
    # @property total_credits   # Computed sum: daily + bundled + signup_bonus + purchased

    # Creator payouts
    creator_stripe_account_id: str  # Stripe Connect account

    # LiteLLM integration
    litellm_api_key: str        # For usage tracking
    litellm_user_id: str        # LiteLLM user ID

    # User preferences
    diagram_model: str          # Model for architecture diagrams
    theme_preset: str           # Current theme ID (default: "default-dark")
    chat_position: str          # Chat panel position: "left" | "center" | "right"
    disabled_models: list       # Model IDs hidden from chat selector (JSON)

    # Public profile
    avatar_url: str             # Profile picture URL or base64 data URI
    bio: str                    # Short bio/description
    twitter_handle: str         # Twitter username
    github_username: str        # GitHub username
    website_url: str            # Personal website URL

    # Two-Factor Authentication
    two_fa_enabled: bool        # Whether 2FA is enabled (default: False)
    two_fa_method: str          # "email", "totp", etc.

    # Referral system
    referral_code: str          # Unique referral code
    referred_by: str            # Referrer's code

    # Activity tracking
    last_active_at: datetime
    created_at: datetime
    updated_at: datetime
```

### FastAPI-Users Integration

FastAPI-Users provides:
- **Email/Password Authentication**: Secure bcrypt password hashing
- **OAuth Integration**: Google, GitHub, etc.
- **JWT Tokens**: Stateless authentication with access/refresh tokens
- **Email Verification**: Optional email verification flow
- **Password Reset**: Secure password reset flow

### Key Relationships

```python
# OAuth accounts (Google, GitHub, etc.)
oauth_accounts: list[OAuthAccount] = relationship(
    "OAuthAccount", back_populates="user", cascade="all, delete-orphan"
)

# Access tokens (for Bearer token auth)
access_tokens: list[AccessToken] = relationship(
    "AccessToken", back_populates="user", cascade="all, delete-orphan"
)

# Git provider credentials
github_credential = relationship("GitHubCredential", back_populates="user", uselist=False)
git_provider_credentials = relationship("GitProviderCredential", back_populates="user")

# Deployment credentials
deployment_credentials = relationship("DeploymentCredential", back_populates="user")

# API keys
api_keys = relationship("UserAPIKey", back_populates="user")

# Projects and content
projects = relationship("Project", back_populates="owner")
chats = relationship("Chat", back_populates="user")
```

### Common Queries

**Get user by email (login)**:
```python
from fastapi_users.db import SQLAlchemyUserDatabase

user_db = SQLAlchemyUserDatabase(AsyncSession, User)
user = await user_db.get_by_email(email)
```

**Register a new user**:
```python
from fastapi_users import schemas

# Using FastAPI-Users UserManager
user = await user_manager.create(
    schemas.UserCreate(
        email="user@example.com",
        password="securepassword",
        name="John Doe",
        username="johndoe",
        slug="johndoe-xyz123"
    )
)
```

**Verify user email**:
```python
user.is_verified = True
await db.commit()
```

**Update subscription tier**:
```python
user.subscription_tier = "pro"
user.stripe_subscription_id = subscription.id
await db.commit()
```

### Subscription Tiers

- **free**: Limited features, rate limits, community support
- **pro**: Full features, higher rate limits, priority support
- **enterprise**: Custom limits, dedicated support, SLA

### Notes

- The `is_admin` property is an alias for `is_superuser` (backward compatibility)
- Passwords are hashed with bcrypt (never stored in plaintext)
- Email verification is optional but recommended for production
- Users can have multiple OAuth accounts (Google + GitHub)

---

## OAuthAccount Model

Stores OAuth provider connections (Google, GitHub, etc.) for users.

### Schema

```python
class OAuthAccount(SQLAlchemyBaseOAuthAccountTable[uuid.UUID], Base):
    __tablename__ = "oauth_accounts"

    # FastAPI-Users base fields (inherited)
    id: UUID
    user_id: UUID               # Foreign key to User
    oauth_name: str             # Provider name: "google", "github"
    access_token: str           # OAuth access token
    expires_at: int             # Token expiration timestamp (optional)
    refresh_token: str          # OAuth refresh token (optional)
    account_id: str             # Provider-specific account ID
    account_email: str          # Email from OAuth provider

    # Additional metadata
    created_at: datetime
    updated_at: datetime
```

### OAuth Providers

OpenSail supports:
- **Google**: OAuth 2.0 with openid, email, profile scopes
- **GitHub**: OAuth 2.0 with user:email, read:user scopes

### Key Relationships

```python
user = relationship("User", back_populates="oauth_accounts")
```

### Common Queries

**Get OAuth accounts for a user**:
```python
result = await db.execute(
    select(OAuthAccount)
    .where(OAuthAccount.user_id == user.id)
)
oauth_accounts = result.scalars().all()
```

**Check if user has GitHub connected**:
```python
result = await db.execute(
    select(OAuthAccount)
    .where(OAuthAccount.user_id == user.id)
    .where(OAuthAccount.oauth_name == "github")
)
github_account = result.scalar_one_or_none()

if github_account:
    # User has GitHub connected
    pass
```

**Get user by OAuth account**:
```python
result = await db.execute(
    select(User)
    .join(OAuthAccount)
    .where(OAuthAccount.oauth_name == "google")
    .where(OAuthAccount.account_id == google_user_id)
)
user = result.scalar_one_or_none()
```

### OAuth Flow

1. User clicks "Sign in with Google"
2. Frontend redirects to `/auth/google/authorize`
3. User authorizes on Google
4. Google redirects back with code
5. Backend exchanges code for tokens
6. Backend creates OAuthAccount record
7. Backend creates or links User account
8. Backend returns JWT to frontend

### Notes

- OAuth tokens are stored in plaintext (encrypted database at rest recommended)
- Refresh tokens allow re-authentication without user interaction
- Multiple OAuth accounts can link to the same user (email match)

---

## AccessToken Model

Stores access tokens for stateful Bearer token authentication (alternative to JWT).

### Schema

```python
class AccessToken(Base):
    __tablename__ = "access_tokens"

    # Token
    token: str                  # 43-character token (primary key)
    user_id: UUID               # Foreign key to User

    # Timestamp
    created_at: datetime
```

### Key Relationships

```python
user = relationship("User", back_populates="access_tokens")
```

### Common Queries

**Create access token**:
```python
import secrets

token = secrets.token_urlsafe(32)  # 43 characters
access_token = AccessToken(
    token=token,
    user_id=user.id
)
db.add(access_token)
await db.commit()
```

**Validate access token**:
```python
result = await db.execute(
    select(AccessToken)
    .options(selectinload(AccessToken.user))
    .where(AccessToken.token == token)
)
access_token = result.scalar_one_or_none()

if access_token:
    user = access_token.user
    # Token is valid
```

**Revoke access token**:
```python
await db.delete(access_token)
await db.commit()
```

### Notes

- AccessToken is used for stateful authentication (database-backed)
- Tokens do not expire automatically (must be revoked explicitly)
- For production, consider JWT with short-lived access tokens + refresh tokens

---

## Git Provider Credentials Models

**File**: `c:\Users\Smirk\Downloads\Tesslate-Studio\orchestrator\app\models.py`

---

## GitHubCredential Model (DEPRECATED)

**Note**: This model is deprecated. Use `GitProviderCredential` instead for unified Git provider support.

### Schema

```python
class GitHubCredential(Base):
    __tablename__ = "github_credentials"

    # Identity
    id: UUID
    user_id: UUID               # Foreign key to User (unique)

    # OAuth tokens (encrypted)
    access_token: str           # Encrypted OAuth access token
    refresh_token: str          # Encrypted OAuth refresh token
    token_expires_at: datetime

    # OAuth metadata
    scope: str                  # Granted scopes: "repo user:email"
    state: str                  # OAuth state for CSRF protection

    # GitHub user info
    github_username: str
    github_email: str
    github_user_id: str

    # Timestamps
    created_at: datetime
    updated_at: datetime
```

### Migration Path

Existing `GitHubCredential` records should be migrated to `GitProviderCredential`:

```python
# Migrate GitHubCredential to GitProviderCredential
old_cred = await db.get(GitHubCredential, user_id)

if old_cred:
    new_cred = GitProviderCredential(
        user_id=old_cred.user_id,
        provider="github",
        access_token=old_cred.access_token,
        refresh_token=old_cred.refresh_token,
        token_expires_at=old_cred.token_expires_at,
        scope=old_cred.scope,
        provider_username=old_cred.github_username,
        provider_email=old_cred.github_email,
        provider_user_id=old_cred.github_user_id
    )
    db.add(new_cred)
    await db.delete(old_cred)
    await db.commit()
```

---

## GitProviderCredential Model

Unified model for Git provider OAuth credentials (GitHub, GitLab, Bitbucket).

### Schema

```python
class GitProviderCredential(Base):
    __tablename__ = "git_provider_credentials"

    # Identity
    id: UUID
    user_id: UUID               # Foreign key to User
    provider: str               # 'github', 'gitlab', 'bitbucket'

    # OAuth tokens (encrypted)
    access_token: str           # Encrypted OAuth access token
    refresh_token: str          # Encrypted OAuth refresh token
    token_expires_at: datetime

    # OAuth metadata
    scope: str                  # Granted OAuth scopes

    # Provider user info
    provider_username: str
    provider_email: str
    provider_user_id: str

    # Timestamps
    created_at: datetime
    updated_at: datetime

    # Unique constraint: one credential per user per provider
    __table_args__ = (
        Index('ix_git_provider_credentials_user_provider', 'user_id', 'provider', unique=True),
    )
```

### Supported Providers

**GitHub**:
- OAuth App with `repo`, `user:email`, `read:user` scopes
- API: https://api.github.com

**GitLab**:
- OAuth App with `api`, `read_user` scopes
- API: https://gitlab.com/api/v4

**Bitbucket**:
- OAuth Consumer with `repository`, `account` scopes
- API: https://api.bitbucket.org/2.0

### Key Relationships

```python
user = relationship("User", back_populates="git_provider_credentials")
```

### Common Queries

**Get user's GitHub credential**:
```python
result = await db.execute(
    select(GitProviderCredential)
    .where(GitProviderCredential.user_id == user.id)
    .where(GitProviderCredential.provider == "github")
)
cred = result.scalar_one_or_none()
```

**Store GitHub OAuth tokens**:
```python
from app.services.encryption import encrypt_token

cred = GitProviderCredential(
    user_id=user.id,
    provider="github",
    access_token=encrypt_token(oauth_response["access_token"]),
    refresh_token=encrypt_token(oauth_response.get("refresh_token")),
    scope=oauth_response.get("scope"),
    provider_username=github_user["login"],
    provider_email=github_user["email"],
    provider_user_id=str(github_user["id"])
)
db.add(cred)
await db.commit()
```

**Refresh expired token**:
```python
from app.services.encryption import decrypt_token, encrypt_token

# Check if token expired
if cred.token_expires_at and datetime.utcnow() >= cred.token_expires_at:
    # Refresh token
    refresh_token = decrypt_token(cred.refresh_token)
    new_tokens = await refresh_oauth_token(cred.provider, refresh_token)

    # Update credential
    cred.access_token = encrypt_token(new_tokens["access_token"])
    if "refresh_token" in new_tokens:
        cred.refresh_token = encrypt_token(new_tokens["refresh_token"])
    cred.token_expires_at = new_tokens.get("expires_at")
    await db.commit()
```

### Security Notes

- OAuth tokens MUST be encrypted before storing in database
- Use Fernet symmetric encryption (or similar)
- Encryption key should be stored in environment variable, not in code
- Tokens should be decrypted only when needed (Git operations)

---

## GitRepository Model

Tracks Git repository connections for projects.

### Schema

```python
class GitRepository(Base):
    __tablename__ = "git_repositories"

    # Identity
    id: UUID
    project_id: UUID            # Foreign key to Project (unique)
    user_id: UUID               # Foreign key to User

    # Repository info
    repo_url: str               # GitHub repo URL
    repo_name: str              # Repository name
    repo_owner: str             # Repository owner
    default_branch: str         # "main" or "master"

    # Authentication method
    auth_method: str            # 'oauth' only

    # Sync status
    last_sync_at: datetime
    sync_status: str            # 'synced', 'ahead', 'behind', 'diverged', 'error'
    last_commit_sha: str        # Last known commit SHA

    # Configuration
    auto_push: bool             # Auto-push on file save?
    auto_pull: bool             # Auto-pull on project open?

    # Timestamps
    created_at: datetime
    updated_at: datetime
```

### Key Relationships

```python
project = relationship("Project", back_populates="git_repository")
user = relationship("User", back_populates="git_repositories")
```

### Common Queries

**Link Git repo to project**:
```python
git_repo = GitRepository(
    project_id=project.id,
    user_id=user.id,
    repo_url="https://github.com/user/repo",
    repo_name="repo",
    repo_owner="user",
    default_branch="main",
    auth_method="oauth",
    auto_push=False,
    auto_pull=False
)
db.add(git_repo)
await db.commit()
```

**Update sync status**:
```python
git_repo.sync_status = "synced"
git_repo.last_sync_at = datetime.utcnow()
git_repo.last_commit_sha = "abc123def456"
await db.commit()
```

---

## Deployment Credentials Models

**File**: `c:\Users\Smirk\Downloads\Tesslate-Studio\orchestrator\app\models.py`

---

## DeploymentCredential Model

Stores encrypted deployment credentials for various providers (Cloudflare, Vercel, Netlify, Supabase, etc.).

### Schema

```python
class DeploymentCredential(Base):
    __tablename__ = "deployment_credentials"

    # Identity
    id: UUID
    user_id: UUID               # Foreign key to User
    project_id: UUID            # Foreign key to Project (NULL for user defaults)
    provider: str               # cloudflare, vercel, netlify, supabase, stripe

    # Encrypted credentials
    access_token_encrypted: str # Encrypted API token/access token

    # Provider-specific metadata (JSON)
    provider_metadata: JSON     # Account IDs, namespace, etc.

    # Timestamps
    created_at: datetime
    updated_at: datetime
```

### Supported Providers

**Cloudflare Workers**:
```python
provider = "cloudflare"
access_token_encrypted = encrypt("cloudflare_api_token")
provider_metadata = {
    "account_id": "xxx",
    "dispatch_namespace": "yyy"
}
```

**Vercel**:
```python
provider = "vercel"
access_token_encrypted = encrypt("vercel_token")
provider_metadata = {
    "team_id": "team_xxx"  # Optional
}
```

**Netlify**:
```python
provider = "netlify"
access_token_encrypted = encrypt("netlify_token")
provider_metadata = {}  # No additional metadata
```

**Supabase**:
```python
provider = "supabase"
access_token_encrypted = encrypt("supabase_service_role_key")
provider_metadata = {
    "project_ref": "xxx",
    "endpoint": "https://xxx.supabase.co"
}
```

**Stripe**:
```python
provider = "stripe"
access_token_encrypted = encrypt("stripe_secret_key")
provider_metadata = {
    "publishable_key": "pk_test_xxx"
}
```

### Key Relationships

```python
user = relationship("User", back_populates="deployment_credentials")
project = relationship("Project", back_populates="deployment_credentials")
```

### User vs Project Credentials

**User-level credentials** (`project_id=NULL`):
- Default credentials for all projects
- Used when no project-specific override exists
- Example: User's Vercel account token

**Project-level credentials** (`project_id` set):
- Override user defaults for specific project
- Example: Different Vercel team for one project

### Common Queries

**Get user's default Vercel credential**:
```python
result = await db.execute(
    select(DeploymentCredential)
    .where(DeploymentCredential.user_id == user.id)
    .where(DeploymentCredential.provider == "vercel")
    .where(DeploymentCredential.project_id.is_(None))
)
cred = result.scalar_one_or_none()
```

**Get project-specific credential (with fallback to user default)**:
```python
# Try project-specific first
result = await db.execute(
    select(DeploymentCredential)
    .where(DeploymentCredential.project_id == project.id)
    .where(DeploymentCredential.provider == "vercel")
)
cred = result.scalar_one_or_none()

if not cred:
    # Fall back to user default
    result = await db.execute(
        select(DeploymentCredential)
        .where(DeploymentCredential.user_id == user.id)
        .where(DeploymentCredential.provider == "vercel")
        .where(DeploymentCredential.project_id.is_(None))
    )
    cred = result.scalar_one_or_none()
```

**Store credential**:
```python
from app.services.encryption import encrypt_token

cred = DeploymentCredential(
    user_id=user.id,
    project_id=None,  # User default
    provider="vercel",
    access_token_encrypted=encrypt_token(vercel_token),
    provider_metadata={"team_id": "team_xxx"}
)
db.add(cred)
await db.commit()
```

**Use credential for deployment**:
```python
from app.services.encryption import decrypt_token

# Get credential
cred = await get_credential(user.id, project.id, "vercel")

# Decrypt token
token = decrypt_token(cred.access_token_encrypted)

# Use token for Vercel API
vercel_client = VercelClient(token)
deployment = await vercel_client.deploy(project_path)
```

### Security Notes

- All credentials MUST be encrypted before storing
- Use Fernet symmetric encryption with a strong key
- Encryption key stored in environment variable (`ENCRYPTION_KEY`)
- Credentials decrypted only when needed (deployment operations)
- Never log or expose decrypted credentials

---

## UserAPIKey Model

Stores user API keys for various providers (OpenAI, Anthropic, OpenRouter, etc.).

### Schema

```python
class UserAPIKey(Base):
    __tablename__ = "user_api_keys"

    # Identity
    id: UUID
    user_id: UUID               # Foreign key to User
    provider: str               # openrouter, anthropic, openai, google, github
    auth_type: str              # api_key, oauth_token, bearer_token, personal_access_token
    key_name: str               # Optional user-friendly name

    # Encrypted key
    encrypted_value: str        # The actual key/token (encrypted)

    # Provider metadata (JSON)
    provider_metadata: JSON     # Refresh tokens, scopes, etc.

    # Status
    is_active: bool
    expires_at: datetime
    last_used_at: datetime

    # Timestamps
    created_at: datetime
    updated_at: datetime
```

### Key Relationships

```python
user = relationship("User", back_populates="api_keys")
```

### Common Queries

**Store OpenAI API key**:
```python
from app.services.encryption import encrypt_token

api_key = UserAPIKey(
    user_id=user.id,
    provider="openai",
    auth_type="api_key",
    key_name="Production Key",
    encrypted_value=encrypt_token(openai_api_key),
    is_active=True
)
db.add(api_key)
await db.commit()
```

**Get active API key**:
```python
result = await db.execute(
    select(UserAPIKey)
    .where(UserAPIKey.user_id == user.id)
    .where(UserAPIKey.provider == "openai")
    .where(UserAPIKey.is_active == True)
)
api_key = result.scalar_one_or_none()
```

**Update last used timestamp**:
```python
api_key.last_used_at = datetime.utcnow()
await db.commit()
```

---

## Summary

The authentication and credentials models provide:

- **User**: FastAPI-Users compatible authentication with email/password and OAuth
- **OAuthAccount**: Link multiple OAuth providers (Google, GitHub) to one user
- **AccessToken**: Stateful Bearer token authentication (alternative to JWT)
- **GitProviderCredential**: Unified OAuth credentials for GitHub, GitLab, Bitbucket
- **GitRepository**: Git repository connections for projects
- **DeploymentCredential**: Encrypted API tokens for Vercel, Netlify, Cloudflare, etc.
- **UserAPIKey**: User-provided API keys for OpenAI, Anthropic, etc.

Security best practices:
- All OAuth tokens and API keys must be encrypted before storage
- Use Fernet symmetric encryption with strong key from environment
- Decrypt only when needed (during API calls)
- Never log or expose decrypted credentials
- Implement token refresh for expired OAuth tokens
- Use unique constraint to prevent duplicate credentials
