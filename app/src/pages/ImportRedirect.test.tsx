import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import ImportRedirect from './ImportRedirect';

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

/** Captures navigation target and state for assertions. */
function LocationCapture() {
  const location = useLocation();
  const from = (location.state as { from?: string })?.from ?? '';
  return (
    <div data-testid="captured-location">
      <span data-testid="captured-pathname">{location.pathname}</span>
      <span data-testid="captured-search">{location.search}</span>
      <span data-testid="captured-from">{from}</span>
    </div>
  );
}

function renderImportRedirect(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/import" element={<ImportRedirect />} />
        <Route path="/login" element={<LocationCapture />} />
        <Route path="/dashboard" element={<LocationCapture />} />
      </Routes>
    </MemoryRouter>
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('ImportRedirect', () => {
  describe('when authenticated', () => {
    beforeEach(() => {
      mockUseAuth.mockReturnValue({ isAuthenticated: true, isLoading: false });
    });

    it('redirects to /dashboard with import_repo param when repo is valid', () => {
      renderImportRedirect('/import?repo=https://github.com/tesslateai/agent-wrapped');

      expect(screen.getByTestId('captured-pathname')).toHaveTextContent('/dashboard');
      expect(screen.getByTestId('captured-search')).toHaveTextContent(
        '?import_repo=https%3A%2F%2Fgithub.com%2Ftesslateai%2Fagent-wrapped'
      );
    });

    it('redirects to /dashboard without params when repo is missing', () => {
      renderImportRedirect('/import');

      expect(screen.getByTestId('captured-pathname')).toHaveTextContent('/dashboard');
      expect(screen.getByTestId('captured-search')).toHaveTextContent('');
    });

    it('redirects to /dashboard without params when repo is not https', () => {
      renderImportRedirect('/import?repo=http://github.com/org/repo');

      expect(screen.getByTestId('captured-pathname')).toHaveTextContent('/dashboard');
      expect(screen.getByTestId('captured-search')).toHaveTextContent('');
    });

    it('redirects to /dashboard without params when repo is not a URL', () => {
      renderImportRedirect('/import?repo=not-a-url');

      expect(screen.getByTestId('captured-pathname')).toHaveTextContent('/dashboard');
      expect(screen.getByTestId('captured-search')).toHaveTextContent('');
    });

    it('redirects to /dashboard when repo host is not an allowed git provider', () => {
      renderImportRedirect('/import?repo=https://evil.com/malicious-payload');

      expect(screen.getByTestId('captured-pathname')).toHaveTextContent('/dashboard');
      expect(screen.getByTestId('captured-search')).toHaveTextContent('');
    });

    it('rejects javascript: protocol', () => {
      renderImportRedirect('/import?repo=javascript:alert(1)');

      expect(screen.getByTestId('captured-pathname')).toHaveTextContent('/dashboard');
      expect(screen.getByTestId('captured-search')).toHaveTextContent('');
    });
  });

  describe('when unauthenticated', () => {
    beforeEach(() => {
      mockUseAuth.mockReturnValue({ isAuthenticated: false, isLoading: false });
    });

    it('redirects to /login with from state preserving the deep link', () => {
      renderImportRedirect('/import?repo=https://github.com/tesslateai/agent-wrapped');

      expect(screen.getByTestId('captured-pathname')).toHaveTextContent('/login');
      expect(screen.getByTestId('captured-from')).toHaveTextContent(
        '/import?repo=https%3A%2F%2Fgithub.com%2Ftesslateai%2Fagent-wrapped'
      );
    });

    it('redirects to /dashboard when repo param is missing', () => {
      renderImportRedirect('/import');

      expect(screen.getByTestId('captured-pathname')).toHaveTextContent('/dashboard');
    });
  });

  describe('when loading', () => {
    it('renders loading spinner and does not navigate', () => {
      mockUseAuth.mockReturnValue({ isAuthenticated: false, isLoading: true });

      renderImportRedirect('/import?repo=https://github.com/org/repo');

      expect(screen.queryByTestId('captured-location')).not.toBeInTheDocument();
    });
  });
});
