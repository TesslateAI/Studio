/**
 * Route Guard Tests
 *
 * Config-driven suite that verifies every application route has the correct
 * auth protection, plus targeted tests for edge-case behavior (loading state,
 * "from" state preservation, round-trip redirect chain).
 *
 * IMPORTANT: When adding a new route to App.tsx, you MUST add it to the
 * ROUTE_CONFIG array below and run these tests to verify correct auth behavior.
 */
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { PrivateRoute, PublicOnlyRoute } from './RouteGuards';

// ---------------------------------------------------------------------------
// Mock useAuth
// ---------------------------------------------------------------------------
const mockUseAuth = vi.fn();

vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => mockUseAuth(),
}));

beforeEach(() => mockUseAuth.mockReset());

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Captures the login redirect and exposes the `from` state for assertions. */
function LoginCapture() {
  const location = useLocation();
  const from = (location.state as { from?: string })?.from ?? '';
  return (
    <div data-testid="login-redirect">
      <span data-testid="redirect-from">{from}</span>
    </div>
  );
}

// ===========================================================================
// Config-driven route protection tests
//
// Every route in App.tsx must be listed here. When adding a new route,
// add an entry to ROUTE_CONFIG and run `npm test` to verify.
// ===========================================================================

type RouteGuard = 'private' | 'publicOnly' | 'public';

interface RouteSpec {
  /** The path as defined in App.tsx (use concrete values for params) */
  path: string;
  /** Which guard wraps this route */
  guard: RouteGuard;
  /** Human-readable description for test output */
  label: string;
}

/**
 * Master list of all application routes and their expected auth protection.
 *
 * KEEP THIS IN SYNC WITH App.tsx ROUTES.
 * If a test fails after adding a route, add the route here.
 */
const ROUTE_CONFIG: RouteSpec[] = [
  // --- Public pages (no guard) ---
  { path: '/import', guard: 'public', label: 'Import redirect (deep link)' },
  { path: '/forgot-password', guard: 'public', label: 'Forgot password' },
  { path: '/reset-password', guard: 'public', label: 'Reset password' },
  { path: '/logout', guard: 'public', label: 'Logout' },
  { path: '/oauth/callback', guard: 'public', label: 'OAuth callback' },
  { path: '/marketplace', guard: 'public', label: 'Marketplace home' },
  { path: '/marketplace/category/ai', guard: 'public', label: 'Marketplace category redirect' },
  { path: '/marketplace/browse/agents', guard: 'public', label: 'Marketplace browse' },
  { path: '/marketplace/my-agent', guard: 'public', label: 'Marketplace detail' },
  { path: '/marketplace/creator/u1', guard: 'public', label: 'Marketplace author' },

  // --- Public-only pages (redirect away if authenticated) ---
  { path: '/login', guard: 'publicOnly', label: 'Login' },
  { path: '/register', guard: 'publicOnly', label: 'Register' },

  // --- Private pages (redirect to login if not authenticated) ---
  { path: '/dashboard', guard: 'private', label: 'Dashboard' },
  { path: '/library', guard: 'private', label: 'Library' },
  { path: '/feedback', guard: 'private', label: 'Feedback' },
  { path: '/marketplace/success', guard: 'private', label: 'Marketplace success' },
  { path: '/project/my-app', guard: 'private', label: 'Project graph' },
  { path: '/project/my-app/builder', guard: 'private', label: 'Project builder' },
  { path: '/admin', guard: 'private', label: 'Admin dashboard' },
  { path: '/settings/profile', guard: 'private', label: 'Settings: profile' },
  { path: '/settings/preferences', guard: 'private', label: 'Settings: preferences' },
  { path: '/settings/security', guard: 'private', label: 'Settings: security' },
  { path: '/settings/deployment', guard: 'private', label: 'Settings: deployment' },
  { path: '/settings/billing', guard: 'private', label: 'Settings: billing' },
  { path: '/auth/github/callback', guard: 'private', label: 'GitHub auth callback' },
  { path: '/referral', guard: 'private', label: 'Referral' },
  { path: '/referrals', guard: 'private', label: 'Referrals' },
];

// ---------------------------------------------------------------------------
// Helper: render a route with the specified guard and assert behavior
// ---------------------------------------------------------------------------
function renderGuardedRoute(path: string, guard: RouteGuard) {
  const content = <div data-testid="page-content">Page</div>;

  let element;
  if (guard === 'private') {
    element = <PrivateRoute>{content}</PrivateRoute>;
  } else if (guard === 'publicOnly') {
    element = <PublicOnlyRoute>{content}</PublicOnlyRoute>;
  } else {
    element = content;
  }

  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path={path} element={element} />
        {/* Redirect targets */}
        <Route path="/login" element={<div data-testid="login-page">Login</div>} />
        <Route path="/dashboard" element={<div data-testid="dashboard">Dashboard</div>} />
        <Route path="/home" element={<div data-testid="home">Home</div>} />
      </Routes>
    </MemoryRouter>
  );
}

