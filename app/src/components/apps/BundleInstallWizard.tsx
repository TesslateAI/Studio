import { useEffect, useMemo, useState } from 'react';
import { X, CheckCircle, XCircle } from '@phosphor-icons/react';
import toast from 'react-hot-toast';
import {
  appBundlesApi,
  appVersionsApi,
  type AppVersionDetail,
  type BundleDetail,
  type BundleInstallResult,
} from '../../lib/api';
import { useTeam } from '../../contexts/TeamContext';

/**
 * BundleInstallWizard — modal for installing a MarketplaceApp bundle.
 *
 * Aggregates wallet + MCP consent across selected items. Honors `required`
 * items (can't be disabled) and `default_enabled` defaults.
 *
 * Backend returns 207 Multi-Status (`succeeded[]` + `failed[]`); we render
 * a per-item summary after the install attempt.
 */

export interface BundleInstallWizardProps {
  bundleId: string;
  onClose: () => void;
  onDone: () => void;
  /** Initial step for testing. */
  initialStep?: WizardStep;
}

type WizardStep = 1 | 2 | 3 | 4 | 5;

interface BillingDim {
  dimension: string;
  payer: string;
}
interface McpDecl {
  name: string;
  scopes: string[];
}

function parseBilling(manifest: Record<string, unknown> | null): BillingDim[] {
  if (!manifest) return [];
  const billing = manifest.billing;
  if (!billing || typeof billing !== 'object') return [];
  const out: BillingDim[] = [];
  for (const [dimension, raw] of Object.entries(billing as Record<string, unknown>)) {
    if (raw && typeof raw === 'object') {
      const b = raw as Record<string, unknown>;
      out.push({
        dimension,
        payer: typeof b.payer === 'string' ? b.payer : 'installer',
      });
    }
  }
  return out;
}

function parseMcp(manifest: Record<string, unknown> | null): McpDecl[] {
  if (!manifest) return [];
  const mcp = manifest.mcp;
  if (!Array.isArray(mcp)) return [];
  const out: McpDecl[] = [];
  for (const raw of mcp) {
    if (raw && typeof raw === 'object') {
      const m = raw as Record<string, unknown>;
      out.push({
        name: typeof m.name === 'string' ? m.name : 'unnamed',
        scopes: Array.isArray(m.scopes) ? (m.scopes as string[]) : [],
      });
    }
  }
  return out;
}

