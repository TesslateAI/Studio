# Authentication Pages

## Login (`Login.tsx`)

**File**: `app/src/pages/Login.tsx`
**Route**: `/login`
**Layout**: Split-screen (form left, gradient animation right)

### Purpose
User authentication via email/password (with mandatory email 2FA) or OAuth providers.

### Features
- **Email/Password Login**: Credentials → email 2FA verification → JWT token
- **Email 2FA**: Mandatory 6-digit code sent via email after credential validation
- **OAuth Login**: Google, GitHub (bypasses 2FA)
- **Forgot Password**: Link to `/forgot-password`
- **Register Link**: Navigate to registration

### State
```typescript
const [email, setEmail] = useState('');
const [password, setPassword] = useState('');
const [loading, setLoading] = useState(false);
const [error, setError] = useState<string | null>(null);

// 2FA state
const [twoFaRequired, setTwoFaRequired] = useState(false);
const [tempToken, setTempToken] = useState('');
const [otpCode, setOtpCode] = useState(['', '', '', '', '', '']);
const [resendCooldown, setResendCooldown] = useState(0);
```

### Email/Password Login with 2FA
```typescript
const handleLogin = async (e: React.FormEvent) => {
  e.preventDefault();
  setLoading(true);
  setError(null);

  try {
    const response = await authApi.login(email, password);

    if (response.requires_2fa) {
      // Step 1: Show 2FA input
      setTwoFaRequired(true);
      setTempToken(response.temp_token);
      setResendCooldown(60);
    }
  } catch (err) {
    setError(error.response?.data?.detail || 'Invalid credentials');
  } finally {
    setLoading(false);
  }
};

const handleVerify2fa = async () => {
  const code = otpCode.join('');
  if (code.length !== 6) return;

  setLoading(true);
  try {
    const response = await authApi.verify2fa(tempToken, code);
    localStorage.setItem('token', response.access_token);
    await checkAuth({ force: true }); // Update AuthContext
    navigate('/dashboard');
  } catch (err) {
    setError('Invalid or expired code');
  } finally {
    setLoading(false);
  }
};
```

### 2FA OTP Input
The 2FA screen shows 6 individual digit input boxes with:
- **Auto-advance**: Focus moves to next input after entering a digit
- **Backspace handling**: Moves focus to previous input
- **Paste support**: Distributes pasted digits across inputs
- **Resend button**: 60-second cooldown timer
- **Back button**: Returns to credentials form

### OAuth Login
```typescript
const handleOAuthLogin = (provider: 'google' | 'github') => {
  const authUrl = `${API_URL}/api/auth/${provider}/authorize`;
  window.location.href = authUrl;
};
```

**Note**: OAuth logins completely bypass 2FA. The OAuth provider handles authentication.

---

## Forgot Password (`ForgotPassword.tsx`)

**File**: `app/src/pages/ForgotPassword.tsx`
**Route**: `/forgot-password`
**Layout**: Split-screen (form left, gradient animation right)

### Purpose
Start the password reset flow by submitting email address.

### Features
- **Email input**: Enter email to receive reset link
- **Success state**: Shows "Check your email" confirmation
- **Privacy**: Always shows success regardless of whether email exists (prevents user enumeration)
- **Back to login**: Link to return to `/login`

### State
```typescript
const [email, setEmail] = useState('');
const [loading, setLoading] = useState(false);
const [sent, setSent] = useState(false);
const [error, setError] = useState<string | null>(null);
```

### Flow
```typescript
const handleSubmit = async (e: React.FormEvent) => {
  e.preventDefault();
  setLoading(true);
  setError(null);

  try {
    await authApi.forgotPassword(email);
    setSent(true); // Shows success UI
  } catch (err) {
    // Still show success to prevent email enumeration
    setSent(true);
  } finally {
    setLoading(false);
  }
};
```

### UI States
- **Default**: Email input form with submit button
- **Success**: "Check your email" message with instructions

---

## Reset Password (`ResetPassword.tsx`)

