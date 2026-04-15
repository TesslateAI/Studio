import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  appBillingApi,
  type LedgerEntry,
  type WalletSnapshot,
} from '../lib/api';
import { useAuth } from '../contexts/AuthContext';

interface CreatorUser {
  id: string;
  creator_stripe_account_id?: string | null;
}

interface AxiosLikeError {
  response?: { status?: number; data?: { detail?: string } };
  message?: string;
}

function extractError(err: unknown, fallback: string): string {
  const e = err as AxiosLikeError;
  return e?.response?.data?.detail ?? e?.message ?? fallback;
}

function formatCurrency(amount: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
  }).format(amount);
}

/**
 * CreatorBillingPanel — the content block, reusable inside CreatorStudioPage
 * Billing tab as well as the dedicated route.
 */
export function CreatorBillingPanel() {
  const { user } = useAuth();
  const creator = user as (typeof user & CreatorUser) | null;
  const navigate = useNavigate();

  const [wallet, setWallet] = useState<WalletSnapshot | null>(null);
  const [ledger, setLedger] = useState<LedgerEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [onboardingRequired, setOnboardingRequired] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setOnboardingRequired(false);

    (async () => {
      try {
        const w = await appBillingApi.getCreatorWallet();
        if (cancelled) return;
        setWallet(w);
      } catch (err) {
        const e = err as AxiosLikeError;
        if (e?.response?.status === 403) {
          if (!cancelled) setOnboardingRequired(true);
          return;
        }
        if (!cancelled) setError(extractError(err, 'Failed to load wallet'));
        return;
      }

      try {
        const l = await appBillingApi.getLedger({ wallet_type: 'creator', limit: 50 });
        if (!cancelled) setLedger(l.items);
      } catch (err) {
        if (!cancelled) setError(extractError(err, 'Failed to load ledger'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const monthlyStats = useMemo(() => {
    const cutoff = Date.now() - 30 * 24 * 60 * 60 * 1000;
    const recent = ledger.filter((e) => new Date(e.created_at).getTime() >= cutoff);
    const total = recent.reduce((acc, e) => acc + (e.amount_usd ?? 0), 0);
    const byApp: Record<string, number> = {};
    for (const e of recent) {
      const ref =
        (e.meta?.['app_name'] as string) ||
        (e.meta?.['app_id'] as string) ||
        e.reference_id ||
        'unknown';
      byApp[ref] = (byApp[ref] ?? 0) + e.amount_usd;
    }
    const top = Object.entries(byApp).sort((a, b) => b[1] - a[1])[0];
    return { total, topApp: top ? { name: top[0], amount: top[1] } : null };
  }, [ledger]);

  const pendingEarnings = useMemo(
    () => ledger.filter((e) => e.meta?.['settled'] === false).reduce((a, e) => a + e.amount_usd, 0),
    [ledger]
  );

  if (onboardingRequired || !creator?.creator_stripe_account_id) {
    return (
      <div className="p-6 max-w-xl mx-auto text-center">
        <h2 className="text-xl font-semibold text-[var(--text)] mb-3">Become a creator</h2>
        <p className="text-[var(--text-muted)] mb-6">
          Connect a Stripe account to receive earnings from app installs and usage.
        </p>
        <button
          onClick={() => navigate('/settings')}
          className="px-4 py-2 rounded bg-[var(--accent)] text-white"
          type="button"
        >
          Connect Stripe
        </button>
      </div>
    );
  }

  if (loading) {
    return <div className="p-6 text-[var(--text-muted)]">Loading billing...</div>;
  }
  if (error) {
    return <div className="p-6 text-red-500">{error}</div>;
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div
          className="p-4 rounded-lg border"
          style={{ borderColor: 'var(--border)', backgroundColor: 'var(--surface)' }}
        >
          <div className="text-xs text-[var(--text-muted)] uppercase">Wallet Balance</div>
          <div className="text-3xl font-semibold text-[var(--text)] mt-1">
            {formatCurrency(wallet?.balance_usd ?? 0)}
          </div>
        </div>
        <div
          className="p-4 rounded-lg border"
          style={{ borderColor: 'var(--border)', backgroundColor: 'var(--surface)' }}
        >
          <div className="text-xs text-[var(--text-muted)] uppercase">Pending Earnings</div>
          <div className="text-3xl font-semibold text-[var(--text)] mt-1">
            {formatCurrency(pendingEarnings)}
          </div>
        </div>
        <div
          className="p-4 rounded-lg border"
          style={{ borderColor: 'var(--border)', backgroundColor: 'var(--surface)' }}
        >
          <div className="text-xs text-[var(--text-muted)] uppercase">Last 30 Days</div>
          <div className="text-3xl font-semibold text-[var(--text)] mt-1">
            {formatCurrency(monthlyStats.total)}
          </div>
          {monthlyStats.topApp && (
            <div className="text-xs text-[var(--text-muted)] mt-1">
              Top: {monthlyStats.topApp.name}
            </div>
          )}
        </div>
      </div>

      <div>
        <h3 className="text-sm font-semibold text-[var(--text)] mb-2">Recent Earnings</h3>
        {ledger.length === 0 ? (
          <div className="text-sm text-[var(--text-muted)]">No ledger entries yet.</div>
        ) : (
          <div
            className="border rounded-lg overflow-hidden"
            style={{ borderColor: 'var(--border)' }}
          >
            <table className="w-full text-sm">
              <thead
                className="text-left text-xs uppercase text-[var(--text-muted)]"
                style={{ backgroundColor: 'var(--surface)' }}
              >
                <tr>
                  <th className="px-3 py-2">Date</th>
                  <th className="px-3 py-2">Reference</th>
                  <th className="px-3 py-2">Type</th>
                  <th className="px-3 py-2 text-right">Amount</th>
                  <th className="px-3 py-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {ledger.map((entry) => (
                  <tr
                    key={entry.id}
                    className="border-t"
                    style={{ borderColor: 'var(--border)' }}
                  >
                    <td className="px-3 py-2 text-[var(--text-muted)]">
                      {entry.created_at.slice(0, 10)}
                    </td>
                    <td className="px-3 py-2 text-[var(--text)]">
                      {(entry.meta?.['app_name'] as string) ||
                        entry.reference_id?.slice(0, 8) ||
                        '—'}
                    </td>
                    <td className="px-3 py-2 text-[var(--text-muted)]">{entry.entry_type}</td>
                    <td className="px-3 py-2 text-right text-[var(--text)]">
                      {formatCurrency(entry.amount_usd)}
                    </td>
                    <td className="px-3 py-2 text-[var(--text-muted)]">
                      {entry.meta?.['settled'] === false ? 'pending' : 'settled'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div
        className="p-4 rounded-lg border"
        style={{ borderColor: 'var(--border)', backgroundColor: 'var(--surface)' }}
      >
        <h3 className="text-sm font-semibold text-[var(--text)] mb-1">Payout Settings</h3>
        <p className="text-xs text-[var(--text-muted)]">
          Stripe Connect account: {creator.creator_stripe_account_id}
        </p>
      </div>
    </div>
  );
}

export default function CreatorBillingPage() {
  return (
    <div className="p-6">
      <h1 className="text-xl font-semibold text-[var(--text)] mb-4">Creator Billing</h1>
      <CreatorBillingPanel />
    </div>
  );
}
