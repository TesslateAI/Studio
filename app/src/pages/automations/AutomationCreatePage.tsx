import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import { ArrowLeft } from '@phosphor-icons/react';
import { automationsApi } from '../../lib/api';
import { APPLY_STORAGE_KEY, type ApplyHandoff } from '../marketplace/ContractTemplates';
import type {
  AutomationActionIn,
  AutomationDefinitionIn,
  AutomationDeliveryTargetIn,
  AutomationTriggerIn,
  AutomationWorkspaceScope,
} from '../../types/automations';
import { TriggerEditor } from './components/TriggerEditor';
import { ActionEditor } from './components/ActionEditor';
import { ContractEditor } from './components/ContractEditor';
import { DestinationPicker } from './components/DestinationPicker';

const DEFAULT_CONTRACT = `{
  "allowed_tools": ["read", "write", "bash"],
  "max_compute_tier": 1,
  "max_iterations": 25
}`;

const SCOPES: Array<{ value: AutomationWorkspaceScope; label: string; help: string }> = [
  {
    value: 'none',
    label: 'No files needed',
    help: 'The automation just runs an action — no project files involved.',
  },
  {
    value: 'user_automation_workspace',
    label: 'In my personal automation folder',
    help: 'Use a private folder shared across your automations.',
  },
  {
    value: 'team_automation_workspace',
    label: "In our team's automation folder",
    help: 'Use a shared folder visible to everyone on the team.',
  },
  {
    value: 'target_project',
    label: 'Inside one of my projects',
    help: 'Run inside an existing project. Pick the project below.',
  },
];

/**
 * /automations/new — single-form create page. Submits to
 * POST /api/automations and redirects to the detail page.
 */
