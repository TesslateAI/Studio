/**
 * ForkModal — submits with correct args.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('../../config', () => ({
  config: { API_URL: 'http://test' },
}));

const fork = vi.fn();

vi.mock('../../lib/api', () => ({
  marketplaceAppsApi: {
    fork: (...args: unknown[]) => fork(...args),
  },
}));

vi.mock('../../contexts/TeamContext', () => ({
  useTeam: () => ({ activeTeam: null }),
}));

import { ForkModal } from '../../components/apps/ForkModal';

describe('ForkModal', () => {
  beforeEach(() => {
    fork.mockReset();
  });

  it('submits fork with slug + name and invokes onForked', async () => {
    fork.mockResolvedValue({
      id: 'app-new',
      slug: 'my-fork',
      name: 'My Fork',
      description: null,
      category: null,
      icon_ref: null,
      forkable: 'true',
      forked_from: 'app-src',
      visibility: 'public',
      state: 'draft',
      reputation: {},
      creator_user_id: 'u1',
      created_at: '',
      updated_at: '',
    });

    const onForked = vi.fn();
    render(
      <ForkModal appId="app-src" sourceAppVersionId="v1" onClose={() => {}} onForked={onForked} />
    );

    const nameInput = screen.getByPlaceholderText('My forked app') as HTMLInputElement;
    fireEvent.change(nameInput, { target: { value: 'My Fork' } });

    const submitBtn = screen.getByRole('button', { name: /^fork$/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(fork).toHaveBeenCalledWith('app-src', {
        source_app_version_id: 'v1',
        new_slug: 'my-fork',
        new_name: 'My Fork',
      });
      expect(onForked).toHaveBeenCalled();
    });
  });
});
