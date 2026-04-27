import { useCallback, useEffect, useMemo, useState } from 'react';
import { CaretDown, CaretRight, CheckCircle, X, Warning } from '@phosphor-icons/react';
import toast from 'react-hot-toast';
import {
  appVersionsApi,
  marketplaceAppsApi,
  type AppVersionDetail,
  type CompatReport,
  type UpdatePolicy,
} from '../../lib/api';
import { useApps } from '../../contexts/AppsContext';
import { useTeam } from '../../contexts/TeamContext';
import type {
  AppManifestConnector,
  AppManifestConnectorExposure,
  AppManifestConnectorKind,
  AppManifestDependency,
  AppManifestTenancyModel,
} from '../../types/opensailAppYaml';

/**
 * AppInstallModal — single review screen with collapsible advanced sections.
 *
 * Replaces the legacy multi-step `AppInstallWizard`. UX surface #3 in the
 * plan calls for "one review screen, advanced sections collapse by
 * default" so the install flow is one click for trusted apps and one
 * collapse-expand for power users.
 *
 * Sections:
 *   - Header (always visible): version, billing summary, primary CTA.
 *   - Runtime mode (advanced): per_install / shared_singleton /
 *     per_invocation. Disabled when manifest pins one mode.
 *   - Connections (advanced): per-connector exposure highlight (proxy
 *     badge green, env badge amber + warning banner).
 *   - Modules (advanced): app dependencies the install will recursively
 *     pull in.
 *   - Billing & credits (advanced): per-dimension wallet routing.
 *   - Update policy (advanced): manual / minor / patch.
 *
 * The modal calls the same backend wire contract as the wizard so the
 * install path is unchanged — only the user-facing surface is rewritten.
 */

export interface AppInstallModalProps {
  appVersionId: string;
  onClose: () => void;
  onDone: (appInstanceId: string) => void;
}

interface BillingDim {
  dimension: string;
  payer: string;
  cap_usd?: number | null;
}

interface ConnectorDecl {
  id: string;
  kind: AppManifestConnectorKind;
  scopes: string[];
  exposure: AppManifestConnectorExposure;
  required: boolean;
}

const RUNTIME_MODES: AppManifestTenancyModel[] = [
  'per_install',
  'shared_singleton',
  'per_invocation',
];

function parseBilling(manifest: Record<string, unknown> | null): BillingDim[] {
  if (!manifest) return [];
  const billing = manifest.billing;
  if (!billing || typeof billing !== 'object') return [];
  const out: BillingDim[] = [];
  for (const [dimension, raw] of Object.entries(billing as Record<string, unknown>)) {
    if (raw && typeof raw === 'object') {
      const b = raw as Record<string, unknown>;
      const payer =
        typeof b.payer_default === 'string'
          ? (b.payer_default as string)
          : typeof b.payer === 'string'
            ? (b.payer as string)
            : 'installer';
      out.push({
        dimension,
        payer,
        cap_usd: typeof b.cap_usd === 'number' ? b.cap_usd : null,
      });
    }
  }
  return out;
}

function parseConnectors(manifest: Record<string, unknown> | null): ConnectorDecl[] {
  if (!manifest) return [];
  const connectors = manifest.connectors;
  if (!Array.isArray(connectors)) return [];
  const validKinds: AppManifestConnectorKind[] = ['mcp', 'api_key', 'oauth', 'webhook'];
  const out: ConnectorDecl[] = [];
  for (const raw of connectors) {
    if (!raw || typeof raw !== 'object') continue;
    const c = raw as Partial<AppManifestConnector>;
    const kindRaw = typeof c.kind === 'string' ? c.kind : 'api_key';
    const kind: AppManifestConnectorKind = (validKinds as string[]).includes(kindRaw)
      ? (kindRaw as AppManifestConnectorKind)
      : 'api_key';
    const exposureRaw = typeof c.exposure === 'string' ? c.exposure : 'proxy';
    const exposure: AppManifestConnectorExposure =
      exposureRaw === 'env' ? 'env' : 'proxy';
    out.push({
      id: typeof c.id === 'string' ? c.id : 'unnamed',
      kind,
      scopes: Array.isArray(c.scopes) ? (c.scopes as string[]) : [],
      exposure,
      required: typeof c.required === 'boolean' ? c.required : true,
    });
  }
  return out;
}

