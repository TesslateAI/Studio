/**
 * AdminSubmissionWorkbenchPage — verifies the advance button calls
 * advanceSubmission with the current stage's next-stage.
 */
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../config', () => ({ config: { API_URL: 'http://test' } }));

const mockUseAuth = vi.fn();
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => mockUseAuth(),
}));

const advanceSubmission = vi.fn().mockResolvedValue(undefined);
const runStage1Scan = vi.fn();
const runStage2Eval = vi.fn();
vi.mock('../contexts/AdminContext', () => ({
  useRequiredAdmin: () => ({
    submissionQueue: [],
    yankQueue: [],
    stats: null,
    isLoading: false,
    error: null,
    refreshAll: vi.fn(),
    advanceSubmission,
    runStage1Scan,
    runStage2Eval,
    approveYank: vi.fn(),
    rejectYank: vi.fn(),
  }),
}));

const getSubmission = vi.fn();
vi.mock('../lib/api', () => ({
  appSubmissionsApi: {
    get: (...a: unknown[]) => getSubmission(...a),
    recordCheck: vi.fn(),
  },
}));

import AdminSubmissionWorkbenchPage from './AdminSubmissionWorkbenchPage';

beforeEach(() => {
  advanceSubmission.mockClear();
  getSubmission.mockReset();
  mockUseAuth.mockReturnValue({ user: { id: 'u1', is_superuser: true } });
});

describe('AdminSubmissionWorkbenchPage', () => {
  it('advance button calls advanceSubmission with next stage', async () => {
    getSubmission.mockResolvedValue({
      id: 'sub-1',
      app_version_id: 'v1',
      submitter_user_id: 'u2',
      stage: 'stage0',
      decision: 'pending',
      reviewer_user_id: null,
      decision_notes: null,
      checks: [],
    });

    render(
      <MemoryRouter initialEntries={['/admin/marketplace/submissions/sub-1']}>
        <Routes>
          <Route
            path="/admin/marketplace/submissions/:submissionId"
            element={<AdminSubmissionWorkbenchPage />}
          />
        </Routes>
      </MemoryRouter>
    );

    const advanceBtn = await screen.findByTestId('advance-stage1');
    fireEvent.click(advanceBtn);

    await waitFor(() =>
      expect(advanceSubmission).toHaveBeenCalledWith('sub-1', 'stage1', undefined)
    );
  });
});