**File**: `app/src/pages/ResetPassword.tsx`
**Route**: `/reset-password`
**Layout**: Split-screen (form left, gradient animation right)

### Purpose
Complete the password reset flow using the token from the email link.

### Features
- **Token validation**: Reads `?token=` from URL query params
- **Password input**: New password (min 6 chars, max 72 chars)
- **Confirm password**: Must match
- **Real-time validation**: Password match checking
- **Error handling**: Invalid/expired token states
- **Success redirect**: Redirects to `/login` after successful reset

### State
```typescript
const [password, setPassword] = useState('');
const [confirmPassword, setConfirmPassword] = useState('');
const [loading, setLoading] = useState(false);
const [error, setError] = useState<string | null>(null);
const [success, setSuccess] = useState(false);
```

### Flow
```typescript
const handleSubmit = async (e: React.FormEvent) => {
  e.preventDefault();

  if (password !== confirmPassword) {
    setError('Passwords do not match');
    return;
  }

  setLoading(true);
  try {
    await authApi.resetPassword(token, password);
    setSuccess(true);
    toast.success('Password reset successfully! Please sign in.');
    setTimeout(() => navigate('/login'), 2000);
  } catch (err) {
    setError('Invalid or expired reset link');
  } finally {
    setLoading(false);
  }
};
```

### Edge Cases
- **Missing token**: Shows "Invalid reset link" with link to `/forgot-password`
- **Expired token**: Shows error from backend (`RESET_PASSWORD_BAD_TOKEN`)
- **Success**: Shows success message, auto-redirects to `/login`

---

## Register (`Register.tsx`)

**File**: `app/src/pages/Register.tsx`
**Route**: `/register`
**Layout**: Split-screen (form left, gradient animation right)

### Purpose
Create new user account.

### Features
- **Email/Password Registration**: Create account with name, username, email, password
- **OAuth Registration**: Google, GitHub
- **Referral Code**: Track referrals
- **Password validation**: Min 6 chars, must confirm match

### State
```typescript
const [formData, setFormData] = useState({
  name: '',
  username: '',
  email: '',
  password: '',
  confirmPassword: '',
});
const [loading, setLoading] = useState(false);
const [errors, setErrors] = useState<Record<string, string>>({});
```

---

## OAuth Login Callback (`OAuthLoginCallback.tsx`)

**File**: `app/src/pages/OAuthLoginCallback.tsx`
**Route**: `/oauth/callback`
**Layout**: Minimal (loading spinner)

### Purpose
Handle OAuth provider redirects and establish session. OAuth users bypass 2FA entirely.

### Features
- **Token Exchange**: Exchange OAuth code for JWT
- **Cookie Session**: Set httpOnly cookie for OAuth users
- **Error Handling**: Display OAuth errors
- **Referral Tracking**: Apply referral code if present

### State
```typescript
const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading');
const [error, setError] = useState<string | null>(null);
```

---

## GitHub OAuth Callback (`AuthCallback.tsx`)

**File**: `app/src/pages/AuthCallback.tsx`
**Route**: `/auth/github/callback`
**Layout**: Minimal (loading spinner)

### Purpose
Handle GitHub OAuth for **git operations** (not login). Stores GitHub token for commit/push/pull.

**Note**: This is different from GitHub login. This connects GitHub for repository access.

---

## Logout (`Logout.tsx`)

**File**: `app/src/pages/Logout.tsx`
**Route**: `/logout`
**Layout**: None (immediate redirect)

### Purpose
Clear authentication and redirect to login.

### Implementation
```typescript
export default function Logout() {
  useEffect(() => {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    localStorage.removeItem('referral_code');
    window.location.href = '/login';
  }, []);

  return null;
}
```

---

## SecuritySettings (`SecuritySettings.tsx`)

**File**: `app/src/pages/settings/SecuritySettings.tsx`
**Route**: `/settings/security`
**Layout**: SettingsLayout

### Purpose
Security settings page showing 2FA status and password management.

### Features
- **2FA Status Display**: Shows "Email verification is active" badge
- **Change Password**: Sends password reset email to user's own email (via forgot-password flow)
- **Future**: Session management, TOTP 2FA toggle

