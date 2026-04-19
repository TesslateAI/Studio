/**
 * AdminCreatorReputationPage
 *
 * Route: /admin/marketplace/reputation
 *
 * Adjust creator reputation. Backend exposes
 *   POST /api/admin-marketplace/reputation/{user_id}
 * but there is no aggregate "list all creators with reputation" endpoint yet.
 * Until that exists, superusers enter a user_id manually. The per-row form
 * sends signed deltas via adminMarketplaceApi.adjustReputation.
 */
import { useState } from 'react';
import { Navigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import { useAuth } from '../contexts/AuthContext';
import { adminMarketplaceApi } from '../lib/api';

interface Row {
  userId: string;
  deltaScore: string;
  deltaApprovals: string;
  deltaYanks: string;
  deltaCriticalYanks: string;
  busy: boolean;
}

function newRow(userId = ''): Row {
  return {
    userId,
    deltaScore: '0',
    deltaApprovals: '0',
    deltaYanks: '0',
    deltaCriticalYanks: '0',
    busy: false,
  };
}

export default function AdminCreatorReputationPage() {
  const { user } = useAuth();
  const [rows, setRows] = useState<Row[]>([newRow()]);

  if (!user?.is_superuser) return <Navigate to="/dashboard" replace />;

  const update = (idx: number, patch: Partial<Row>) => {
    setRows((prev) => prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
  };

  const submit = async (idx: number) => {
    const row = rows[idx];
    if (!row.userId) {
      toast.error('user_id required');
      return;
    }
    update(idx, { busy: true });
    try {
      await adminMarketplaceApi.adjustReputation(row.userId, {
        delta_score: parseIntSafe(row.deltaScore),
        delta_approvals: parseIntSafe(row.deltaApprovals),
        delta_yanks: parseIntSafe(row.deltaYanks),
        delta_critical_yanks: parseIntSafe(row.deltaCriticalYanks),
      });
      toast.success('Reputation adjusted');
      update(idx, {
        busy: false,
        deltaScore: '0',
        deltaApprovals: '0',
        deltaYanks: '0',
        deltaCriticalYanks: '0',
      });
    } catch (e) {
      toast.error((e as Error).message);
      update(idx, { busy: false });
    }
  };

  return (
    <div className="min-h-screen bg-[var(--bg)] text-[var(--text)]">
      <header className="border-b border-[var(--border)] px-8 py-5">
        <h1 className="text-2xl font-semibold">Creator Reputation</h1>
        <p className="text-sm text-[var(--text-muted)] mt-1">
          Adjust reputation deltas. Aggregate listing endpoint not yet available — enter user ids
          manually.
        </p>
      </header>

      <main className="p-8 space-y-4">
        {rows.map((row, idx) => (
          <div
            key={idx}
            className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4"
          >
            <div className="grid grid-cols-5 gap-2 text-sm">
              <LabeledField label="user_id">
                <input
                  value={row.userId}
                  onChange={(e) => update(idx, { userId: e.target.value })}
                  className="w-full rounded border border-[var(--border)] bg-[var(--surface-hover)] px-2 py-1 font-mono text-xs"
                />
              </LabeledField>
              <LabeledField label="Δ score">
                <NumberInput
                  value={row.deltaScore}
                  onChange={(v) => update(idx, { deltaScore: v })}
                />
              </LabeledField>
              <LabeledField label="Δ approvals">
                <NumberInput
                  value={row.deltaApprovals}
                  onChange={(v) => update(idx, { deltaApprovals: v })}
                />
              </LabeledField>
              <LabeledField label="Δ yanks">
                <NumberInput
                  value={row.deltaYanks}
                  onChange={(v) => update(idx, { deltaYanks: v })}
                />
              </LabeledField>
              <LabeledField label="Δ critical yanks">
                <NumberInput
                  value={row.deltaCriticalYanks}
                  onChange={(v) => update(idx, { deltaCriticalYanks: v })}
                />
              </LabeledField>
            </div>

            <div className="mt-3 flex gap-2">
              <button
                disabled={row.busy}
                onClick={() => void submit(idx)}
                className="px-3 py-1.5 rounded bg-[var(--primary)] text-white text-sm disabled:opacity-50"
              >
                Apply
              </button>
              {rows.length > 1 && (
                <button
                  onClick={() => setRows((prev) => prev.filter((_, i) => i !== idx))}
                  className="px-3 py-1.5 rounded border border-[var(--border)] text-sm"
                >
                  Remove
                </button>
              )}
            </div>
          </div>
        ))}

        <button
          onClick={() => setRows((p) => [...p, newRow()])}
          className="px-3 py-1.5 rounded border border-dashed border-[var(--border)] text-sm"
        >
          + Add row
        </button>
      </main>
    </div>
  );
}

function parseIntSafe(v: string): number {
  const n = parseInt(v, 10);
  return Number.isFinite(n) ? n : 0;
}

function LabeledField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-xs uppercase tracking-wide text-[var(--text-muted)] mb-1">
        {label}
      </span>
      {children}
    </label>
  );
}

function NumberInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <input
      type="number"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="w-full rounded border border-[var(--border)] bg-[var(--surface-hover)] px-2 py-1 text-sm"
    />
  );
}