function parseDependencies(
  manifest: Record<string, unknown> | null
): AppManifestDependency[] {
  if (!manifest) return [];
  const deps = manifest.dependencies;
  if (!Array.isArray(deps)) return [];
  const out: AppManifestDependency[] = [];
  for (const raw of deps) {
    if (!raw || typeof raw !== 'object') continue;
    const d = raw as Partial<AppManifestDependency>;
    if (typeof d.alias !== 'string' || typeof d.app_id !== 'string') continue;
    out.push({
      alias: d.alias,
      app_id: d.app_id,
      required: typeof d.required === 'boolean' ? d.required : true,
      needs: typeof d.needs === 'object' ? (d.needs ?? undefined) : undefined,
    });
  }
  return out;
}

function parseTenancyMode(
  manifest: Record<string, unknown> | null
): AppManifestTenancyModel | null {
  if (!manifest) return null;
  const runtime = manifest.runtime as Record<string, unknown> | undefined;
  if (!runtime) return null;
  const t = runtime.tenancy_model;
  return (RUNTIME_MODES as string[]).includes(t as string)
    ? (t as AppManifestTenancyModel)
    : null;
}

function CollapsibleSection({
  label,
  count,
  defaultExpanded = false,
  children,
}: {
  label: string;
  count?: number;
  defaultExpanded?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultExpanded);
  return (
    <div className="border border-[var(--border)] rounded-[var(--radius-small)] bg-[var(--surface-hover)]">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-[var(--surface)] transition-colors"
        aria-expanded={open}
        data-testid={`section-${label.toLowerCase().replace(/\s+/g, '-')}`}
      >
        <span className="text-[var(--text-subtle)]">
          {open ? <CaretDown size={12} /> : <CaretRight size={12} />}
        </span>
        <span className="text-xs font-medium text-[var(--text)] flex-1">{label}</span>
        {typeof count === 'number' && (
          <span className="text-[10px] text-[var(--text-subtle)]">{count}</span>
        )}
      </button>
      {open && <div className="px-3 pb-3 pt-1 text-xs">{children}</div>}
    </div>
  );
}

/** Dependency install state — drives the inline "Install" buttons in the
 *  Modules section. Phase 5 recursive composition: parent install button
 *  stays disabled while any required dependency is missing. */
type DependencyState =
  | { status: 'unknown' }
  | { status: 'installed'; appInstanceId: string }
  | { status: 'skipped' };