---

## Authentication Flow Diagrams

### Email/Password Login with 2FA
```
User submits email/password
  ↓
POST /api/auth/login (form-encoded)
  ↓
Backend validates credentials
  ↓ (if valid)
Backend generates 6-digit code, stores hash in EmailVerificationCode
  ↓
Backend returns { requires_2fa: true, temp_token: "...", method: "email" }
  ↓ (async, non-blocking)
Email sent with 6-digit code (or logged to console if SMTP not configured)
  ↓
Frontend shows 2FA code input (6 digit boxes)
  ↓
User enters 6-digit code
  ↓
POST /api/auth/2fa/verify { temp_token, code }
  ↓
Backend validates temp_token signature + expiry
  ↓
Backend compares code against hash (max 5 attempts)
  ↓ (if valid)
Backend issues JWT access_token
  ↓
Frontend stores token, calls checkAuth({ force: true })
  ↓
Navigate to /dashboard
```

### Password Reset Flow
```
User clicks "Forgot password?" on login page
  ↓
Navigate to /forgot-password
  ↓
User enters email, clicks "Send reset link"
  ↓
POST /api/auth/forgot-password { email }
  ↓
Backend generates signed reset token (1 hour expiry)
  ↓ (async, non-blocking)
Email sent with reset URL (or logged to console)
  ↓
Response always shows success (prevents email enumeration)
  ↓
User clicks link in email
  ↓
Navigate to /reset-password?token=...
  ↓
User enters new password + confirmation
  ↓
POST /api/auth/reset-password { token, password }
  ↓
Backend validates token signature + expiry
  ↓ (if valid)
Backend updates user password hash
  ↓
Frontend shows success, redirects to /login
```

### OAuth Login Flow (No 2FA)
```
User clicks "Login with Google/GitHub"
  ↓
Frontend redirects to GET /api/auth/{provider}/authorize
  ↓
Backend redirects to OAuth consent screen
  ↓
User grants permission
  ↓
Provider redirects to /api/auth/{provider}/callback?code=...
  ↓
Backend exchanges code for user info, creates/finds user
  ↓
Backend sets httpOnly cookie (bypasses 2FA entirely)
  ↓
Backend redirects to /oauth/callback
  ↓
Frontend verifies cookie auth with GET /api/users/me
  ↓
Navigate to /dashboard
```

### GitHub Git OAuth Flow
```
User clicks "Connect GitHub" in settings
  ↓
Frontend opens popup: /api/auth/github/authorize?scope=repo
  ↓
GitHub OAuth consent screen
  ↓
User grants permission
  ↓
GitHub redirects to /api/auth/github/callback?code=...
  ↓
Backend exchanges code for GitHub token
  ↓
Backend stores token in DeploymentCredential
  ↓
Backend redirects popup to /auth/github/callback
  ↓
Frontend verifies connection
  ↓
Popup posts message to parent window
  ↓
Popup closes, parent refreshes credentials
```

## API Endpoints

```typescript
// Login (returns 2FA challenge, NOT a JWT directly)
POST /api/auth/login
Content-Type: application/x-www-form-urlencoded
{ username: string, password: string }
→ { requires_2fa: true, temp_token: string, method: "email" }

// Verify 2FA code (returns JWT)
POST /api/auth/2fa/verify
{ temp_token: string, code: string }
→ { access_token: string, token_type: "bearer" }

// Resend 2FA code
POST /api/auth/2fa/resend
{ temp_token: string }
→ { message: "Code resent" }

// Register
POST /api/auth/register
{ name: string, email: string, password: string, username?: string, referral_code?: string }
→ { access_token: string, token_type: 'bearer', user: User }

// OAuth authorize (redirects)
GET /api/auth/{provider}/authorize
→ Redirects to provider consent screen

// OAuth callback (sets cookie, redirects)
GET /api/auth/{provider}/callback?code=...
→ Sets httpOnly cookie, redirects to /oauth/callback

// Get current user (requires auth)
GET /api/users/me
→ { id, name, email, ... }

// Logout (clears cookie)
POST /api/auth/logout
→ Clears httpOnly cookie

// Forgot password
POST /api/auth/forgot-password
{ email: string }
→ Always returns success (202)

// Reset password
POST /api/auth/reset-password
{ token: string, password: string }
→ Success or RESET_PASSWORD_BAD_TOKEN error

// Apply referral code
POST /api/auth/referral
{ code: string }
→ { success: true, credits_earned: number }
```

