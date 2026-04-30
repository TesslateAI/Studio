/**
 * AutomationDetailPage — cost rollup card.
 *
 * Smoke test verifying the spend rollup component sums runs by created_at
 * window (24h / 7d / 30d) using a deterministic ``Date.now`` and a small
 * mock automation + run set served via the api.ts mock below.
 *
 * The test scopes itself to the rollup card + run-history table; the
 * filter bar's status-dropdown re-fetch behaviour is not covered here
 * (the component already verifies that with manual testing during
 * development — adding it here would require a deeper async harness).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import type { ReactNode } from 'react';

vi.mock('../config', () => ({
  config: { API_URL: 'http://test' },
}));

// react-hot-toast — just stub the toast object.
vi.mock('react-hot-toast', () => ({
  default: { success: vi.fn(), error: vi.fn() },
  toast: { success: vi.fn(), error: vi.fn() },
}));

// Tight mock around the only two automationsApi methods the page hits.
const mockGet = vi.fn();
const mockListRuns = vi.fn();

vi.mock('../lib/api', () => ({
  automationsApi: {
    get: (...args: unknown[]) => mockGet(...args),
    listRuns: (...args: unknown[]) => mockListRuns(...args),
    update: vi.fn(),
    remove: vi.fn(),
    run: vi.fn(),
  },
  // Detail page resolves agent_id → name and shows destination names
  // alongside trigger/action labels. The rollup test doesn't care about
  // either, so stub them to empty results.
  marketplaceApi: {
    getMyAgents: vi.fn().mockResolvedValue({ agents: [] }),
  },
  communicationDestinationsApi: {
    list: vi.fn().mockResolvedValue([]),
  },
}));

// DestinationPicker pulls in CommunicationDestination data we don't care
// about — stub it to a no-op input.
vi.mock('../pages/automations/components/DestinationPicker', () => ({
  DestinationPicker: () => null,
}));

vi.mock('../components/modals/ConfirmDialog', () => ({
  ConfirmDialog: () => null,
}));

import AutomationDetailPage from '../pages/automations/AutomationDetailPage';

function wrap(node: ReactNode) {
  return (
    <MemoryRouter initialEntries={['/automations/auto-1']}>
      <Routes>
        <Route path="/automations/:id" element={node} />
      </Routes>
    </MemoryRouter>
  );
}

const FIXED_NOW = new Date('2026-04-26T12:00:00Z').getTime();

function isoBeforeNow(ms: number): string {
  return new Date(FIXED_NOW - ms).toISOString();
}

describe('AutomationDetailPage cost rollups', () => {
  let originalDateNow: typeof Date.now;

  beforeEach(() => {
    mockGet.mockReset();
    mockListRuns.mockReset();
    // Pin Date.now without enabling fake timers so React's promise
    // microtask scheduling continues to work normally.
    originalDateNow = Date.now;
    Date.now = () => FIXED_NOW;
  });

  afterEach(() => {
    Date.now = originalDateNow;
  });

  it('sums spend_usd across the 24h / 7d / 30d windows', async () => {
    mockGet.mockResolvedValue({
      id: 'auto-1',
      name: 'Test automation',
      owner_user_id: 'u-1',
      team_id: null,
      workspace_scope: 'none',
      workspace_project_id: null,
      target_project_id: null,
      contract: {},
      max_compute_tier: 1,
      max_spend_per_run_usd: null,
      max_spend_per_day_usd: null,
      parent_automation_id: null,
      depth: 0,
      is_active: true,
      paused_reason: null,
      attribution_user_id: null,
      created_by_user_id: null,
      created_at: isoBeforeNow(0),
      updated_at: isoBeforeNow(0),
      triggers: [],
      actions: [],
      delivery_targets: [],
    });

    // Three runs, one inside each rollup window:
    //  - 1h ago,   $0.50  → counts in 24h, 7d, 30d
    //  - 3d ago,   $1.25  → counts in 7d, 30d
    //  - 20d ago,  $4.00  → counts only in 30d
    mockListRuns.mockResolvedValue([
      {
        id: 'run-recent',
        automation_id: 'auto-1',
        event_id: 'e-1',
        status: 'succeeded',
        retry_count: 0,
        spend_usd: '0.50',
        contract_breaches: 0,
        paused_reason: null,
        started_at: isoBeforeNow(60 * 60 * 1000),
        ended_at: isoBeforeNow(60 * 60 * 1000 - 5_000),
        created_at: isoBeforeNow(60 * 60 * 1000),
      },
      {
        id: 'run-mid',
        automation_id: 'auto-1',
        event_id: 'e-2',
        status: 'succeeded',
        retry_count: 0,
        spend_usd: '1.25',
        contract_breaches: 0,
        paused_reason: null,
        started_at: isoBeforeNow(3 * 24 * 60 * 60 * 1000),
        ended_at: null,
        created_at: isoBeforeNow(3 * 24 * 60 * 60 * 1000),
      },
      {
        id: 'run-old',
        automation_id: 'auto-1',
        event_id: 'e-3',
        status: 'failed',
        retry_count: 0,
        spend_usd: '4.00',
        contract_breaches: 1,
        paused_reason: null,
        started_at: isoBeforeNow(20 * 24 * 60 * 60 * 1000),
        ended_at: isoBeforeNow(20 * 24 * 60 * 60 * 1000 - 5_000),
        created_at: isoBeforeNow(20 * 24 * 60 * 60 * 1000),
      },
    ]);

    render(wrap(<AutomationDetailPage />));

    await waitFor(() => {
      expect(screen.getByTestId('cost-rollup-card')).toBeInTheDocument();
    });

    // Wait for runs to load before asserting the rollup numbers.
    await waitFor(() => {
      expect(screen.getByTestId('rollup-30d').textContent).toContain('$5.75');
    });

    // 24h window: just the $0.50 run (formatter trims trailing zeros < $1).
    expect(screen.getByTestId('rollup-24h').textContent).toContain('$0.5');
    // 7d window: $0.50 + $1.25 = $1.75.
    expect(screen.getByTestId('rollup-7d').textContent).toContain('$1.75');
    // 30d window: $0.50 + $1.25 + $4.00 = $5.75.
    expect(screen.getByTestId('rollup-30d').textContent).toContain('$5.75');
  });
});
