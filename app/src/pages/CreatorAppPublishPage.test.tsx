import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

vi.mock('../config', () => ({ config: { API_URL: 'http://test' } }));

const publish = vi.fn();
const getAll = vi.fn();

vi.mock('../lib/api', () => ({
  appVersionsApi: { publish: (...a: unknown[]) => publish(...a) },
  marketplaceAppsApi: {
    get: vi.fn(),
    listVersions: vi.fn(),
  },
  projectsApi: { getAll: (...a: unknown[]) => getAll(...a) },
}));

vi.mock('../contexts/TeamContext', () => ({
  useTeam: () => ({ activeTeam: { slug: 'team-1' } }),
}));

const showToast = vi.fn();
vi.mock('../components/ui/Toast', () => ({
  useToast: () => ({ showToast, hideToast: vi.fn() }),
}));

import CreatorAppPublishPage from './CreatorAppPublishPage';

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/creator/publish/new']}>
      <Routes>
        <Route path="/creator/publish/:appId" element={<CreatorAppPublishPage />} />
      </Routes>
    </MemoryRouter>
  );
}

describe('CreatorAppPublishPage', () => {
  beforeEach(() => {
    publish.mockReset();
    getAll.mockReset();
    showToast.mockReset();
    getAll.mockResolvedValue([
      { id: 'p1', slug: 'proj-1', name: 'Project 1' },
    ]);
  });

  it('blocks submit when manifest is invalid', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Publish New App')).toBeInTheDocument());

    fireEvent.click(screen.getByText('Publish'));

    await waitFor(() => {
      expect(screen.getByText(/Select a source project/i)).toBeInTheDocument();
    });
    expect(publish).not.toHaveBeenCalled();
  });

  it('submits a valid manifest', async () => {
    publish.mockResolvedValue({
      app_id: 'app-1',
      app_version_id: 'ver-1',
      version: '0.1.0',
      bundle_hash: 'b',
      manifest_hash: 'm',
      submission_id: 's',
    });

    renderPage();
    await waitFor(() => expect(screen.getByText('Publish New App')).toBeInTheDocument());

    // pick project
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'p1' } });
    // fill slug
    const inputs = screen.getAllByRole('textbox');
    // slug, version, app name
    fireEvent.change(inputs[0], { target: { value: 'my-app' } });
    // version already '0.1.0'
    fireEvent.change(inputs[2], { target: { value: 'My App' } });
    // generate skeleton manifest
    fireEvent.click(screen.getByText('Generate skeleton'));

    fireEvent.click(screen.getByText('Publish'));

    await waitFor(() => expect(publish).toHaveBeenCalledTimes(1));
    const call = publish.mock.calls[0][0];
    expect(call.project_id).toBe('p1');
    expect(typeof call.manifest).toBe('object');
  });
});