## Backend Services

### Two-Factor Authentication (`orchestrator/app/services/two_fa_service.py`)

| Function | Purpose |
|----------|---------|
| `generate_code()` | Cryptographically-secure 6-digit code via `secrets.randbelow()` |
| `create_verification_code()` | Invalidates old codes, hashes new code, stores in DB |
| `verify_code()` | Checks expiry, attempts, hash match; marks used on success |
| `create_temp_token()` | Signs user_id with itsdangerous (salt: "2fa-temp-token") |
| `validate_temp_token()` | Validates signature + expiry, returns user_id or None |
| `cleanup_expired_codes()` | Deletes codes older than 1 hour |

### Email Service (`orchestrator/app/services/email_service.py`)

| Method | Purpose |
|--------|---------|
| `send_2fa_code(to_email, code)` | Sends styled HTML email with 6-digit code |
| `send_password_reset(to_email, reset_url)` | Sends reset link with button |
| `_send(to_email, subject, plain, html)` | Internal SMTP sender via aiosmtplib |

**Dev mode fallback**: If SMTP is not configured, all emails are logged to console:
```
[EMAIL-DEV] 2FA code for user@example.com: 123456 (SMTP not configured, printing to console)
```

## Security

### Code Security
- 6-digit codes with 1M possibilities
- Max 5 attempts per code (brute force protection)
- 10-minute expiry
- Argon2 hash stored in DB (never plaintext)

### Token Security
- Temporary tokens are **signed** (itsdangerous) but **NOT JWTs**
- Cannot be used to access API endpoints
- 10-minute expiry, different salt from JWT tokens

### Email Privacy
- Password reset always returns success regardless of email existence
- Prevents user enumeration attacks

### Non-Blocking
- All email sending happens via `asyncio.create_task()` (fire-and-forget)
- Login/reset responses are not delayed by email delivery

## Configuration

### SMTP Settings (`.env`)
```bash
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=your_smtp_username
SMTP_PASSWORD=your_smtp_password
SMTP_USE_TLS=true
SMTP_SENDER_EMAIL=noreply@yourdomain.com
```

### 2FA Settings (`config.py`)
```python
two_fa_code_length: int = 6
two_fa_code_expiry_seconds: int = 600      # 10 minutes
two_fa_max_attempts: int = 5
two_fa_temp_token_expiry_seconds: int = 600
```

## Troubleshooting

**Issue**: OAuth redirect loop
- Check callback URL matches backend config
- Verify cookie domain settings
- Clear browser cookies

**Issue**: 401 after login
- Check token is stored correctly
- Verify Authorization header is set
- Check token expiration

**Issue**: 2FA code not received
- Check SMTP configuration in `.env`
- If SMTP not configured, check backend console logs for `[EMAIL-DEV]` messages
- Check spam/junk folder

**Issue**: 2FA code expired
- Codes expire after 10 minutes
- Click "Resend code" to get a new one (60s cooldown)
- Previous codes are automatically invalidated

**Issue**: Redirect loop after 2FA verification
- Ensure `checkAuth({ force: true })` is called after storing the JWT
- This was fixed in commit `308dbbc`

**Issue**: Password reset link expired
- Reset tokens expire after 1 hour
- Request a new one from `/forgot-password`

**Issue**: GitHub OAuth not working
- Verify GitHub app client ID/secret
- Check redirect URI is whitelisted
- Ensure repo scope is requested

**Issue**: CSRF token errors (OAuth)
- Ensure withCredentials: true on axios
- Check X-CSRF-Token header is sent
- Verify CSRF token endpoint is accessible