export function BundleInstallWizard({
  bundleId,
  onClose,
  onDone,
  initialStep = 1,
}: BundleInstallWizardProps) {
  const { teams, activeTeam } = useTeam();

  const [step, setStep] = useState<WizardStep>(initialStep);
  const [bundle, setBundle] = useState<BundleDetail | null>(null);
  const [versionDetails, setVersionDetails] = useState<
    Record<string, AppVersionDetail | null>
  >({});
  const [enabled, setEnabled] = useState<Record<string, boolean>>({});
  const [walletAccepted, setWalletAccepted] = useState(false);
  const [mcpAccepted, setMcpAccepted] = useState<Record<string, boolean>>({});
  const [teamId, setTeamId] = useState(activeTeam?.id ?? '');

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<BundleInstallResult | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const b = await appBundlesApi.get(bundleId);
        if (cancelled) return;
        setBundle(b);
        const defaults: Record<string, boolean> = {};
        for (const it of b.items) defaults[it.app_version_id] = it.default_enabled || it.required;
        setEnabled(defaults);
        // fetch version details (best-effort)
        const pairs = await Promise.all(
          b.items.map(async (it) => {
            try {
              const v = await appVersionsApi.get(it.app_version_id);
              return [it.app_version_id, v] as const;
            } catch {
              return [it.app_version_id, null] as const;
            }
          })
        );
        if (cancelled) return;
        const vmap: Record<string, AppVersionDetail | null> = {};
        for (const [id, v] of pairs) vmap[id] = v;
        setVersionDetails(vmap);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load bundle');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [bundleId]);

  const selectedItems = useMemo(
    () => (bundle ? bundle.items.filter((it) => enabled[it.app_version_id]) : []),
    [bundle, enabled]
  );

  const aggregatedBilling = useMemo(() => {
    const map = new Map<string, BillingDim>();
    for (const it of selectedItems) {
      const v = versionDetails[it.app_version_id];
      for (const b of parseBilling(v?.manifest_json ?? null)) {
        const key = `${b.dimension}:${b.payer}`;
        if (!map.has(key)) map.set(key, b);
      }
    }
    return [...map.values()];
  }, [selectedItems, versionDetails]);

  const aggregatedMcp = useMemo(() => {
    const map = new Map<string, McpDecl>();
    for (const it of selectedItems) {
      const v = versionDetails[it.app_version_id];
      for (const m of parseMcp(v?.manifest_json ?? null)) {
        if (!map.has(m.name)) {
          map.set(m.name, m);
        } else {
          const existing = map.get(m.name)!;
          map.set(m.name, {
            name: m.name,
            scopes: Array.from(new Set([...existing.scopes, ...m.scopes])),
          });
        }
      }
    }
    return [...map.values()];
  }, [selectedItems, versionDetails]);

  const allMcpAccepted =
    aggregatedMcp.length === 0 || aggregatedMcp.every((d) => mcpAccepted[d.name]);

  const canAdvance = (): boolean => {
    if (loading) return false;
    switch (step) {
      case 1:
        return selectedItems.length > 0;
      case 2:
        return walletAccepted;
      case 3:
        return allMcpAccepted;
      case 4:
        return !!teamId;
      default:
        return true;
    }
  };

  const toggle = (it: BundleDetail['items'][number]) => {
    if (it.required) return;
    setEnabled((m) => ({ ...m, [it.app_version_id]: !m[it.app_version_id] }));
  };

  const confirm = async () => {
    if (!bundle || !teamId) return;
    setSubmitting(true);
    try {
      const res = await appBundlesApi.install(bundle.id, {
        team_id: teamId,
        installs: selectedItems.map((it) => ({
          app_version_id: it.app_version_id,
          wallet_mix_consent: { accepted: true },
          mcp_consents: aggregatedMcp.map((m) => ({
            name: m.name,
            scopes: m.scopes,
            accepted: mcpAccepted[m.name] === true,
          })),
        })),
      });
      setResult(res);
      if (res.failed.length === 0) {
        toast.success(`Installed ${res.succeeded.length} app${res.succeeded.length === 1 ? '' : 's'}`);
      } else {
        toast.error(`${res.failed.length} item(s) failed to install`);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Bundle install failed');
    } finally {
      setSubmitting(false);
    }
  };

  const titles: Record<WizardStep, string> = {
    1: 'Select items',
    2: 'Wallet & billing',
    3: 'MCP access',
    4: 'Team',
    5: result ? 'Install results' : 'Review',
  };

  const body = (() => {
    if (loading) return <p>Loading bundle…</p>;
    if (error) return <p className="text-[var(--danger, #c00)]">{error}</p>;
    if (!bundle) return null;

    if (result) {
      return (
        <div className="flex flex-col gap-3" data-testid="result-step">
          {result.succeeded.map((s) => (
            <div
              key={s.app_version_id}
              className="flex items-center gap-2 p-2 border border-[var(--border)] rounded-[var(--radius-small)]"
            >
              <CheckCircle size={16} className="text-[var(--success, #0a0)]" />
              <span className="text-xs font-mono">{s.app_version_id.slice(0, 8)}</span>
              <span className="flex-1" />
              <span className="text-[10px] text-[var(--text-subtle)]">installed</span>
            </div>
          ))}
          {result.failed.map((f) => (
            <div
              key={f.app_version_id}
              className="flex items-start gap-2 p-2 border border-[var(--border)] rounded-[var(--radius-small)]"
            >
              <XCircle size={16} className="text-[var(--danger, #c00)]" />
              <div className="flex-1 min-w-0">
                <div className="text-xs font-mono">{f.app_version_id.slice(0, 8)}</div>
                <div className="text-[10px] text-[var(--text-subtle)] break-words">{f.error}</div>
              </div>
            </div>
          ))}
          {result.note && <p className="text-[10px] text-[var(--text-subtle)]">{result.note}</p>}
        </div>
      );
    }

    if (step === 1) {
      return (
        <div className="flex flex-col gap-2" data-testid="items-step">
          <p className="text-xs mb-1">
            {bundle.display_name} — {bundle.items.length} items
          </p>
          {bundle.items.map((it) => {
            const v = versionDetails[it.app_version_id];
            const isEnabled = !!enabled[it.app_version_id];
            return (
              <label
                key={it.app_version_id}
                className={`flex items-center gap-2 p-2 border border-[var(--border)] rounded-[var(--radius-small)] ${
                  it.required ? 'opacity-75' : 'cursor-pointer hover:bg-[var(--surface-hover)]'
                }`}
              >
                <input
                  type="checkbox"
                  checked={isEnabled}
                  disabled={it.required}
                  onChange={() => toggle(it)}
                  data-testid={`item-toggle-${it.app_version_id}`}
                />
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-mono text-[var(--text)]">
                    {v?.version ? `v${v.version}` : it.app_version_id.slice(0, 8)}
                  </div>
                  <div className="text-[10px] text-[var(--text-subtle)]">
                    {it.required ? 'required' : it.default_enabled ? 'default: on' : 'optional'}
                  </div>
                </div>
              </label>
            );
          })}
        </div>
      );
    }

    if (step === 2) {
      return (
        <div className="flex flex-col gap-3" data-testid="wallet-step">
          {aggregatedBilling.length === 0 ? (
            <p className="text-xs">No billing dimensions across selected items.</p>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-[var(--text-subtle)]">
                  <th className="py-1">Dimension</th>
                  <th className="py-1">Payer</th>
                </tr>
              </thead>
              <tbody>
                {aggregatedBilling.map((b) => (
                  <tr key={`${b.dimension}:${b.payer}`} className="border-t border-[var(--border)]">
                    <td className="py-1 font-mono">{b.dimension}</td>
                    <td className="py-1">{b.payer}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <label className="flex items-center gap-2 mt-2">
            <input
              type="checkbox"
              checked={walletAccepted}
              onChange={(e) => setWalletAccepted(e.target.checked)}
            />
            <span>I understand and accept these billing terms across all selected items.</span>
          </label>
        </div>
      );
    }

    if (step === 3) {
      return (
        <div className="flex flex-col gap-2" data-testid="mcp-step">
          {aggregatedMcp.length === 0 ? (
            <p className="text-xs">No MCP servers requested.</p>
          ) : (
            aggregatedMcp.map((d) => (
              <label
                key={d.name}
                className="flex items-start gap-2 p-2 border border-[var(--border)] rounded-[var(--radius-small)]"
              >
                <input
                  type="checkbox"
                  checked={!!mcpAccepted[d.name]}
                  onChange={(e) =>
                    setMcpAccepted((m) => ({ ...m, [d.name]: e.target.checked }))
                  }
                />
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-semibold text-[var(--text)]">{d.name}</div>
                  <div className="text-[10px] text-[var(--text-subtle)]">
                    scopes: {d.scopes.join(', ') || '(none)'}
                  </div>
                </div>
              </label>
            ))
          )}
        </div>
      );
    }

    if (step === 4) {
      return (
        <label className="flex flex-col gap-1 text-xs" data-testid="team-step">
          <span className="text-[var(--text-subtle)]">Install to team</span>
          <select
            className="h-8 px-2 bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius-small)] text-sm text-[var(--text)]"
            value={teamId}
            onChange={(e) => setTeamId(e.target.value)}
          >
            <option value="">— select a team —</option>
            {teams.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </label>
      );
    }

    return (
      <div className="flex flex-col gap-2 text-xs" data-testid="review-step">
        <div>
          <span className="text-[var(--text-subtle)]">Items to install:</span>{' '}
          {selectedItems.length}
        </div>
        <div>
          <span className="text-[var(--text-subtle)]">Billing dimensions:</span>{' '}
          {aggregatedBilling.length}
        </div>
        <div>
          <span className="text-[var(--text-subtle)]">MCP servers accepted:</span>{' '}
          {aggregatedMcp.length}
        </div>
        <div>
          <span className="text-[var(--text-subtle)]">Team:</span>{' '}
          {teams.find((t) => t.id === teamId)?.name ?? '—'}
        </div>
      </div>
    );
  })();

  const footer = (() => {
    if (result) {
      return (
        <>
          <div className="flex-1" />
          <button className="btn btn-filled" onClick={onDone}>
            Done
          </button>
        </>
      );
    }
    return (
      <>
        {step > 1 && (
          <button
            className="btn"
            onClick={() => setStep((s) => (s > 1 ? ((s - 1) as WizardStep) : s))}
            disabled={submitting}
          >
            Back
          </button>
        )}
        <div className="flex-1" />
        <button className="btn" onClick={onClose} disabled={submitting}>
          Cancel
        </button>
        {step < 5 ? (
          <button
            className="btn btn-filled"
            onClick={() => setStep((s) => (s < 5 ? ((s + 1) as WizardStep) : s))}
            disabled={!canAdvance()}
          >
            Next
          </button>
        ) : (
          <button
            className="btn btn-filled"
            onClick={confirm}
            disabled={submitting || selectedItems.length === 0}
          >
            {submitting ? 'Installing…' : 'Install bundle'}
          </button>
        )}
      </>
    );
  })();

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Install bundle"
    >
      <div className="w-full max-w-xl bg-[var(--bg)] border border-[var(--border)] rounded-[var(--radius)] shadow-xl flex flex-col max-h-[90vh]">
        <div className="flex items-center gap-3 p-4 border-b border-[var(--border)]">
          <div className="flex-1">
            <h2 className="text-sm font-semibold text-[var(--text)]">{titles[step]}</h2>
            {!result && (
              <p className="text-[10px] text-[var(--text-subtle)]">Step {step} of 5</p>
            )}
          </div>
          <button className="btn btn-sm" onClick={onClose} aria-label="Close">
            <X size={14} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-4 text-sm text-[var(--text-muted)]">{body}</div>
        <div className="flex items-center gap-2 p-4 border-t border-[var(--border)]">{footer}</div>
      </div>
    </div>
  );
}

export default BundleInstallWizard;