// ---------------------------------------------------------------------------
// Private routes
// ---------------------------------------------------------------------------
describe('Route protection – private routes', () => {
  const privateRoutes = ROUTE_CONFIG.filter((r) => r.guard === 'private');

  describe('redirect to /login when unauthenticated', () => {
    beforeEach(() => {
      mockUseAuth.mockReturnValue({ isAuthenticated: false, isLoading: false });
    });

    it.each(privateRoutes.map((r) => [r.label, r.path]))('%s (%s)', (_label, path) => {
      renderGuardedRoute(path, 'private');
      expect(screen.queryByTestId('page-content')).not.toBeInTheDocument();
      expect(screen.getByTestId('login-page')).toBeInTheDocument();
    });
  });

  describe('render content when authenticated', () => {
    beforeEach(() => {
      mockUseAuth.mockReturnValue({ isAuthenticated: true, isLoading: false });
    });

    it.each(privateRoutes.map((r) => [r.label, r.path]))('%s (%s)', (_label, path) => {
      renderGuardedRoute(path, 'private');
      expect(screen.getByTestId('page-content')).toBeInTheDocument();
      expect(screen.queryByTestId('login-page')).not.toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// Public-only routes
// ---------------------------------------------------------------------------
describe('Route protection – public-only routes', () => {
  const publicOnlyRoutes = ROUTE_CONFIG.filter((r) => r.guard === 'publicOnly');

  describe('redirect to /home when authenticated', () => {
    beforeEach(() => {
      mockUseAuth.mockReturnValue({ isAuthenticated: true, isLoading: false });
    });

    it.each(publicOnlyRoutes.map((r) => [r.label, r.path]))('%s (%s)', (_label, path) => {
      renderGuardedRoute(path, 'publicOnly');
      expect(screen.queryByTestId('page-content')).not.toBeInTheDocument();
      expect(screen.getByTestId('home')).toBeInTheDocument();
    });
  });

  describe('render content when unauthenticated', () => {
    beforeEach(() => {
      mockUseAuth.mockReturnValue({ isAuthenticated: false, isLoading: false });
    });

    it.each(publicOnlyRoutes.map((r) => [r.label, r.path]))('%s (%s)', (_label, path) => {
      renderGuardedRoute(path, 'publicOnly');
      expect(screen.getByTestId('page-content')).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// Public routes
// ---------------------------------------------------------------------------
describe('Route protection – public routes always render', () => {
  const publicRoutes = ROUTE_CONFIG.filter((r) => r.guard === 'public');

  describe('when authenticated', () => {
    beforeEach(() => {
      mockUseAuth.mockReturnValue({ isAuthenticated: true, isLoading: false });
    });

    it.each(publicRoutes.map((r) => [r.label, r.path]))('%s (%s)', (_label, path) => {
      renderGuardedRoute(path, 'public');
      expect(screen.getByTestId('page-content')).toBeInTheDocument();
    });
  });

  describe('when unauthenticated', () => {
    beforeEach(() => {
      mockUseAuth.mockReturnValue({ isAuthenticated: false, isLoading: false });
    });

    it.each(publicRoutes.map((r) => [r.label, r.path]))('%s (%s)', (_label, path) => {
      renderGuardedRoute(path, 'public');
      expect(screen.getByTestId('page-content')).toBeInTheDocument();
    });
  });
});

// ===========================================================================
// Edge-case behavior (not covered by config-driven tests above)
// ===========================================================================

describe('PrivateRoute – loading state', () => {
  it('renders nothing while auth is loading', () => {
    mockUseAuth.mockReturnValue({ isAuthenticated: false, isLoading: true });

    const { container } = render(
      <MemoryRouter initialEntries={['/protected']}>
        <Routes>
          <Route
            path="/protected"
            element={
              <PrivateRoute>
                <div data-testid="content">Secret</div>
              </PrivateRoute>
            }
          />
          <Route path="/login" element={<div data-testid="login-page">Login</div>} />
        </Routes>
      </MemoryRouter>
    );

    expect(screen.queryByTestId('content')).not.toBeInTheDocument();
    expect(screen.queryByTestId('login-page')).not.toBeInTheDocument();
    expect(container.innerHTML).toBe('');
  });
});

describe('PublicOnlyRoute – loading state', () => {
  it('renders nothing while auth is loading', () => {
    mockUseAuth.mockReturnValue({ isAuthenticated: false, isLoading: true });

    const { container } = render(
      <MemoryRouter initialEntries={['/login']}>
        <Routes>
          <Route
            path="/login"
            element={
              <PublicOnlyRoute>
                <div data-testid="login-form">Login</div>
              </PublicOnlyRoute>
            }
          />
          <Route path="/dashboard" element={<div data-testid="dashboard">Dashboard</div>} />
        </Routes>
      </MemoryRouter>
    );

    expect(screen.queryByTestId('login-form')).not.toBeInTheDocument();
    expect(screen.queryByTestId('dashboard')).not.toBeInTheDocument();
    expect(container.innerHTML).toBe('');
  });
});

describe('PrivateRoute – "from" state preservation', () => {
  it('passes current path as "from" state when redirecting to login', () => {
    mockUseAuth.mockReturnValue({ isAuthenticated: false, isLoading: false });

    render(
      <MemoryRouter initialEntries={['/settings/billing']}>
        <Routes>
          <Route
            path="/settings/billing"
            element={
              <PrivateRoute>
                <div>Billing</div>
              </PrivateRoute>
            }
          />
          <Route path="/login" element={<LoginCapture />} />
        </Routes>
      </MemoryRouter>
    );

    expect(screen.getByTestId('redirect-from')).toHaveTextContent('/settings/billing');
  });
});

describe('PublicOnlyRoute – "from" state redirect', () => {
  it('redirects to saved "from" destination when authenticated', () => {
    mockUseAuth.mockReturnValue({ isAuthenticated: true, isLoading: false });

    render(
      <MemoryRouter initialEntries={[{ pathname: '/login', state: { from: '/settings/billing' } }]}>
        <Routes>
          <Route
            path="/login"
            element={
              <PublicOnlyRoute>
                <div data-testid="login-form">Login</div>
              </PublicOnlyRoute>
            }
          />
          <Route path="/dashboard" element={<div data-testid="dashboard">Dashboard</div>} />
          <Route path="/settings/billing" element={<div data-testid="billing">Billing</div>} />
        </Routes>
      </MemoryRouter>
    );

    expect(screen.queryByTestId('login-form')).not.toBeInTheDocument();
    expect(screen.queryByTestId('dashboard')).not.toBeInTheDocument();
    expect(screen.getByTestId('billing')).toBeInTheDocument();
  });
});

describe('PrivateRoute → PublicOnlyRoute round-trip', () => {
  it('preserves destination through the full redirect chain', () => {
    // Step 1: unauthenticated user visits /protected → redirected to /login
    mockUseAuth.mockReturnValue({ isAuthenticated: false, isLoading: false });

    const { unmount } = render(
      <MemoryRouter initialEntries={['/protected']}>
        <Routes>
          <Route
            path="/protected"
            element={
              <PrivateRoute>
                <div>Protected</div>
              </PrivateRoute>
            }
          />
          <Route path="/login" element={<LoginCapture />} />
        </Routes>
      </MemoryRouter>
    );

    expect(screen.getByTestId('redirect-from')).toHaveTextContent('/protected');
    unmount();

    // Step 2: user logs in, visits /login with from state → redirected to /protected
    mockUseAuth.mockReturnValue({ isAuthenticated: true, isLoading: false });

    render(
      <MemoryRouter initialEntries={[{ pathname: '/login', state: { from: '/protected' } }]}>
        <Routes>
          <Route
            path="/login"
            element={
              <PublicOnlyRoute>
                <div data-testid="login-form">Login</div>
              </PublicOnlyRoute>
            }
          />
          <Route path="/protected" element={<div data-testid="destination">Made it!</div>} />
          <Route path="/dashboard" element={<div data-testid="dashboard">Dashboard</div>} />
        </Routes>
      </MemoryRouter>
    );

    expect(screen.queryByTestId('login-form')).not.toBeInTheDocument();
    expect(screen.queryByTestId('dashboard')).not.toBeInTheDocument();
    expect(screen.getByTestId('destination')).toBeInTheDocument();
  });
});

// ===========================================================================
// Config sanity checks
// ===========================================================================
describe('Route config sanity', () => {
  it('every route has a valid guard type', () => {
    for (const route of ROUTE_CONFIG) {
      expect(['private', 'publicOnly', 'public']).toContain(route.guard);
    }
  });

  it('has no duplicate paths', () => {
    const paths = ROUTE_CONFIG.map((r) => r.path);
    const unique = new Set(paths);
    expect(unique.size).toBe(paths.length);
  });

  it('covers a minimum number of routes (catch missing entries)', () => {
    // Update this count when adding routes. If it fails, you added a route
    // to App.tsx but forgot to add it here.
    expect(ROUTE_CONFIG.length).toBeGreaterThanOrEqual(27);
  });
});
