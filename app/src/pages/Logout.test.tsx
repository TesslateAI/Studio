/**
 * Logout page tests
 *
 * Verifies the Logout page delegates to AuthContext.logout() and
 * cleans up GitHub-specific tokens before redirecting.
 */
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ---------------------------------------------------------------------------
// localStorage mock (jsdom doesn't provide a full implementation)
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

vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ logout: mockLogout }),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return { ...actual, useNavigate: () => mockNavigate };
});

vi.mock('react-hot-toast', () => ({
  default: { success: vi.fn() },
}));

// Import after mocks are set up
import Logout from './Logout';
import toast from 'react-hot-toast';

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
  localStorageMock.clear();
  store['token'] = 'test-jwt';
  store['github_token'] = 'gh-token-abc';
  store['github_oauth_return'] = '/dashboard';
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('Logout page', () => {
  it('calls AuthContext.logout()', async () => {
    render(
      <MemoryRouter>
        <Logout />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(mockLogout).toHaveBeenCalledOnce();
    });
  });

  it('clears GitHub tokens from localStorage', async () => {
    render(
      <MemoryRouter>
        <Logout />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(localStorageMock.removeItem).toHaveBeenCalledWith('github_token');
      expect(localStorageMock.removeItem).toHaveBeenCalledWith('github_oauth_return');
    });
  });

  it('shows success toast and navigates to /login', async () => {
    render(
      <MemoryRouter>
        <Logout />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith('Logged out successfully');
      expect(mockNavigate).toHaveBeenCalledWith('/login');
    });
  });

  it('shows "Logging out..." while running', () => {
    // Make logout hang so we can see the loading state
    mockLogout.mockReturnValue(new Promise(() => {}));

    render(
      <MemoryRouter>
        <Logout />
      </MemoryRouter>
    );

    expect(screen.getByText('Logging out...')).toBeInTheDocument();
  });

  it('still redirects even if logout() rejects', async () => {
    mockLogout.mockRejectedValueOnce(new Error('network'));

    render(
      <MemoryRouter>
        <Logout />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/login');
    });
  });
});