export default function AutomationCreatePage() {
  const navigate = useNavigate();
  const [name, setName] = useState('');
  const [scope, setScope] = useState<AutomationWorkspaceScope>('none');
  const [targetProjectId, setTargetProjectId] = useState('');
  const [maxComputeTier, setMaxComputeTier] = useState('0');
  const [maxSpendPerRun, setMaxSpendPerRun] = useState('');
  const [maxSpendPerDay, setMaxSpendPerDay] = useState('');
  const [trigger, setTrigger] = useState<AutomationTriggerIn>({
    kind: 'manual',
    config: {},
  });
  const [action, setAction] = useState<AutomationActionIn>({
    action_type: 'agent.run',
    config: {},
    app_action_id: null,
    ordinal: 0,
  });
  const [contractText, setContractText] = useState<string>(DEFAULT_CONTRACT);
  const [appliedTemplateName, setAppliedTemplateName] = useState<string | null>(null);

  // Phase 5: marketplace ContractTemplates page hands the contract over via
  // sessionStorage (URL stays human-readable). Read once on mount; clear
  // immediately so a refresh doesn't re-apply.
  useEffect(() => {
    let raw: string | null = null;
    try {
      raw = sessionStorage.getItem(APPLY_STORAGE_KEY);
      if (raw) sessionStorage.removeItem(APPLY_STORAGE_KEY);
    } catch {
      return;
    }
    if (!raw) return;
    try {
      const handoff = JSON.parse(raw) as ApplyHandoff;
      if (
        handoff &&
        typeof handoff === 'object' &&
        handoff.contract &&
        typeof handoff.contract === 'object'
      ) {
        setContractText(JSON.stringify(handoff.contract, null, 2));
        setAppliedTemplateName(handoff.template_name ?? null);
        toast.success(`Applied template: ${handoff.template_name ?? 'contract template'}`);
      }
    } catch {
      // Stale/malformed handoff — silently ignore.
    }
  }, []);
  // Phase 4: pick a stored CommunicationDestination via DestinationPicker
  // (drop-down + inline create). Empty string = "no delivery target".
  const [deliveryDestinationId, setDeliveryDestinationId] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const canSubmit = useMemo(() => {
    return name.trim().length > 0 && contractText.trim().length > 0 && !submitting;
  }, [name, contractText, submitting]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;

    let contract: Record<string, unknown>;
    try {
      contract = JSON.parse(contractText);
      if (typeof contract !== 'object' || contract === null || Array.isArray(contract)) {
        throw new Error('Contract must be a JSON object.');
      }
      if (Object.keys(contract).length === 0) {
        throw new Error('Contract must contain at least one key.');
      }
    } catch (err) {
      toast.error(`Invalid contract: ${err instanceof Error ? err.message : String(err)}`);
      return;
    }

    // Coerce app.invoke `input` from textarea-as-string to JSON so the
    // dispatcher receives a real object. The ActionEditor already does this
    // best-effort but keeps strings for partial typing.
    const finalAction: AutomationActionIn = { ...action };
    if (finalAction.action_type === 'app.invoke' && typeof finalAction.config.input === 'string') {
      try {
        finalAction.config = {
          ...finalAction.config,
          input: JSON.parse(String(finalAction.config.input)),
        };
      } catch {
        toast.error('App action input must be valid JSON.');
        return;
      }
    }

    const deliveryTargets: AutomationDeliveryTargetIn[] = deliveryDestinationId.trim()
      ? [
          {
            destination_id: deliveryDestinationId.trim(),
            ordinal: 0,
            on_failure: {},
            artifact_filter: 'all',
          },
        ]
      : [];

    const payload: AutomationDefinitionIn = {
      name: name.trim(),
      workspace_scope: scope,
      target_project_id: scope === 'target_project' ? targetProjectId.trim() || null : null,
      contract,
      max_compute_tier: Number.isFinite(parseInt(maxComputeTier, 10))
        ? parseInt(maxComputeTier, 10)
        : 0,
      max_spend_per_run_usd: maxSpendPerRun.trim() ? maxSpendPerRun.trim() : null,
      max_spend_per_day_usd: maxSpendPerDay.trim() ? maxSpendPerDay.trim() : null,
      triggers: [trigger],
      actions: [finalAction],
      delivery_targets: deliveryTargets,
    };

    setSubmitting(true);
    try {
      const created = await automationsApi.create(payload);
      toast.success('Automation created');
      navigate(`/automations/${created.id}`);
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
        'Failed to create automation';
      toast.error(typeof msg === 'string' ? msg : 'Failed to create automation');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      {/* Header */}
      <div className="flex-shrink-0">
        <div
          className="h-10 flex items-center gap-2"
          style={{
            paddingLeft: '11px',
            paddingRight: '11px',
            borderBottom: 'var(--border-width) solid var(--border)',
          }}
        >
          <button
            onClick={() => navigate('/automations')}
            className="btn btn-icon btn-sm"
            aria-label="Back to automations"
          >
            <ArrowLeft className="w-3 h-3" />
          </button>
          <h2 className="text-xs font-semibold text-[var(--text)]">New automation</h2>
        </div>
      </div>

      {/* Form */}
      <div className="flex-1 overflow-y-auto">
        <form onSubmit={handleSubmit} className="max-w-2xl mx-auto px-6 py-6 space-y-6">
          <Section title="Basics" description="Name your automation and pick where it should run.">
            <label className="block">
              <span className="block text-xs font-medium text-[var(--text)] mb-1">Name</span>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="My nightly summary"
                required
                className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
              />
            </label>

            <fieldset className="space-y-1.5">
              <legend className="text-xs font-medium text-[var(--text)] mb-1">
                Where should it run?
              </legend>
              {SCOPES.map((opt) => (
                <label key={opt.value} className="flex items-start gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="scope"
                    value={opt.value}
                    checked={scope === opt.value}
                    onChange={() => setScope(opt.value)}
                    className="mt-0.5"
                  />
                  <span className="flex-1">
                    <span className="block text-xs text-[var(--text)]">{opt.label}</span>
                    <span className="block text-[10px] text-[var(--text-subtle)]">{opt.help}</span>
                  </span>
                </label>
              ))}
            </fieldset>

            {scope === 'target_project' && (
              <label className="block">
                <span className="block text-xs font-medium text-[var(--text)] mb-1">
                  Project ID
                </span>
                <input
                  type="text"
                  value={targetProjectId}
                  onChange={(e) => setTargetProjectId(e.target.value)}
                  placeholder="project UUID"
                  className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs font-mono focus:outline-none focus:border-[var(--border-hover)]"
                />
                <span className="mt-1 block text-[10px] text-[var(--text-subtle)]">
                  Paste a project UUID for now. A picker is coming soon.
                </span>
              </label>
            )}
          </Section>

          <Section title="When" description="Pick the trigger that should start each run.">
            <TriggerEditor value={trigger} onChange={setTrigger} />
          </Section>

          <Section
            title="What it does"
            description="Pick exactly one thing the automation should do."
          >
            <ActionEditor value={action} onChange={setAction} />
          </Section>

          <Section
            title="Where to send the result (optional)"
            description="Pick a saved destination — Slack, Telegram, email, webhook, etc. — or create a new one. Leave empty to just keep results in the run history."
          >
            <DestinationPicker
              value={deliveryDestinationId}
              onChange={setDeliveryDestinationId}
              placeholder="Don't send anywhere"
            />
          </Section>

          <Section
            title="Limits (optional)"
            description="Cap how powerful and how expensive each run can be."
          >
            <div className="grid grid-cols-3 gap-3">
              <label className="block">
                <span className="block text-xs font-medium text-[var(--text)] mb-1">
                  Power level
                </span>
                <input
                  type="number"
                  min={0}
                  step={1}
                  value={maxComputeTier}
                  onChange={(e) => setMaxComputeTier(e.target.value)}
                  className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs font-mono focus:outline-none focus:border-[var(--border-hover)]"
                />
                <span className="mt-1 block text-[10px] text-[var(--text-subtle)]">
                  0 = light, 1 = standard, 2+ = heavy.
                </span>
              </label>
              <label className="block">
                <span className="block text-xs font-medium text-[var(--text)] mb-1">
                  Max $ per run
                </span>
                <input
                  type="text"
                  inputMode="decimal"
                  value={maxSpendPerRun}
                  onChange={(e) => setMaxSpendPerRun(e.target.value)}
                  placeholder="e.g. 0.50"
                  className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs font-mono focus:outline-none focus:border-[var(--border-hover)]"
                />
              </label>
              <label className="block">
                <span className="block text-xs font-medium text-[var(--text)] mb-1">
                  Max $ per day
                </span>
                <input
                  type="text"
                  inputMode="decimal"
                  value={maxSpendPerDay}
                  onChange={(e) => setMaxSpendPerDay(e.target.value)}
                  placeholder="e.g. 5.00"
                  className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs font-mono focus:outline-none focus:border-[var(--border-hover)]"
                />
              </label>
            </div>
          </Section>

          <Section
            title="Permissions"
            description="Required guardrails for what this automation is allowed to do."
          >
            {appliedTemplateName && (
              <div
                className="mb-2 px-2 py-1.5 text-[11px] text-[var(--text)] bg-[var(--primary)]/10 border border-[var(--primary)]/30 rounded-[var(--radius-small)] flex items-center gap-2"
                data-testid="applied-template-badge"
              >
                <span className="font-medium">Applied template:</span>
                <span className="font-mono">{appliedTemplateName}</span>
                <button
                  type="button"
                  className="ml-auto text-[10px] text-[var(--text-subtle)] hover:text-[var(--text)] underline"
                  onClick={() => {
                    setContractText(DEFAULT_CONTRACT);
                    setAppliedTemplateName(null);
                  }}
                >
                  Reset
                </button>
              </div>
            )}
            <ContractEditor value={contractText} onChange={setContractText} />
          </Section>

          <div className="flex items-center justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={() => navigate('/automations')}
              className="btn"
              disabled={submitting}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="btn btn-filled"
              disabled={!canSubmit}
              data-testid="create-automation-submit"
            >
              {submitting ? 'Creating…' : 'Create automation'}
            </button>
          </div>
        </form>
      </div>
    </>
  );
}

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-4 space-y-3">
      <header>
        <h3 className="text-xs font-semibold text-[var(--text)]">{title}</h3>
        <p className="text-[10px] text-[var(--text-subtle)] mt-0.5">{description}</p>
      </header>
      {children}
    </section>
  );
}
