import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import { Lightning, ArrowSquareOut } from '@phosphor-icons/react';
import {
  contractTemplatesApi,
  type ContractTemplate,
} from '../../lib/api';

/**
 * Contract Templates marketplace browse page — Phase 5 polish.
 *
 * Lists published :class:`ContractTemplate` rows from
 * ``GET /api/contract-templates``. The user filters by category,
 * inspects a template's contract JSON, and clicks "Apply Template" to
 * jump into the AutomationCreatePage with the contract prefilled.
 *
 * The Apply flow uses ``sessionStorage`` (not the URL) to hand the
 * contract over so the URL stays human-readable. AutomationCreatePage
 * picks the key up on mount and clears it.
 */

const APPLY_STORAGE_KEY = 'opensail.automationCreate.applyTemplate';

interface ApplyHandoff {
  template_id: string;
  template_name: string;
  contract: Record<string, unknown>;
}

export default function ContractTemplatesPage() {
  const navigate = useNavigate();
  const [templates, setTemplates] = useState<ContractTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [category, setCategory] = useState<string>('');
  const [applying, setApplying] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    contractTemplatesApi
      .list(category ? { category } : {})
      .then((rows) => {
        if (cancelled) return;
        setTemplates(rows);
      })
      .catch((err: { response?: { data?: { detail?: string } }; message?: string }) => {
        if (cancelled) return;
        const msg =
          err?.response?.data?.detail ?? err?.message ?? 'Failed to load templates';
        setError(msg);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [category]);

  // Distinct category list — derived from the current result set so the
  // filter chips reflect what's actually there.
  const categories = useMemo(() => {
    const set = new Set<string>();
    for (const t of templates) set.add(t.category);
    return ['', ...Array.from(set).sort()];
  }, [templates]);

  const handleApply = async (template: ContractTemplate) => {
    setApplying(template.id);
    try {
      const resp = await contractTemplatesApi.apply(template.id);
      const handoff: ApplyHandoff = {
        template_id: resp.template_id,
        template_name: resp.template_name,
        contract: resp.contract,
      };
      try {
        sessionStorage.setItem(APPLY_STORAGE_KEY, JSON.stringify(handoff));
      } catch {
        toast.error('Could not stage template — sessionStorage unavailable.');
        return;
      }
      navigate('/automations/new');
    } catch (err) {
      const e = err as { response?: { data?: { detail?: string } }; message?: string };
      toast.error(
        e?.response?.data?.detail ?? e?.message ?? 'Failed to apply template'
      );
    } finally {
      setApplying(null);
    }
  };

  return (
    <div className="p-4 md:p-6 max-w-[1200px] mx-auto">
      <header className="mb-4 flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-base font-semibold text-[var(--text)]">
            Contract templates
          </h1>
          <p className="text-xs text-[var(--text-subtle)] mt-1">
            Pre-built guard rails for the Automation Builder. Apply a
            template to prefill the contract JSON, then customize before
            creating.
          </p>
        </div>
      </header>

      <div className="flex items-center gap-1.5 mb-5 flex-wrap">
        {categories.map((c) => (
          <button
            key={c || '__all__'}
            type="button"
            onClick={() => setCategory(c)}
            className={`btn btn-sm ${category === c ? 'btn-active' : ''}`}
            data-testid={`category-${c || 'all'}`}
          >
            {c === '' ? 'All' : c}
          </button>
        ))}
      </div>

      {loading && (
        <p className="text-xs text-[var(--text-subtle)]">Loading templates…</p>
      )}
      {error && (
        <p
          role="alert"
          className="text-xs text-[var(--status-error)]"
          data-testid="contract-templates-error"
        >
          {error}
        </p>
      )}

      {!loading && !error && templates.length === 0 && (
        <p className="text-xs text-[var(--text-subtle)]">
          No published templates in this category.
        </p>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {templates.map((tpl) => (
          <article
            key={tpl.id}
            className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-4 flex flex-col gap-3"
            data-testid={`template-card-${tpl.id}`}
          >
            <div className="flex items-start gap-2">
              <Lightning
                size={16}
                weight="fill"
                className="text-[var(--primary)] flex-shrink-0 mt-0.5"
              />
              <div className="flex-1 min-w-0">
                <h2 className="text-sm font-semibold text-[var(--text)] truncate">
                  {tpl.name}
                </h2>
                <p className="text-[10px] uppercase tracking-wide text-[var(--text-subtle)] mt-0.5">
                  {tpl.category}
                </p>
              </div>
            </div>
            {tpl.description && (
              <p className="text-xs text-[var(--text-muted)] leading-relaxed">
                {tpl.description}
              </p>
            )}
            <details className="text-[10px]">
              <summary className="cursor-pointer text-[var(--text-subtle)] hover:text-[var(--text)]">
                Contract JSON
              </summary>
              <pre className="mt-1 p-2 bg-[var(--bg)] border border-[var(--border)] rounded-[var(--radius-small)] overflow-auto max-h-40 text-[10px] font-mono text-[var(--text)]">
                {JSON.stringify(tpl.contract_json, null, 2)}
              </pre>
            </details>
            <div className="flex-1" />
            <button
              type="button"
              onClick={() => handleApply(tpl)}
              disabled={applying === tpl.id}
              className="btn btn-filled btn-sm w-full justify-center"
              data-testid={`apply-template-${tpl.id}`}
            >
              <ArrowSquareOut size={12} />
              {applying === tpl.id ? 'Applying…' : 'Apply Template'}
            </button>
          </article>
        ))}
      </div>
    </div>
  );
}

export { APPLY_STORAGE_KEY };
export type { ApplyHandoff };
