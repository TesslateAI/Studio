/**
 * AdminYankCenterPage
 *
 * Route: /admin/marketplace/yanks
 *
 * Full yank moderation table. Approve / reject actions go through
 * useAdmin(). Critical yanks require a second admin — backend responds
 * { needs_second_admin: true } and we keep the row in pending state while
 * showing a warning toast.
 */
import { useCallback, useEffect, useState } from 'react';
import { Navigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import { useAuth } from '../contexts/AuthContext';
import { useRequiredAdmin } from '../contexts/AdminContext';
import { appYanksApi, type YankRequest, type YankSeverity } from '../lib/api';

export default function AdminYankCenterPage() {
  const { user } = useAuth();
  if (!user?.is_superuser) return <Navigate to="/dashboard" replace />;

  const admin = useRequiredAdmin();
  const [rows, setRows] = useState<YankRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await appYanksApi.list({ limit: 100 });
      setRows(resp.items);
    } catch (e) {
      toast.error(`Failed to load yanks: ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const onApprove = async (row: YankRequest) => {
    setBusyId(row.id);
    try {
      const result = await admin.approveYank(row.id);
      if (result.needsSecondAdmin) {
        toast('Needs a second admin to approve critical yank', { icon: '⚠️' });
      } else {
        toast.success('Yank approved');
      }
      await load();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusyId(null);
    }
  };

  const onReject = async (row: YankRequest) => {
    setBusyId(row.id);
    try {
      await admin.rejectYank(row.id);
      toast.success('Yank rejected');
      await load();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="min-h-screen bg-[var(--bg)] text-[var(--text)]">
      <header className="border-b border-[var(--border)] px-8 py-5">
        <h1 className="text-2xl font-semibold">Yank Center</h1>
        <p className="text-sm text-[var(--text-muted)] mt-1">
          Review, approve, or reject yank requests.
        </p>
      </header>

      <main className="p-8">
        {loading && <p className="text-sm text-[var(--text-muted)]">Loading…</p>}
        {!loading && rows.length === 0 && (
          <p className="text-sm text-[var(--text-muted)]">No yank requests.</p>
        )}
        {!loading && rows.length > 0 && (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[var(--text-muted)] border-b border-[var(--border)]">
                <th className="py-2 pr-4">App Version</th>
                <th className="py-2 pr-4">Requester</th>
                <th className="py-2 pr-4">Severity</th>
                <th className="py-2 pr-4">Status</th>
                <th className="py-2 pr-4">Primary</th>
                <th className="py-2 pr-4">Secondary</th>
                <th className="py-2 pr-4">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.id}
                  data-testid={`yank-row-${row.id}`}
                  className="border-b border-[var(--border)] align-top"
                >
                  <td className="py-2 pr-4 font-mono text-xs">
                    {row.app_version_id.slice(0, 8)}
                  </td>
                  <td className="py-2 pr-4 font-mono text-xs">
                    {row.requester_user_id?.slice(0, 8) ?? '—'}
                  </td>
                  <td className="py-2 pr-4">
                    <SeverityBadge severity={row.severity} />
                  </td>
                  <td className="py-2 pr-4 text-xs">{row.status}</td>
                  <td className="py-2 pr-4 font-mono text-xs">
                    {row.primary_admin_id?.slice(0, 8) ?? '—'}
                  </td>
                  <td className="py-2 pr-4 font-mono text-xs">
                    {row.secondary_admin_id?.slice(0, 8) ?? '—'}
                  </td>
                  <td className="py-2 pr-4">
                    <div className="flex flex-col gap-1">
                      {row.status === 'pending' && (
                        <>
                          <button
                            data-testid={`approve-${row.id}`}
                            disabled={busyId === row.id}
                            onClick={() => void onApprove(row)}
                            className="px-2 py-1 rounded bg-emerald-600 text-white text-xs disabled:opacity-50"
                          >
                            Approve
                          </button>
                          <button
                            data-testid={`reject-${row.id}`}
                            disabled={busyId === row.id}
                            onClick={() => void onReject(row)}
                            className="px-2 py-1 rounded bg-red-600 text-white text-xs disabled:opacity-50"
                          >
                            Reject
                          </button>
                        </>
                      )}
                      {row.severity === 'critical' &&
                        row.primary_admin_id &&
                        !row.secondary_admin_id &&
                        row.status === 'pending' && (
                          <span
                            data-testid={`needs-second-${row.id}`}
                            className="text-amber-400 text-xs"
                          >
                            Needs second admin
                          </span>
                        )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </main>
    </div>
  );
}

function SeverityBadge({ severity }: { severity: YankSeverity }) {
  const colors: Record<string, string> = {
    low: 'bg-slate-500/20 text-slate-300',
    medium: 'bg-amber-500/20 text-amber-300',
    critical: 'bg-red-500/20 text-red-300',
  };
  const cls = colors[severity] ?? 'bg-[var(--surface-hover)] text-[var(--text-muted)]';
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${cls}`}>
      {severity}
    </span>
  );
}
