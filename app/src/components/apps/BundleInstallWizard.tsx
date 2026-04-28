import { useEffect, useMemo, useState } from 'react';
import { X, CheckCircle, XCircle, Warning } from '@phosphor-icons/react';
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
 * Aggregates wallet + connector consent across selected items (manifest
 * 2026-05: connectors[] with exposure=proxy|env). Honors `required` items
 * (can't be disabled) and `default_enabled` defaults. exposure=env warns
 * the user that raw credentials will be injected into the app container.
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

type ConnectorKind = 'mcp' | 'api_key' | 'oauth' | 'webhook';
type ConnectorExposure = 'proxy' | 'env';

interface ConnectorDecl {
  id: string;
  kind: ConnectorKind;
  scopes: string[];
  /** Per manifest 2026-05: 'proxy' routes calls through the platform Connector
   *  Proxy (token never leaves the platform); 'env' injects the raw credential
   *  as a container env var so the app can use it directly. */
  exposure: ConnectorExposure;
  required: boolean;
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

function parseConnectors(manifest: Record<string, unknown> | null): ConnectorDecl[] {
  // Manifest 2026-05: connectors live in `manifest.connectors[]`. The legacy
  // `manifest.mcp` field has been removed entirely — Phase 1's hard reset
  // forces all installs to re-run through this wizard against the new schema.
  if (!manifest) return [];
  const connectors = manifest.connectors;
  if (!Array.isArray(connectors)) return [];
  const out: ConnectorDecl[] = [];
  const validKinds: ConnectorKind[] = ['mcp', 'api_key', 'oauth', 'webhook'];
  for (const raw of connectors) {
    if (raw && typeof raw === 'object') {
      const c = raw as Record<string, unknown>;
      const kindRaw = typeof c.kind === 'string' ? c.kind : 'api_key';
      const kind: ConnectorKind = (validKinds as string[]).includes(kindRaw)
        ? (kindRaw as ConnectorKind)
        : 'api_key';
      const exposureRaw = typeof c.exposure === 'string' ? c.exposure : 'proxy';
      const exposure: ConnectorExposure = exposureRaw === 'env' ? 'env' : 'proxy';
      out.push({
        id: typeof c.id === 'string' ? c.id : 'unnamed',
        kind,
        scopes: Array.isArray(c.scopes) ? (c.scopes as string[]) : [],
        exposure,
        required: typeof c.required === 'boolean' ? c.required : true,
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
  const [connectorAccepted, setConnectorAccepted] = useState<Record<string, boolean>>({});
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

  const aggregatedConnectors = useMemo(() => {
    const map = new Map<string, ConnectorDecl>();
    for (const it of selectedItems) {
      const v = versionDetails[it.app_version_id];
      for (const c of parseConnectors(v?.manifest_json ?? null)) {
        const existing = map.get(c.id);
        if (!existing) {
          map.set(c.id, c);
        } else {
          // Merge scopes; if any declaration uses env exposure, the aggregate
          // is env (more invasive — installer must consent to the worst case).
          map.set(c.id, {
            id: c.id,
            kind: existing.kind,
            scopes: Array.from(new Set([...existing.scopes, ...c.scopes])),
            exposure:
              existing.exposure === 'env' || c.exposure === 'env' ? 'env' : 'proxy',
            required: existing.required || c.required,
          });
        }
      }
    }
    return [...map.values()];
  }, [selectedItems, versionDetails]);

  const allConnectorsAccepted =
    aggregatedConnectors.length === 0 ||
    aggregatedConnectors.every((d) => connectorAccepted[d.id]);

  const canAdvance = (): boolean => {
    if (loading) return false;
    switch (step) {
      case 1:
        return selectedItems.length > 0;
      case 2:
        return walletAccepted;
      case 3:
        return allConnectorsAccepted;
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
          // Backend wire contract still keys this field as `mcp_consents` for
          // back-compat. Each entry now carries the full connector descriptor
          // (id, kind, exposure, scopes) so the orchestrator can record exactly
          // which exposure mode the installer agreed to. Matches AppInstallWizard.
          mcp_consents: aggregatedConnectors.map((d) => ({
            id: d.id,
            name: d.id,
            kind: d.kind,
            exposure: d.exposure,
            scopes: d.scopes,
            accepted: connectorAccepted[d.id] === true,
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
    3: 'Connectors & access',
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
        <div className="flex flex-col gap-3" data-testid="mcp-step">
          {aggregatedConnectors.length === 0 ? (
            <p className="text-xs">No connectors requested across selected items.</p>
          ) : (
            <>
              <p className="text-xs">
                Review each connector's access mode and scopes (aggregated
                across selected items):
              </p>
              {aggregatedConnectors.map((d) => (
                <div
                  key={d.id}
                  className="p-3 border border-[var(--border)] rounded-[var(--radius-small)] flex flex-col gap-2"
                  data-testid={`connector-${d.id}`}
                >
                  <div className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={!!connectorAccepted[d.id]}
                      onChange={(e) =>
                        setConnectorAccepted((m) => ({ ...m, [d.id]: e.target.checked }))
                      }
                    />
                    <span className="font-semibold text-[var(--text)]">{d.id}</span>
                    <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded border border-[var(--border)] text-[var(--text-subtle)]">
                      {d.kind}
                    </span>
                    {d.exposure === 'proxy' ? (
                      <span
                        className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/30 text-emerald-400"
                        title="Calls route through the platform Connector Proxy. Your token never reaches this app."
                      >
                        Proxied
                      </span>
                    ) : (
                      <span
                        className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-amber-500/10 border border-amber-500/30 text-amber-400"
                        title="The raw credential will be injected into this app's container as an environment variable."
                      >
                        Env
                      </span>
                    )}
                  </div>
                  <p className="text-[11px] text-[var(--text-subtle)]">
                    scopes: {d.scopes.join(', ') || '(none)'}
                  </p>
                  {d.exposure === 'proxy' ? (
                    <p className="text-[11px] text-[var(--text-subtle)]">
                      Proxied — your token stays on the platform; this app calls
                      it through the Connector Proxy.
                    </p>
                  ) : (
                    <div
                      role="alert"
                      className="flex items-start gap-2 rounded-[var(--radius-small)] bg-amber-500/10 border border-amber-500/30 p-2"
                    >
                      <Warning
                        size={14}
                        weight="fill"
                        className="text-amber-400 mt-0.5 flex-shrink-0"
                      />
                      <p className="text-[11px] text-amber-300 leading-snug">
                        This app will receive your raw <span className="font-mono">{d.id}</span>{' '}
                        {d.kind} credential as an environment variable. Only
                        install if you trust the creator.
                      </p>
                    </div>
                  )}
                </div>
              ))}
            </>
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
          <span className="text-[var(--text-subtle)]">Connectors accepted:</span>{' '}
          {aggregatedConnectors.length}
          {aggregatedConnectors.some((d) => d.exposure === 'env') && (
            <span className="ml-2 inline-flex items-center gap-1 text-amber-400">
              <Warning size={12} weight="fill" />
              {aggregatedConnectors.filter((d) => d.exposure === 'env').length} use env-injected
              credentials
            </span>
          )}
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
