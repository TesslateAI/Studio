import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import { ArrowLeft } from '@phosphor-icons/react';
import { automationsApi } from '../../lib/api';
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

const DEFAULT_CONTRACT = `{
  "allowed_tools": ["read", "write", "bash"],
  "max_compute_tier": 1,
  "max_iterations": 25
}`;

const SCOPES: Array<{ value: AutomationWorkspaceScope; label: string; help: string }> = [
  { value: 'none', label: 'No workspace', help: 'Action runs without a project workspace.' },
  {
    value: 'user_automation_workspace',
    label: 'User workspace',
    help: 'Use the per-user automation workspace volume.',
  },
  {
    value: 'team_automation_workspace',
    label: 'Team workspace',
    help: 'Use the team-shared automation workspace volume.',
  },
  {
    value: 'target_project',
    label: 'Target project',
    help: 'Run inside an existing project (target_project_id required).',
  },
];

/**
 * /automations/new — single-form create page.
 *
 * No wizard, no fancy validation — just the fields the backend requires
 * + the optional ones a user might reasonably want to set on day one.
 * Submits to POST /api/automations and redirects to the detail page.
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
  // Phase 4 owns CommunicationDestination management. Phase 1 lets the
  // user paste a destination UUID directly so they can wire something up
  // if a destination already exists in the DB.
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
    if (
      finalAction.action_type === 'app.invoke' &&
      typeof finalAction.config.input === 'string'
    ) {
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
          <Section title="Basics" description="Name + workspace scope.">
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
                Workspace scope
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
                    <span className="block text-[10px] text-[var(--text-subtle)]">
                      {opt.help}
                    </span>
                  </span>
                </label>
              ))}
            </fieldset>

            {scope === 'target_project' && (
              <label className="block">
                <span className="block text-xs font-medium text-[var(--text)] mb-1">
                  Target project ID
                </span>
                <input
                  type="text"
                  value={targetProjectId}
                  onChange={(e) => setTargetProjectId(e.target.value)}
                  placeholder="project UUID"
                  className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs font-mono focus:outline-none focus:border-[var(--border-hover)]"
                />
              </label>
            )}
          </Section>

          <Section title="Trigger" description="When the automation should fire.">
            <TriggerEditor value={trigger} onChange={setTrigger} />
          </Section>

          <Section title="Action" description="Phase 1 supports exactly one action.">
            <ActionEditor value={action} onChange={setAction} />
          </Section>

          <Section
            title="Delivery target (optional)"
            description="Phase 4 adds a destination picker. For now, paste an existing CommunicationDestination UUID."
          >
            <input
              type="text"
              value={deliveryDestinationId}
              onChange={(e) => setDeliveryDestinationId(e.target.value)}
              placeholder="destination UUID (leave blank to skip)"
              className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs font-mono focus:outline-none focus:border-[var(--border-hover)]"
            />
          </Section>

          <Section
            title="Limits (optional)"
            description="Compute tier and per-run / per-day spend caps."
          >
            <div className="grid grid-cols-3 gap-3">
              <label className="block">
                <span className="block text-xs font-medium text-[var(--text)] mb-1">
                  Max compute tier
                </span>
                <input
                  type="number"
                  min={0}
                  step={1}
                  value={maxComputeTier}
                  onChange={(e) => setMaxComputeTier(e.target.value)}
                  className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs font-mono focus:outline-none focus:border-[var(--border-hover)]"
                />
              </label>
              <label className="block">
                <span className="block text-xs font-medium text-[var(--text)] mb-1">
                  Max $/run
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
                  Max $/day
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
            title="Contract"
            description="Required guard rails. Dispatcher refuses to run without a contract."
          >
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
