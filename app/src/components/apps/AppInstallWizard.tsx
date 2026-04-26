import { useCallback, useEffect, useMemo, useState } from 'react';
import { X, Warning } from '@phosphor-icons/react';
import toast from 'react-hot-toast';
import {
  appVersionsApi,
  type AppVersionDetail,
  type CompatReport,
  type UpdatePolicy,
} from '../../lib/api';
import { useApps } from '../../contexts/AppsContext';
import { useTeam } from '../../contexts/TeamContext';

/**
 * AppInstallWizard — multi-step modal to install an AppVersion.
 *
 * Steps:
 *   1. Compatibility — GET /api/app-versions/{id}/compat; blocks if !compatible.
 *   2. Wallet consent — creator-defined billing dimensions; user acks.
 *   3. Connector consent — per-declaration scope + exposure accept (manifest
 *      2026-05: connectors[] with exposure=proxy|env). exposure=env warns the
 *      user that raw credentials will be injected into the app container.
 *   4. Team + options — teamId + update_policy.
 *   5. Review + confirm — install via useApps().installApp.
 */

export interface AppInstallWizardProps {
  appVersionId: string;
  onClose: () => void;
  onDone: (appInstanceId: string) => void;
  /** Override step for testing. Not used in production. */
  initialStep?: WizardStep;
}

type WizardStep = 1 | 2 | 3 | 4 | 5;

