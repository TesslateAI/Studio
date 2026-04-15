/**
 * AdminAdversarialSuitePage
 *
 * Route: /admin/marketplace/adversarial
 *
 * Backend currently exposes only
 *   POST /api/admin-marketplace/adversarial/runs (recordAdversarialRun)
 * — there is no GET endpoint for listing AdversarialSuite rows or previous
 * runs. Until those exist, admins enter suite_id + app_version_id manually
 * and we keep a client-side recent-runs list of what was submitted in this
 * session.
 */
import { useState } from 'react';
import { Navigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import { useAuth } from '../contexts/AuthContext';
import { adminMarketplaceApi } from '../lib/api';

interface RecentRun {
  run_id: string;
  suite_id: string;
  app_version_id: string;
  score: number | null;
  findings: Record<string, unknown> | null;
  at: string;
}

export default function AdminAdversarialSuitePage() {
  const { user } = useAuth();
  if (!user?.is_superuser) return <Navigate to="/dashboard" replace />;

  const [suiteId, setSuiteId] = useState('');
  const [appVersionId, setAppVersionId] = useState('');
  const [score, setScore] = useState('');
  const [findings, setFindings] = useState('{}');
  const [busy, setBusy] = useState(false);
  const [recent, setRecent] = useState<RecentRun[]>([]);

  const submit = async () => {
    if (!suiteId || !appVersionId) {
      toast.error('suite_id and app_version_id required');
      return;
    }
    let findingsObj: Record<string, unknown> = {};
    try {
      findingsObj = JSON.parse(findings) as Record<string, unknown>;
    } catch {
      toast.error('findings must be valid JSON');
      return;
    }
    const scoreNum = score === '' ? undefined : parseFloat(score);
    if (score !== '' && !Number.isFinite(scoreNum)) {
      toast.error('score must be a number');
      return;
    }
    setBusy(true);
    try {
      const r = await adminMarketplaceApi.recordAdversarialRun({
        suite_id: suiteId,
        app_version_id: appVersionId,
        score: scoreNum,
        findings: findingsObj,
      });
      toast.success(`Run recorded: ${r.run_id}`);
      setRecent((p) => [
        {
          run_id: r.run_id,
          suite_id: suiteId,
          app_version_id: appVersionId,
          score: scoreNum ?? null,
          findings: findingsObj,
          at: new Date().toISOString(),
        },
        ...p,
      ]);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-[var(--bg)] text-[var(--text)]">
      <header className="border-b border-[var(--border)] px-8 py-5">
        <h1 className="text-2xl font-semibold">Adversarial Suite</h1>
        <p className="text-sm text-[var(--text-muted)] mt-1">
          Record adversarial runs against an approved AppVersion. Suite listing
          endpoint is not yet available.
        </p>
      </header>

      <main className="p-8 grid grid-cols-1 lg:grid-cols-2 gap-8">
        <section className="space-y-3">
          <Field label="Suite id" value={suiteId} onChange={setSuiteId} />
          <Field
            label="App version id"
            value={appVersionId}
            onChange={setAppVersionId}
          />
          <Field label="Score (optional)" value={score} onChange={setScore} />
          <label className="block text-sm">
            <span className="block text-xs uppercase tracking-wide text-[var(--text-muted)] mb-1">
              Findings (JSON)
            </span>
            <textarea
              value={findings}
              onChange={(e) => setFindings(e.target.value)}
              rows={6}
              className="w-full rounded border border-[var(--border)] bg-[var(--surface)] px-2 py-1 font-mono text-xs"
            />
          </label>
          <button
            disabled={busy}
            onClick={() => void submit()}
            className="px-4 py-2 rounded bg-[var(--primary)] text-white text-sm disabled:opacity-50"
          >
            Record run
          </button>
        </section>

        <section>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--text-muted)] mb-3">
            Recent runs (this session)
          </h2>
          {recent.length === 0 && (
            <p className="text-sm text-[var(--text-muted)]">
              No runs submitted this session.
            </p>
          )}
          <ul className="space-y-2">
            {recent.map((r) => (
              <li
                key={r.run_id}
                className="rounded border border-[var(--border)] p-3 text-sm"
              >
                <div className="font-mono text-xs text-[var(--text-muted)]">
                  {r.run_id}
                </div>
                <div>
                  <span className="text-[var(--text-muted)]">score:</span>{' '}
                  {r.score ?? '—'}
                </div>
                <pre className="text-xs mt-1 overflow-auto">
                  {JSON.stringify(r.findings, null, 2)}
                </pre>
              </li>
            ))}
          </ul>
        </section>
      </main>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="block text-sm">
      <span className="block text-xs uppercase tracking-wide text-[var(--text-muted)] mb-1">
        {label}
      </span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded border border-[var(--border)] bg-[var(--surface)] px-2 py-1"
      />
    </label>
  );
}
