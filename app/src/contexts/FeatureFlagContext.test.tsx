/**
 * Feature Flag Context Tests
 *
 * Tests the context provider, hooks, and API integration.
 */
import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { FeatureFlagProvider } from './FeatureFlagContext';
import { useFeatureFlag, useFeatureFlags } from './useFeatureFlag';

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockGetFlags = vi.fn();

vi.mock('../lib/api', () => ({
  featureFlagsApi: {
    getFlags: () => mockGetFlags(),
  },
}));

// ---------------------------------------------------------------------------
// Test components
// ---------------------------------------------------------------------------

function FlagDisplay({ flag }: { flag: string }) {
  const value = useFeatureFlag(flag);
  return <span data-testid={`flag-${flag}`}>{String(value)}</span>;
}

function AllFlagsDisplay() {
  const { flags, env, loading } = useFeatureFlags();
  return (
    <div>
      <span data-testid="loading">{String(loading)}</span>
      <span data-testid="env">{env}</span>
      <span data-testid="flags">{JSON.stringify(flags)}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('FeatureFlagContext', () => {
  beforeEach(() => {
    mockGetFlags.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('provides flags from the API response', async () => {
    mockGetFlags.mockResolvedValue({
      env: 'minikube',
      flags: { two_fa: false, template_builder: true },
    });

    render(
      <FeatureFlagProvider>
        <FlagDisplay flag="two_fa" />
        <FlagDisplay flag="template_builder" />
      </FeatureFlagProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('flag-two_fa')).toHaveTextContent('false');
      expect(screen.getByTestId('flag-template_builder')).toHaveTextContent('true');
    });
  });

  it('returns false for unknown flags', async () => {
    mockGetFlags.mockResolvedValue({
      env: 'docker',
      flags: { two_fa: false },
    });

    render(
      <FeatureFlagProvider>
        <FlagDisplay flag="nonexistent" />
      </FeatureFlagProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('flag-nonexistent')).toHaveTextContent('false');
    });
  });

  it('sets loading to false after fetch resolves', async () => {
    mockGetFlags.mockResolvedValue({
      env: 'beta',
      flags: { two_fa: true },
    });

    render(
      <FeatureFlagProvider>
        <AllFlagsDisplay />
      </FeatureFlagProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('false');
      expect(screen.getByTestId('env')).toHaveTextContent('beta');
    });
  });

  it('fails open with empty flags on API error', async () => {
    mockGetFlags.mockResolvedValue({
      env: '',
      flags: {},
    });

    render(
      <FeatureFlagProvider>
        <AllFlagsDisplay />
      </FeatureFlagProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('false');
      expect(screen.getByTestId('flags')).toHaveTextContent('{}');
    });
  });

  it('exposes env from response', async () => {
    mockGetFlags.mockResolvedValue({
      env: 'production',
      flags: { two_fa: true },
    });

    render(
      <FeatureFlagProvider>
        <AllFlagsDisplay />
      </FeatureFlagProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('env')).toHaveTextContent('production');
    });
  });

  it('returns false for all flags while loading', () => {
    // Never-resolving promise to keep loading state
    mockGetFlags.mockReturnValue(new Promise(() => {}));

    render(
      <FeatureFlagProvider>
        <FlagDisplay flag="two_fa" />
        <AllFlagsDisplay />
      </FeatureFlagProvider>
    );

    // Should immediately render false (default) while loading
    expect(screen.getByTestId('flag-two_fa')).toHaveTextContent('false');
    expect(screen.getByTestId('loading')).toHaveTextContent('true');
  });
});
