# Authentication Pages

## Login (`Login.tsx`)

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/pages/Login.tsx`
**Route**: `/login`
**Layout**: Minimal (centered form)

### Purpose
User authentication via email/password or OAuth providers.

### Features
- **Email/Password Login**: JWT token authentication
- **OAuth Login**: Google, GitHub, GitLab, Bitbucket
- **Remember Me**: Persistent login
- **Forgot Password**: Password reset link
- **Register Link**: Navigate to registration

### State
```typescript
const [email, setEmail] = useState('');
const [password, setPassword] = useState('');
const [rememberMe, setRememberMe] = useState(false);
const [loading, setLoading] = useState(false);
const [error, setError] = useState<string | null>(null);
```

### Email/Password Login
```typescript
const handleLogin = async (e: React.FormEvent) => {
  e.preventDefault();
  setLoading(true);
  setError(null);

  try {
    const response = await authApi.login(email, password);

    // Store JWT token
    localStorage.setItem('token', response.access_token);

    // Store user info
    if (response.user) {
      localStorage.setItem('user', JSON.stringify(response.user));
    }

    toast.success('Logged in successfully');
    navigate('/dashboard');
  } catch (err) {
    const error = err as { response?: { data?: { detail?: string } } };
    setError(error.response?.data?.detail || 'Invalid credentials');
  } finally {
    setLoading(false);
  }
};
```

### OAuth Login
```typescript
const handleOAuthLogin = (provider: 'google' | 'github' | 'gitlab' | 'bitbucket') => {
  // Store referral code if present
  const referralCode = searchParams.get('ref');
  if (referralCode) {
    localStorage.setItem('referral_code', referralCode);
  }

  // Redirect to OAuth provider
  const authUrl = `${API_URL}/api/auth/${provider}/authorize`;
  window.location.href = authUrl;
};
```

### Form Layout
```typescript
<form onSubmit={handleLogin} className="login-form">
  <h1>Welcome Back</h1>

  {error && (
    <div className="error-banner">
      {error}
    </div>
  )}

  <div className="form-group">
    <label htmlFor="email">Email</label>
    <input
      id="email"
      type="email"
      value={email}
      onChange={(e) => setEmail(e.target.value)}
      required
      autoFocus
    />
  </div>

  <div className="form-group">
    <label htmlFor="password">Password</label>
    <input
      id="password"
      type="password"
      value={password}
      onChange={(e) => setPassword(e.target.value)}
      required
    />
  </div>

  <div className="form-options">
    <label>
      <input
        type="checkbox"
        checked={rememberMe}
        onChange={(e) => setRememberMe(e.target.checked)}
      />
      Remember me
    </label>

    <Link to="/forgot-password">Forgot password?</Link>
  </div>

  <button type="submit" disabled={loading}>
    {loading ? 'Logging in...' : 'Log In'}
  </button>

  <div className="oauth-divider">
    <span>or continue with</span>
  </div>

  <div className="oauth-buttons">
    <button type="button" onClick={() => handleOAuthLogin('google')}>
      <GoogleIcon /> Google
    </button>
    <button type="button" onClick={() => handleOAuthLogin('github')}>
      <GitHubIcon /> GitHub
    </button>
  </div>

  <p className="register-link">
    Don't have an account? <Link to="/register">Sign up</Link>
  </p>
</form>
```

---

## Register (`Register.tsx`)

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/pages/Register.tsx`
**Route**: `/register`
**Layout**: Minimal (centered form)

### Purpose
Create new user account.

### Features
- **Email/Password Registration**: Create JWT account
- **OAuth Registration**: Google, GitHub
- **Email Verification**: Send verification email
- **Referral Code**: Track referrals
- **Terms Acceptance**: Checkbox for ToS

### State
```typescript
const [formData, setFormData] = useState({
  name: '',
  username: '',
  email: '',
  password: '',
  confirmPassword: '',
});
const [acceptTerms, setAcceptTerms] = useState(false);
const [loading, setLoading] = useState(false);
const [errors, setErrors] = useState<Record<string, string>>({});
```