interface BillingDim {
  dimension: string;
  payer: string;
  cap_usd?: number | null;
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
  const dims: BillingDim[] = [];
  for (const [dimension, raw] of Object.entries(billing as Record<string, unknown>)) {
    if (raw && typeof raw === 'object') {
      const b = raw as Record<string, unknown>;
      dims.push({
        dimension,
        payer: typeof b.payer === 'string' ? b.payer : 'installer',
        cap_usd: typeof b.cap_usd === 'number' ? b.cap_usd : null,
      });
    }
  }
  return dims;
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

function Shell({
  onClose,
  step,
  total,
  title,
  children,
  footer,
}: {
  onClose: () => void;
  step: number;
  total: number;
  title: string;
  children: React.ReactNode;
  footer: React.ReactNode;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Install app"
    >
      <div className="w-full max-w-xl bg-[var(--bg)] border border-[var(--border)] rounded-[var(--radius)] shadow-xl flex flex-col max-h-[90vh]">
        <div className="flex items-center gap-3 p-4 border-b border-[var(--border)]">
          <div className="flex-1">
            <h2 className="text-sm font-semibold text-[var(--text)]">{title}</h2>
            <p className="text-[10px] text-[var(--text-subtle)]">
              Step {step} of {total}
            </p>
          </div>
          <button className="btn btn-sm" onClick={onClose} aria-label="Close">
            <X size={14} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-4 text-sm text-[var(--text-muted)]">
          {children}
        </div>
        <div className="flex items-center gap-2 p-4 border-t border-[var(--border)]">{footer}</div>
      </div>
    </div>
  );
}

export function AppInstallWizard({
  appVersionId,
  onClose,
  onDone,
  initialStep = 1,
}: AppInstallWizardProps) {
  const { installApp } = useApps();
  const { teams, activeTeam } = useTeam();

  const [step, setStep] = useState<WizardStep>(initialStep);
  const [version, setVersion] = useState<AppVersionDetail | null>(null);
  const [compat, setCompat] = useState<CompatReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [walletAccepted, setWalletAccepted] = useState(false);
  const [connectorAccepted, setConnectorAccepted] = useState<Record<string, boolean>>({});
  const [teamId, setTeamId] = useState<string>(activeTeam?.id ?? '');
  const [updatePolicy, setUpdatePolicy] = useState<UpdatePolicy>('manual');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const [v, c] = await Promise.all([
          appVersionsApi.get(appVersionId),
          appVersionsApi.compat(appVersionId),
        ]);
        if (cancelled) return;
        setVersion(v);
        setCompat(c);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : 'Failed to load version');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [appVersionId]);

  const billingDims = useMemo(
    () => parseBilling(version?.manifest_json ?? null),
    [version]
  );
  const connectorDecls = useMemo(
    () => parseConnectors(version?.manifest_json ?? null),
    [version]
  );

  const allConnectorsAccepted =
    connectorDecls.length === 0 ||
    connectorDecls.every((d) => connectorAccepted[d.id]);

  const acceptAllConnectors = () => {
    const next: Record<string, boolean> = {};
    for (const d of connectorDecls) next[d.id] = true;
    setConnectorAccepted(next);
  };

  const goNext = () => setStep((s) => (s < 5 ? ((s + 1) as WizardStep) : s));
  const goBack = () => setStep((s) => (s > 1 ? ((s - 1) as WizardStep) : s));

  const canAdvance = useCallback((): boolean => {
    if (loading) return false;
    switch (step) {
      case 1:
        return !!compat?.compatible;
      case 2:
        return walletAccepted;
      case 3:
        return allConnectorsAccepted;
      case 4:
        return !!teamId;
      default:
        return true;
    }
  }, [step, loading, compat, walletAccepted, allConnectorsAccepted, teamId]);

  const confirm = async () => {
    if (!teamId) {
      toast.error('Select a team');
      return;
    }
    setSubmitting(true);
    try {
      // Canonical flat consent shape. Backend _consent_matches_billing is
      // tolerant of older nested/dimensions shapes, but new clients send the
      // flat form keyed by dimension with the full BillingDim object (or null
      // if the manifest doesn't declare that dim).
      const walletMix: Record<string, unknown> = { accepted: true };
      for (const key of ['ai_compute', 'general_compute', 'platform_fee'] as const) {
        const entry = billingDims.find((d) => d.dimension === key);
        if (entry) walletMix[key] = entry;
      }
      const result = await installApp({
        app_version_id: appVersionId,
        team_id: teamId,
        wallet_mix_consent: walletMix,
        // Backend wire contract still keys this field as `mcp_consents` for
        // back-compat. Each entry now carries the full connector descriptor
        // (id, kind, exposure, scopes) so the orchestrator can record exactly
        // which exposure mode the installer agreed to.
        mcp_consents: connectorDecls.map((d) => ({
          id: d.id,
          name: d.id,
          kind: d.kind,
          exposure: d.exposure,
          scopes: d.scopes,
          accepted: connectorAccepted[d.id] === true,
        })),
        update_policy: updatePolicy,
      });
      onDone(result.app_instance_id);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Install failed';
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const titles: Record<WizardStep, string> = {
    1: 'Compatibility',
    2: 'Wallet & billing',
    3: 'Connectors & access',
    4: 'Team & policy',
    5: 'Review',
  };

  const body = (() => {
    if (loading) return <p>Loading…</p>;
    if (error) return <p className="text-[var(--danger, #c00)]">{error}</p>;

    if (step === 1) {
      if (!compat) return <p>Loading compatibility…</p>;
      return (
        <div className="flex flex-col gap-3" data-testid="compat-step">
          <p className={compat.compatible ? 'text-[var(--text)]' : 'text-[var(--danger, #c00)]'}>
            {compat.compatible
              ? 'This app is compatible with your server.'
              : 'This app is not compatible with your server.'}
          </p>
          {compat.unsupported_manifest_schema && (
            <p className="text-xs">Unsupported manifest schema.</p>
          )}
          {compat.missing_features.length > 0 && (
            <div>
              <p className="text-xs font-semibold mb-1">Missing features:</p>
              <ul className="text-xs list-disc pl-5">
                {compat.missing_features.map((f) => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      );
    }

    if (step === 2) {
      return (
        <div className="flex flex-col gap-3" data-testid="wallet-step">
          {billingDims.length === 0 ? (
            <p className="text-xs">This app declares no billing dimensions.</p>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-[var(--text-subtle)]">
                  <th className="py-1">Dimension</th>
                  <th className="py-1">Payer</th>
                  <th className="py-1">Cap</th>
                </tr>
              </thead>
              <tbody>
                {billingDims.map((d) => (
                  <tr key={d.dimension} className="border-t border-[var(--border)]">
                    <td className="py-1 font-mono">{d.dimension}</td>
                    <td className="py-1">{d.payer}</td>
                    <td className="py-1">{d.cap_usd != null ? `$${d.cap_usd}` : '—'}</td>
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
            <span>I understand and accept these billing terms.</span>
          </label>
        </div>
      );
    }

    if (step === 3) {
      return (
        <div className="flex flex-col gap-3" data-testid="mcp-step">
          {connectorDecls.length === 0 ? (
            <p className="text-xs">This app requests no connectors.</p>
          ) : (
            <>
              <div className="flex items-center justify-between">
                <p className="text-xs">
                  Review each connector's access mode and scopes:
                </p>
                <button type="button" className="btn btn-sm" onClick={acceptAllConnectors}>
                  Accept all
                </button>
              </div>
              {connectorDecls.map((d) => (
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
        <div className="flex flex-col gap-3" data-testid="team-step">
          <label className="flex flex-col gap-1 text-xs">
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
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-[var(--text-subtle)]">Update policy</span>
            <select
              className="h-8 px-2 bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius-small)] text-sm text-[var(--text)]"
              value={updatePolicy}
              onChange={(e) => setUpdatePolicy(e.target.value as UpdatePolicy)}
            >
              <option value="manual">Manual</option>
              <option value="patch">Auto-update patch versions</option>
              <option value="minor">Auto-update minor versions</option>
            </select>
          </label>
        </div>
      );
    }

    // step 5
    const teamName = teams.find((t) => t.id === teamId)?.name ?? '—';
    return (
      <div className="flex flex-col gap-2 text-xs" data-testid="review-step">
        <div>
          <span className="text-[var(--text-subtle)]">Version:</span>{' '}
          <span className="font-mono">{version?.version}</span>
        </div>
        <div>
          <span className="text-[var(--text-subtle)]">Team:</span> {teamName}
        </div>
        <div>
          <span className="text-[var(--text-subtle)]">Update policy:</span> {updatePolicy}
        </div>
        <div>
          <span className="text-[var(--text-subtle)]">Billing dimensions:</span>{' '}
          {billingDims.length}
        </div>
        <div>
          <span className="text-[var(--text-subtle)]">Connectors accepted:</span>{' '}
          {connectorDecls.length}
          {connectorDecls.some((d) => d.exposure === 'env') && (
            <span className="ml-2 inline-flex items-center gap-1 text-amber-400">
              <Warning size={12} weight="fill" />
              {connectorDecls.filter((d) => d.exposure === 'env').length} use env-injected
              credentials
            </span>
          )}
        </div>
      </div>
    );
  })();

  const footer = (
    <>
      {step > 1 && (
        <button className="btn" onClick={goBack} disabled={submitting}>
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
          onClick={goNext}
          disabled={!canAdvance()}
          data-testid="wizard-next"
        >
          Next
        </button>
      ) : (
        <button
          className="btn btn-filled"
          onClick={confirm}
          disabled={submitting || !teamId}
        >
          {submitting ? 'Installing…' : 'Install'}
        </button>
      )}
    </>
  );

  return (
    <Shell onClose={onClose} step={step} total={5} title={titles[step]} footer={footer}>
      {body}
    </Shell>
  );
}

export default AppInstallWizard;
