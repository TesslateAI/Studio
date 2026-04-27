import { useEffect, useMemo, useState } from 'react';
import toast from 'react-hot-toast';
import {
  adminSpendApi,
  type SpendRollupGroupBy,
  type SpendRollupResponse,
  type SpendRollupRow,
} from '../../lib/api';

/**
 * Admin spend rollup dashboard — Phase 5 polish.
 *
 * Surfaces ``/api/admin/spend/rollup`` as a date-range + group-by
 * report. The endpoint joins ``spend_records`` against
 * ``invocation_subjects`` (Phase 2 attribution column) so rows always
 * carry the resolved billable identity.
 *
 * UI shape:
 *   * Date range pickers (``<input type="date">``) seeded with last 30
 *     days.
 *   * Group-by toggle (User / App / Team).
 *   * Table with columns appropriate for the active grouping. Tabular
 *     numerals for the total column so sorting visually aligns.
 *   * Footer with the grand total across all rows in the window.
 *
 * The page is superuser-only at the API level. The route guard at
 * App.tsx (admin routes are siblings of /admin/marketplace) inherits the
 * existing auth dependency — no additional client-side auth check.
 */

const DEFAULT_DAYS = 30;

function isoDate(date: Date): string {
  // YYYY-MM-DD — what <input type="date"> expects.
  const y = date.getUTCFullYear();
  const m = String(date.getUTCMonth() + 1).padStart(2, '0');
  const d = String(date.getUTCDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

function startOfDayIso(d: string): string {
  return `${d}T00:00:00Z`;
}

function endOfDayIso(d: string): string {
  return `${d}T23:59:59Z`;
}

export default function SpendDashboard() {
  const today = useMemo(() => new Date(), []);
  const monthAgo = useMemo(() => {
    const d = new Date(today);
    d.setUTCDate(d.getUTCDate() - DEFAULT_DAYS);
    return d;
  }, [today]);

  const [start, setStart] = useState(isoDate(monthAgo));
  const [end, setEnd] = useState(isoDate(today));
  const [groupBy, setGroupBy] = useState<SpendRollupGroupBy>('user');
  const [data, setData] = useState<SpendRollupResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    adminSpendApi
      .rollup({
        start: startOfDayIso(start),
        end: endOfDayIso(end),
        group_by: groupBy,
      })
      .then((resp) => {
        if (cancelled) return;
        setData(resp);
      })
      .catch((err: { response?: { data?: { detail?: string } }; message?: string }) => {
        if (cancelled) return;
        const msg =
          err?.response?.data?.detail ?? err?.message ?? 'Failed to load spend rollup';
        setError(msg);
        toast.error(msg);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [start, end, groupBy]);

  return (
    <div className="p-4 md:p-6 max-w-[1200px] mx-auto">
      <header className="mb-4">
        <h1 className="text-base font-semibold text-[var(--text)]">
          Spend rollup
        </h1>
        <p className="text-xs text-[var(--text-subtle)] mt-1">
          Aggregated <code>spend_records</code> joined through{' '}
          <code>invocation_subjects</code>. Unattributed rows are excluded.
        </p>
      </header>

      <div className="flex flex-wrap items-end gap-3 mb-5 p-3 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)]">
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-[var(--text-subtle)]">Start</span>
          <input
            type="date"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            className="h-8 px-2 bg-[var(--bg)] border border-[var(--border)] rounded-[var(--radius-small)] text-xs text-[var(--text)]"
            data-testid="spend-start"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-[var(--text-subtle)]">End</span>
          <input
            type="date"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            className="h-8 px-2 bg-[var(--bg)] border border-[var(--border)] rounded-[var(--radius-small)] text-xs text-[var(--text)]"
            data-testid="spend-end"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-[var(--text-subtle)]">Group by</span>
          <select
            value={groupBy}
            onChange={(e) => setGroupBy(e.target.value as SpendRollupGroupBy)}
            className="h-8 px-2 bg-[var(--bg)] border border-[var(--border)] rounded-[var(--radius-small)] text-xs text-[var(--text)]"
            data-testid="spend-group-by"
          >
            <option value="user">User</option>
            <option value="app">App</option>
            <option value="team">Team</option>
          </select>
        </label>
        <div className="flex-1" />
        <span className="text-[11px] text-[var(--text-subtle)]">
          {loading ? 'Loading…' : data ? `${data.rows.length} rows` : ''}
        </span>
      </div>

      {error && (
        <div
          role="alert"
          className="mb-4 p-3 rounded-[var(--radius-small)] border border-[var(--status-error)]/40 bg-[var(--status-error)]/10 text-xs text-[var(--text)]"
        >
          {error}
        </div>
      )}

      <div className="overflow-x-auto rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)]">
        <table className="w-full text-xs">
          <thead className="text-left text-[var(--text-subtle)] bg-[var(--surface-hover)]">
            <tr>
              {groupBy === 'user' && (
                <>
                  <th className="px-3 py-2 font-medium">User email</th>
                  <th className="px-3 py-2 font-medium font-mono">User ID</th>
                </>
              )}
              {groupBy === 'app' && (
                <>
                  <th className="px-3 py-2 font-medium">App name</th>
                  <th className="px-3 py-2 font-medium font-mono">Instance ID</th>
                </>
              )}
              {groupBy === 'team' && (
                <th className="px-3 py-2 font-medium font-mono">Team ID</th>
              )}
              <th
                className="px-3 py-2 font-medium text-right"
                style={{ fontVariantNumeric: 'tabular-nums' }}
              >
                Total (USD)
              </th>
            </tr>
          </thead>
          <tbody>
            {data?.rows.length === 0 && (
              <tr>
                <td
                  colSpan={groupBy === 'team' ? 2 : 3}
                  className="px-3 py-4 text-center text-[var(--text-subtle)]"
                >
                  No spend records in this window.
                </td>
              </tr>
            )}
            {data?.rows.map((row) => (
              <SpendRow key={rowKey(row, groupBy)} row={row} groupBy={groupBy} />
            ))}
          </tbody>
          {data && (
            <tfoot className="bg-[var(--surface-hover)]">
              <tr>
                <td
                  className="px-3 py-2 font-medium text-[var(--text)]"
                  colSpan={groupBy === 'team' ? 1 : 2}
                >
                  Total
                </td>
                <td
                  className="px-3 py-2 font-mono font-semibold text-right text-[var(--text)]"
                  style={{ fontVariantNumeric: 'tabular-nums' }}
                  data-testid="spend-grand-total"
                >
                  ${data.totals.all_users_usd}
                </td>
              </tr>
            </tfoot>
          )}
        </table>
      </div>
    </div>
  );
}

function rowKey(row: SpendRollupRow, groupBy: SpendRollupGroupBy): string {
  if (groupBy === 'user') return row.user_id ?? '__null__';
  if (groupBy === 'app') return row.app_instance_id ?? '__null__';
  return row.team_id ?? '__null__';
}

function SpendRow({
  row,
  groupBy,
}: {
  row: SpendRollupRow;
  groupBy: SpendRollupGroupBy;
}) {
  return (
    <tr className="border-t border-[var(--border)] hover:bg-[var(--surface-hover)]">
      {groupBy === 'user' && (
        <>
          <td className="px-3 py-2 text-[var(--text)]">
            {row.user_email ?? '—'}
          </td>
          <td className="px-3 py-2 font-mono text-[10px] text-[var(--text-subtle)] truncate max-w-[260px]">
            {row.user_id ?? '—'}
          </td>
        </>
      )}
      {groupBy === 'app' && (
        <>
          <td className="px-3 py-2 text-[var(--text)]">{row.app_name ?? '—'}</td>
          <td className="px-3 py-2 font-mono text-[10px] text-[var(--text-subtle)] truncate max-w-[260px]">
            {row.app_instance_id ?? '—'}
          </td>
        </>
      )}
      {groupBy === 'team' && (
        <td className="px-3 py-2 font-mono text-[10px] text-[var(--text-subtle)] truncate max-w-[260px]">
          {row.team_id ?? '—'}
        </td>
      )}
      <td
        className="px-3 py-2 font-mono text-right text-[var(--text)]"
        style={{ fontVariantNumeric: 'tabular-nums' }}
      >
        ${row.total_usd}
      </td>
    </tr>
  );
}