### Validation
```typescript
const validateForm = (): boolean => {
  const newErrors: Record<string, string> = {};

  if (!formData.name) {
    newErrors.name = 'Name is required';
  }

  if (!formData.email) {
    newErrors.email = 'Email is required';
  } else if (!/\S+@\S+\.\S+/.test(formData.email)) {
    newErrors.email = 'Email is invalid';
  }

  if (!formData.password) {
    newErrors.password = 'Password is required';
  } else if (formData.password.length < 8) {
    newErrors.password = 'Password must be at least 8 characters';
  }

  if (formData.password !== formData.confirmPassword) {
    newErrors.confirmPassword = 'Passwords do not match';
  }

  if (!acceptTerms) {
    newErrors.terms = 'You must accept the terms of service';
  }

  setErrors(newErrors);
  return Object.keys(newErrors).length === 0;
};
```

### Registration Flow
```typescript
const handleRegister = async (e: React.FormEvent) => {
  e.preventDefault();

  if (!validateForm()) {
    return;
  }

  setLoading(true);

  try {
    // Check for referral code
    const referralCode = searchParams.get('ref') || localStorage.getItem('referral_code');

    const response = await authApi.register({
      name: formData.name,
      username: formData.username || formData.email.split('@')[0],
      email: formData.email,
      password: formData.password,
      referral_code: referralCode || undefined,
    });

    // Store JWT token
    localStorage.setItem('token', response.access_token);

    // Clear referral code
    localStorage.removeItem('referral_code');

    toast.success('Account created! Please check your email to verify your account.');
    navigate('/dashboard');
  } catch (err) {
    const error = err as { response?: { data?: { detail?: string } } };
    setErrors({ submit: error.response?.data?.detail || 'Registration failed' });
  } finally {
    setLoading(false);
  }
};
```

---

## OAuth Login Callback (`OAuthLoginCallback.tsx`)

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/pages/OAuthLoginCallback.tsx`
**Route**: `/oauth/callback`
**Layout**: Minimal (loading spinner)

### Purpose
Handle OAuth provider redirects and establish session.

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

### Callback Flow
```typescript
useEffect(() => {
  handleCallback();
}, []);

const handleCallback = async () => {
  try {
    // Parse URL params
    const code = searchParams.get('code');
    const state = searchParams.get('state');
    const error = searchParams.get('error');

    if (error) {
      throw new Error(error);
    }

    if (!code) {
      throw new Error('No authorization code received');
    }

    // Exchange code for session (backend sets httpOnly cookie)
    // The current page URL already contains the code, so just verify auth
    const response = await axios.get(`${API_URL}/api/users/me`, {
      withCredentials: true,
    });

    if (response.status === 200) {
      setStatus('success');

      // Apply referral code if present
      const referralCode = localStorage.getItem('referral_code');
      if (referralCode) {
        try {
          await authApi.applyReferralCode(referralCode);
          localStorage.removeItem('referral_code');
        } catch (err) {
          console.error('Failed to apply referral code:', err);
        }
      }

      // Redirect to dashboard
      setTimeout(() => {
        navigate('/dashboard');
      }, 1000);
    } else {
      throw new Error('Authentication failed');
    }
  } catch (err) {
    console.error('OAuth callback error:', err);
    setStatus('error');
    setError(err instanceof Error ? err.message : 'Authentication failed');

    // Redirect to login after delay
    setTimeout(() => {
      navigate('/login');
    }, 3000);
  }
};
```

### UI States
```typescript
if (status === 'loading') {
  return (
    <div className="callback-page">
      <LoadingSpinner />
      <p>Completing sign in...</p>
    </div>
  );
}

if (status === 'error') {
  return (
    <div className="callback-page">
      <XCircle size={48} color="#ef4444" />
      <h2>Authentication Failed</h2>
      <p>{error}</p>
      <p>Redirecting to login...</p>
    </div>
  );
}

return (
  <div className="callback-page">
    <CheckCircle size={48} color="#10b981" />
    <h2>Success!</h2>
    <p>Redirecting to dashboard...</p>
  </div>
);
```

---

## GitHub OAuth Callback (`AuthCallback.tsx`)

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/pages/AuthCallback.tsx`
**Route**: `/auth/github/callback`
**Layout**: Minimal (loading spinner)

### Purpose
Handle GitHub OAuth for **git operations** (not login). Stores GitHub token for commit/push/pull.

**Note**: This is different from GitHub login. This connects GitHub for repository access.

### State
```typescript
const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading');
const [message, setMessage] = useState('Connecting GitHub...');
```