export function AppInstallModal({
  appVersionId,
  onClose,
  onDone,
}: AppInstallModalProps) {
  const { installApp, myInstalls, refresh: refreshApps } = useApps();
  const { teams, activeTeam } = useTeam();

  // Per-alias child-install state. Resolved on mount + after each child
  // install completes. ``unknown`` is the default until we know whether
  // the dep is satisfied by an existing install.
  const [depState, setDepState] = useState<Record<string, DependencyState>>({});

  // The currently-open child install modal (null when none). Multiple
  // levels recurse via the React tree — each child renders the same
  // <AppInstallModal /> with its own state.
  const [activeChild, setActiveChild] = useState<{
    alias: string;
    appVersionId: string;
  } | null>(null);

  // Resolved app_version_id per dependency alias. We resolve eagerly on
  // mount so the user clicks Install without an extra round-trip.
  const [depVersionByAlias, setDepVersionByAlias] = useState<
    Record<string, string | null>
  >({});

  const [version, setVersion] = useState<AppVersionDetail | null>(null);
  const [compat, setCompat] = useState<CompatReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [teamId, setTeamId] = useState<string>(activeTeam?.id ?? '');
  const [updatePolicy, setUpdatePolicy] = useState<UpdatePolicy>('manual');
  const [runtimeMode, setRuntimeMode] = useState<AppManifestTenancyModel | ''>('');
  const [connectorAccepted, setConnectorAccepted] = useState<Record<string, boolean>>(
    {}
  );
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
        setLoadError(err instanceof Error ? err.message : 'Failed to load version');
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
  const dependencies = useMemo(
    () => parseDependencies(version?.manifest_json ?? null),
    [version]
  );

  // Resolve each dependency's app_id → latest published app_version_id so
  // the inline Install button has something to hand the child modal.
  // Failures are recorded as ``null`` and surface as a disabled Install
  // button with a "Cannot resolve" tooltip — non-blocking for optional
  // deps.
  useEffect(() => {
    let cancelled = false;
    if (dependencies.length === 0) {
      setDepVersionByAlias({});
      return;
    }
    (async () => {
      const next: Record<string, string | null> = {};
      await Promise.all(
        dependencies.map(async (d) => {
          try {
            const versions = await marketplaceAppsApi.listVersions(d.app_id, {
              limit: 1,
            });
            const latest = versions.items?.[0];
            next[d.alias] = latest ? latest.id : null;
          } catch {
            next[d.alias] = null;
          }
        })
      );
      if (!cancelled) setDepVersionByAlias(next);
    })();
    return () => {
      cancelled = true;
    };
  }, [dependencies]);

  // Initial / refresh-driven dep state lookup. We treat any AppInstance
  // for the same app_id as "already installed" (per-user installs from
  // the user's wallet — composition contract treats them as satisfied
  // links). The ``state==='installed'`` filter guards against in-flight
  // installs so we don't block the parent on a half-baked child.
  useEffect(() => {
    if (dependencies.length === 0) return;
    setDepState((prev) => {
      const next: Record<string, DependencyState> = { ...prev };
      for (const dep of dependencies) {
        if (next[dep.alias]?.status === 'skipped') continue;
        const match = myInstalls.find(
          (inst) =>
            inst.app_id === dep.app_id &&
            (inst.state === 'installed' || inst.state === 'running')
        );
        if (match) {
          next[dep.alias] = {
            status: 'installed',
            appInstanceId: match.id,
          };
        } else if (!next[dep.alias] || next[dep.alias].status === 'unknown') {
          next[dep.alias] = { status: 'unknown' };
        }
      }
      return next;
    });
  }, [dependencies, myInstalls]);
  const manifestTenancy = useMemo(
    () => parseTenancyMode(version?.manifest_json ?? null),
    [version]
  );

  // Runtime mode picker is disabled when the manifest pins a tenancy
  // model — we surface the value but don't let the installer override.
  useEffect(() => {
    if (manifestTenancy && !runtimeMode) setRuntimeMode(manifestTenancy);
  }, [manifestTenancy, runtimeMode]);

  const envExposureCount = connectorDecls.filter((c) => c.exposure === 'env').length;
  const allConnectorsAccepted =
    connectorDecls.length === 0 ||
    connectorDecls.every((d) => connectorAccepted[d.id]);

  const acceptAllConnectors = useCallback(() => {
    const next: Record<string, boolean> = {};
    for (const d of connectorDecls) next[d.id] = true;
    setConnectorAccepted(next);
  }, [connectorDecls]);

  // Required dependencies must be ``installed`` (skipping is only valid
  // for optional deps). Optional deps that the user explicitly skipped
  // count as resolved.
  const allRequiredDepsSatisfied = useMemo(() => {
    return dependencies
      .filter((d) => d.required)
      .every((d) => depState[d.alias]?.status === 'installed');
  }, [dependencies, depState]);

  const canInstall = useMemo(() => {
    if (loading || submitting) return false;
    if (!compat?.compatible) return false;
    if (!teamId) return false;
    if (!allConnectorsAccepted) return false;
    if (!allRequiredDepsSatisfied) return false;
    return true;
  }, [
    loading,
    submitting,
    compat,
    teamId,
    allConnectorsAccepted,
    allRequiredDepsSatisfied,
  ]);

  const confirm = async () => {
    if (!teamId) {
      toast.error('Select a team');
      return;
    }
    setSubmitting(true);
    try {
      const walletMix: Record<string, unknown> = { accepted: true };
      for (const key of ['ai_compute', 'general_compute', 'platform_fee'] as const) {
        const entry = billingDims.find((d) => d.dimension === key);
        if (entry) walletMix[key] = entry;
      }
      const result = await installApp({
        app_version_id: appVersionId,
        team_id: teamId,
        wallet_mix_consent: walletMix,
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

  const teamName = teams.find((t) => t.id === teamId)?.name ?? '—';

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Install app"
      data-testid="app-install-modal"
    >
      <div className="w-full max-w-2xl bg-[var(--bg)] border border-[var(--border)] rounded-[var(--radius)] shadow-xl flex flex-col max-h-[92vh]">
        <div className="flex items-center gap-3 p-4 border-b border-[var(--border)]">
          <div className="flex-1">
            <h2 className="text-sm font-semibold text-[var(--text)]">
              Install {(version?.manifest_json as { app?: { name?: string } } | null | undefined)?.app?.name ?? 'app'}
            </h2>
            <p className="text-[10px] text-[var(--text-subtle)]">
              {version ? `Version ${version.version}` : 'Loading…'}
            </p>
          </div>
          <button className="btn btn-sm" onClick={onClose} aria-label="Close">
            <X size={14} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 text-sm text-[var(--text-muted)] space-y-3">
          {loading ? (
            <p>Loading…</p>
          ) : loadError ? (
            <p className="text-[var(--status-error)]">{loadError}</p>
          ) : (
            <>
              {/* Compat banner — always visible. */}
              {!compat?.compatible ? (
                <div
                  role="alert"
                  className="rounded-[var(--radius-small)] border border-[var(--status-error)]/40 bg-[var(--status-error)]/10 p-3 text-xs"
                  data-testid="compat-blocker"
                >
                  <p className="font-semibold mb-1">Not compatible with this server</p>
                  {compat?.unsupported_manifest_schema && (
                    <p>Unsupported manifest schema.</p>
                  )}
                  {(compat?.missing_features ?? []).length > 0 && (
                    <ul className="list-disc pl-5 mt-1">
                      {(compat?.missing_features ?? []).map((f) => (
                        <li key={f}>{f}</li>
                      ))}
                    </ul>
                  )}
                </div>
              ) : null}

              {/* Headline summary — team selector + env warning. */}
              <div className="flex flex-col gap-2">
                <label className="flex flex-col gap-1 text-xs">
                  <span className="text-[var(--text-subtle)]">Install to team</span>
                  <select
                    className="h-8 px-2 bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius-small)] text-sm text-[var(--text)]"
                    value={teamId}
                    onChange={(e) => setTeamId(e.target.value)}
                    data-testid="team-select"
                  >
                    <option value="">— select a team —</option>
                    {teams.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.name}
                      </option>
                    ))}
                  </select>
                </label>

                {envExposureCount > 0 && (
                  <div
                    role="alert"
                    className="flex items-start gap-2 rounded-[var(--radius-small)] bg-amber-500/10 border border-amber-500/30 p-2"
                    data-testid="env-exposure-warning"
                  >
                    <Warning
                      size={14}
                      weight="fill"
                      className="text-amber-400 mt-0.5 flex-shrink-0"
                    />
                    <p className="text-[11px] text-amber-300 leading-snug">
                      This app uses {envExposureCount} env-injected credential
                      {envExposureCount === 1 ? '' : 's'}. Raw secrets will be
                      injected into the app process. Only install if you trust
                      the creator. Expand "Connections" below to review each one.
                    </p>
                  </div>
                )}
              </div>

              {/* Runtime mode (advanced). */}
              <CollapsibleSection
                label="Runtime mode"
                defaultExpanded={false}
              >
                <div className="flex flex-col gap-2">
                  <p className="text-[var(--text-subtle)]">
                    {manifestTenancy
                      ? `Pinned by manifest: ${manifestTenancy}`
                      : 'How the app process is shared across installs.'}
                  </p>
                  <div className="grid grid-cols-3 gap-2">
                    {RUNTIME_MODES.map((mode) => {
                      const active = (runtimeMode || manifestTenancy) === mode;
                      const allowed = !manifestTenancy || manifestTenancy === mode;
                      return (
                        <button
                          key={mode}
                          type="button"
                          disabled={!allowed}
                          onClick={() => setRuntimeMode(mode)}
                          className={`btn btn-sm w-full justify-center ${
                            active ? 'btn-active' : ''
                          } ${!allowed ? 'opacity-50 cursor-not-allowed' : ''}`}
                          data-testid={`runtime-mode-${mode}`}
                        >
                          {mode}
                        </button>
                      );
                    })}
                  </div>
                </div>
              </CollapsibleSection>

              {/* Connections (advanced). */}
              <CollapsibleSection
                label="Connections"
                count={connectorDecls.length}
                defaultExpanded={connectorDecls.length > 0}
              >
                {connectorDecls.length === 0 ? (
                  <p className="text-[var(--text-subtle)]">
                    This app requests no connectors.
                  </p>
                ) : (
                  <div className="flex flex-col gap-2">
                    <div className="flex items-center justify-between">
                      <p className="text-[var(--text-subtle)]">
                        Review each connector's exposure:
                      </p>
                      <button
                        type="button"
                        className="btn btn-sm"
                        onClick={acceptAllConnectors}
                      >
                        Accept all
                      </button>
                    </div>
                    {connectorDecls.map((d) => (
                      <div
                        key={d.id}
                        className="p-2 border border-[var(--border)] rounded-[var(--radius-small)] flex flex-col gap-1.5"
                        data-testid={`connector-${d.id}`}
                      >
                        <label className="flex items-center gap-2">
                          <input
                            type="checkbox"
                            checked={!!connectorAccepted[d.id]}
                            onChange={(e) =>
                              setConnectorAccepted((m) => ({
                                ...m,
                                [d.id]: e.target.checked,
                              }))
                            }
                          />
                          <span className="font-semibold text-[var(--text)]">
                            {d.id}
                          </span>
                          <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded border border-[var(--border)] text-[var(--text-subtle)]">
                            {d.kind}
                          </span>
                          {d.exposure === 'proxy' ? (
                            <span
                              className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/30 text-emerald-400"
                              title="Calls route through the platform Connector Proxy."
                              data-testid={`badge-proxy-${d.id}`}
                            >
                              Proxied
                            </span>
                          ) : (
                            <span
                              className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-amber-500/10 border border-amber-500/30 text-amber-400"
                              title="Raw credential injected as env var."
                              data-testid={`badge-env-${d.id}`}
                            >
                              Env
                            </span>
                          )}
                        </label>
                        <p className="text-[11px] text-[var(--text-subtle)] ml-6">
                          scopes: {d.scopes.join(', ') || '(none)'}
                        </p>
                        {d.exposure === 'env' && (
                          <p
                            className="text-[11px] text-amber-300 leading-snug ml-6"
                            role="alert"
                          >
                            The app process will see this {d.kind} secret in the
                            clear. Only install if you trust the creator.
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </CollapsibleSection>

              {/* Modules (dependencies). Recursive Phase 5 install:
                  inline Install / Skip buttons drive a child <AppInstallModal>
                  for each dep whose app_id is not already satisfied. */}
              <CollapsibleSection
                label="Modules"
                count={dependencies.length}
                defaultExpanded={dependencies.length > 0}
              >
                {dependencies.length === 0 ? (
                  <p className="text-[var(--text-subtle)]">
                    This app has no app-level dependencies.
                  </p>
                ) : (
                  <ul className="space-y-1.5" data-testid="dependencies-list">
                    {dependencies.map((d) => {
                      const state = depState[d.alias] ?? {
                        status: 'unknown' as const,
                      };
                      const childVersionId = depVersionByAlias[d.alias];
                      const installed = state.status === 'installed';
                      const skipped = state.status === 'skipped';
                      return (
                        <li
                          key={d.alias}
                          className="flex flex-wrap items-center gap-2 p-2 rounded-[var(--radius-small)] border border-[var(--border)]"
                          data-testid={`dependency-${d.alias}`}
                        >
                          <span className="font-mono text-[var(--text)]">
                            {d.alias}
                          </span>
                          <span className="text-[var(--text-subtle)]">
                            → {d.app_id}
                          </span>
                          <span
                            className={`text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded border border-[var(--border)] ${
                              d.required
                                ? 'text-[var(--text)]'
                                : 'text-[var(--text-subtle)]'
                            }`}
                          >
                            {d.required ? 'required' : 'optional'}
                          </span>
                          <div className="flex-1" />
                          {installed ? (
                            <span
                              className="flex items-center gap-1 text-[11px] text-emerald-400"
                              data-testid={`dep-installed-${d.alias}`}
                            >
                              <CheckCircle size={12} weight="fill" />
                              Installed
                            </span>
                          ) : skipped ? (
                            <span
                              className="text-[11px] text-[var(--text-subtle)]"
                              data-testid={`dep-skipped-${d.alias}`}
                            >
                              Skipped
                            </span>
                          ) : (
                            <>
                              <button
                                type="button"
                                className="btn btn-sm"
                                disabled={!childVersionId}
                                title={
                                  childVersionId
                                    ? `Install ${d.alias}`
                                    : 'Cannot resolve a published version for this app'
                                }
                                onClick={() => {
                                  if (!childVersionId) return;
                                  setActiveChild({
                                    alias: d.alias,
                                    appVersionId: childVersionId,
                                  });
                                }}
                                data-testid={`dep-install-${d.alias}`}
                              >
                                Install {d.alias}
                              </button>
                              {!d.required && (
                                <button
                                  type="button"
                                  className="btn btn-sm"
                                  onClick={() => {
                                    setDepState((prev) => ({
                                      ...prev,
                                      [d.alias]: { status: 'skipped' },
                                    }));
                                  }}
                                  data-testid={`dep-skip-${d.alias}`}
                                >
                                  Skip
                                </button>
                              )}
                            </>
                          )}
                        </li>
                      );
                    })}
                    {!allRequiredDepsSatisfied && (
                      <li
                        role="alert"
                        className="text-[11px] text-amber-300 leading-snug"
                        data-testid="dep-blocking-banner"
                      >
                        Install or resolve all required dependencies before
                        installing this app.
                      </li>
                    )}
                  </ul>
                )}
              </CollapsibleSection>

              {/* Billing & credits. */}
              <CollapsibleSection
                label="Billing & credits"
                count={billingDims.length}
                defaultExpanded={false}
              >
                {billingDims.length === 0 ? (
                  <p className="text-[var(--text-subtle)]">
                    This app declares no billing dimensions.
                  </p>
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
                          <td className="py-1">
                            {d.cap_usd != null ? `$${d.cap_usd}` : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </CollapsibleSection>

              {/* Update policy. */}
              <CollapsibleSection label="Update policy" defaultExpanded={false}>
                <label className="flex flex-col gap-1 text-xs">
                  <span className="text-[var(--text-subtle)]">
                    How updates roll out for this install
                  </span>
                  <select
                    className="h-8 px-2 bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius-small)] text-sm text-[var(--text)]"
                    value={updatePolicy}
                    onChange={(e) => setUpdatePolicy(e.target.value as UpdatePolicy)}
                    data-testid="update-policy-select"
                  >
                    <option value="manual">Manual — I review every release</option>
                    <option value="patch">Auto — patch versions only</option>
                    <option value="minor">Auto — minor versions and below</option>
                  </select>
                </label>
              </CollapsibleSection>

              <div className="text-[11px] text-[var(--text-subtle)] mt-2">
                Installing to <span className="text-[var(--text)]">{teamName}</span>{' '}
                with policy <span className="text-[var(--text)]">{updatePolicy}</span>.
              </div>
            </>
          )}
        </div>

        <div className="flex items-center gap-2 p-4 border-t border-[var(--border)]">
          <button className="btn" onClick={onClose} disabled={submitting}>
            Cancel
          </button>
          <div className="flex-1" />
          <button
            className="btn btn-filled"
            onClick={confirm}
            disabled={!canInstall}
            data-testid="install-confirm-btn"
          >
            {submitting ? 'Installing…' : 'Install'}
          </button>
        </div>
      </div>

      {/* Recursive child install modal — opened by the "Install {alias}"
          button in Modules. Higher z-index so it stacks over the parent.
          On success we mark the dep installed; on cancel we leave the dep
          in 'unknown' state so the user can retry or skip. */}
      {activeChild && (
        <div className="fixed inset-0 z-[60]">
          <AppInstallModal
            appVersionId={activeChild.appVersionId}
            onClose={() => setActiveChild(null)}
            onDone={(childInstanceId) => {
              const alias = activeChild.alias;
              setDepState((prev) => ({
                ...prev,
                [alias]: {
                  status: 'installed',
                  appInstanceId: childInstanceId,
                },
              }));
              setActiveChild(null);
              // Refresh installs so the satisfied-by-existing-install
              // path picks up the new row on subsequent renders.
              void refreshApps();
            }}
          />
        </div>
      )}
    </div>
  );
}

export default AppInstallModal;
