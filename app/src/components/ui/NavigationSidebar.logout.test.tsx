/**
 * NavigationSidebar logout tests
 *
 * Verifies the sidebar logout button delegates to AuthContext.logout()
 * rather than doing its own incomplete cleanup.
 */
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ---------------------------------------------------------------------------
// localStorage mock
// ---------------------------------------------------------------------------

const store: Record<string, string> = {};
const localStorageMock = {
  getItem: vi.fn((key: string) => store[key] ?? null),
  setItem: vi.fn((key: string, val: string) => {
    store[key] = val;
  }),
  removeItem: vi.fn((key: string) => {
    delete store[key];
  }),
  clear: vi.fn(() => {
    Object.keys(store).forEach((k) => delete store[k]);
  }),
  get length() {
    return Object.keys(store).length;
  },
  key: vi.fn((i: number) => Object.keys(store)[i] ?? null),
};
Object.defineProperty(window, 'localStorage', { value: localStorageMock, writable: true });

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockLogout = vi.fn().mockResolvedValue(undefined);
const mockNavigate = vi.fn();

vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 'u1', name: 'Test User', email: 'test@test.com', avatar_url: null },
    logout: mockLogout,
  }),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    useLocation: () => ({ pathname: '/dashboard' }),
  };
});

vi.mock('../../contexts/TeamContext', () => ({
  useTeam: () => ({
    activeTeam: { slug: 'personal', name: 'Personal', is_personal: true, subscription_tier: 'free' },
    teams: [{ slug: 'personal', name: 'Personal', is_personal: true, role: 'admin' }],
    switchTeam: vi.fn(),
    refreshTeams: vi.fn(),
    membership: { role: 'admin' },
    can: () => true,
  }),
}));

vi.mock('../../lib/api', () => ({
  billingApi: {
    getSubscription: vi.fn().mockResolvedValue({ tier: 'free' }),
    getCreditBalance: vi.fn().mockResolvedValue({ total_credits: 0 }),
    getCreditsBalance: vi.fn().mockResolvedValue({ total_credits: 0 }),
  },
  teamsApi: {
    list: vi.fn().mockResolvedValue([]),
    create: vi.fn().mockResolvedValue({}),
  },
}));

vi.mock('../../lib/keyboard-registry', () => ({
  modKey: (key: string) => `Ctrl+${key}`,
  shortcutGroups: [],
}));

// Mock heavy child components that pull in unrelated providers
vi.mock('../KeyboardShortcutsModal', () => ({
  KeyboardShortcutsModal: () => null,
}));

// Mock framer-motion to render static divs
vi.mock('framer-motion', () => {
  const handler = {
    get() {
      return ({ children, ...rest }: Record<string, unknown>) => {
        // Strip motion-specific props before passing to DOM
        const {
          initial: _i,
          animate: _a,
          exit: _e,
          transition: _t,
          whileHover: _wh,
          whileTap: _wt,
          layout: _l,
          ...domProps
        } = rest;
        return <div {...domProps}>{children as React.ReactNode}</div>;
      };
    },
  };
  return {
    motion: new Proxy({}, handler),
    AnimatePresence: ({ children }: { children: React.ReactNode }) => children,
  };
});

import { NavigationSidebar } from './NavigationSidebar';

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
  localStorageMock.clear();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('NavigationSidebar logout', () => {
  it('calls AuthContext.logout() when logout button is clicked', async () => {
    render(
      <MemoryRouter>
        <NavigationSidebar activePage="dashboard" />
      </MemoryRouter>
    );

    // Open the user dropdown
    const userArea = screen.getByText('Test User');
    fireEvent.click(userArea);

    // Click the Logout button
    const logoutButton = screen.getByText('Logout');
    fireEvent.click(logoutButton);

    await waitFor(() => {
      expect(mockLogout).toHaveBeenCalledOnce();
    });
  });

  it('navigates to /login after logout', async () => {
    render(
      <MemoryRouter>
        <NavigationSidebar activePage="dashboard" />
      </MemoryRouter>
    );

    const userArea = screen.getByText('Test User');
    fireEvent.click(userArea);

    const logoutButton = screen.getByText('Logout');
    fireEvent.click(logoutButton);

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/login');
    });
  });

  it('does NOT call localStorage.removeItem directly (delegates to AuthContext)', async () => {
    render(
      <MemoryRouter>
        <NavigationSidebar activePage="dashboard" />
      </MemoryRouter>
    );

    const userArea = screen.getByText('Test User');
    fireEvent.click(userArea);

    localStorageMock.removeItem.mockClear();

    const logoutButton = screen.getByText('Logout');
    fireEvent.click(logoutButton);

    // The sidebar itself should NOT directly touch localStorage —
    // that's AuthContext.logout()'s job
    await waitFor(() => {
      expect(mockLogout).toHaveBeenCalledOnce();
    });

    // Verify no direct localStorage.removeItem('token') from the sidebar code
    const directTokenRemoval = localStorageMock.removeItem.mock.calls.filter(
      ([key]: [string]) => key === 'token'
    );
    expect(directTokenRemoval).toHaveLength(0);
  });
});