### Callback Flow
```typescript
useEffect(() => {
  handleGitHubConnect();
}, []);

const handleGitHubConnect = async () => {
  try {
    const code = searchParams.get('code');
    const state = searchParams.get('state');

    if (!code) {
      throw new Error('No authorization code');
    }

    // Exchange code for GitHub token (backend stores it)
    await githubApi.completeOAuth(code, state);

    setStatus('success');
    setMessage('GitHub connected successfully!');

    // Close popup window if opened from parent
    if (window.opener) {
      window.opener.postMessage({ type: 'github-connected' }, '*');
      window.close();
    } else {
      // Redirect to dashboard
      setTimeout(() => {
        navigate('/dashboard');
      }, 2000);
    }
  } catch (err) {
    setStatus('error');
    setMessage(err instanceof Error ? err.message : 'Failed to connect GitHub');

    setTimeout(() => {
      if (window.opener) {
        window.close();
      } else {
        navigate('/settings');
      }
    }, 3000);
  }
};
```

---

## Logout (`Logout.tsx`)

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/pages/Logout.tsx`
**Route**: `/logout`
**Layout**: None (immediate redirect)

### Purpose
Clear authentication and redirect to login.

### Implementation
```typescript
export default function Logout() {
  useEffect(() => {
    // Clear JWT token
    localStorage.removeItem('token');

    // Clear user data
    localStorage.removeItem('user');

    // Clear any other auth-related data
    localStorage.removeItem('referral_code');

    // For OAuth users, backend clears httpOnly cookie automatically
    // when they try to access protected routes

    // Redirect to login
    window.location.href = '/login';
  }, []);

  return null; // No UI, just redirect
}
```

---

## Authentication Flow Diagrams

### JWT Login Flow
```
User submits email/password
  ↓
POST /api/auth/login
  ↓
Backend validates credentials
  ↓
Backend returns { access_token, user }
  ↓
Frontend stores token in localStorage
  ↓
Frontend sets Authorization header for future requests
  ↓
Navigate to /dashboard
```

### OAuth Login Flow
```
User clicks "Login with Google"
  ↓
Frontend redirects to GET /api/auth/google/authorize
  ↓
Backend redirects to Google OAuth consent screen
  ↓
User grants permission
  ↓
Google redirects to /api/auth/google/callback?code=...
  ↓
Backend exchanges code for user info
  ↓
Backend creates/finds user
  ↓
Backend sets httpOnly cookie
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
// JWT Login
POST /api/auth/login
{ email: string, password: string }
→ { access_token: string, token_type: 'bearer', user: User }

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
→ Sends reset email

// Reset password
POST /api/auth/reset-password
{ token: string, password: string }
→ { success: true }

// Apply referral code
POST /api/auth/referral
{ code: string }
→ { success: true, credits_earned: number }
```

## Best Practices

### 1. Secure Token Storage
```typescript
// JWT token in localStorage (for regular login)
localStorage.setItem('token', token);

// OAuth uses httpOnly cookies (managed by backend)
// Frontend just checks auth with GET /api/users/me
```

### 2. Redirect After Login
```typescript
// Check for redirect param
const [searchParams] = useSearchParams();
const redirect = searchParams.get('redirect') || '/dashboard';

// After successful login
navigate(redirect);
```

### 3. Handle Expired Sessions
```typescript
// Axios interceptor (in lib/api.ts)
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token');
      if (window.location.pathname !== '/login') {
        window.location.href = `/login?redirect=${encodeURIComponent(window.location.pathname)}`;
      }
    }
    return Promise.reject(error);
  }
);
```

### 4. Remember Me
```typescript
// Store preference
if (rememberMe) {
  localStorage.setItem('remember_me', 'true');
} else {
  localStorage.setItem('remember_me', 'false');
}

// On app load, check if should auto-login
useEffect(() => {
  const rememberMe = localStorage.getItem('remember_me') === 'true';
  const token = localStorage.getItem('token');

  if (rememberMe && token) {
    // Token is still valid, continue session
  } else {
    // Clear token if remember me is off
    localStorage.removeItem('token');
  }
}, []);
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

**Issue**: GitHub OAuth not working
- Verify GitHub app client ID/secret
- Check redirect URI is whitelisted
- Ensure repo scope is requested

**Issue**: CSRF token errors (OAuth)
- Ensure withCredentials: true on axios
- Check X-CSRF-Token header is sent
- Verify CSRF token endpoint is accessible
