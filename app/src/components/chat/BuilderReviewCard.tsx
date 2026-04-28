import { Sparkles, Calendar, Plug, Clock, Rocket, Save, X } from 'lucide-react';

export interface BuilderReviewSummary {
  name: string;
  description?: string;
  mcps?: { slug?: string; name?: string }[];
  schedule?: {
    cron?: string;
    tz?: string;
    humanized?: string;
  };
  delivery_targets?: { kind?: string; name?: string }[];
  draft_url?: string;
}

export type BuilderReviewResponse =
  | 'publish_and_activate'
  | 'save_draft'
  | 'cancel';

interface BuilderReviewCardProps {
  approvalId: string;
  summary: BuilderReviewSummary;
  onRespond: (approvalId: string, response: BuilderReviewResponse) => void;
}

export function BuilderReviewCard({
  approvalId,
  summary,
  onRespond,
}: BuilderReviewCardProps) {
  const mcps = summary.mcps ?? [];
  const deliveryTargets = summary.delivery_targets ?? [];
  const schedule = summary.schedule;

  return (
    <div className="bg-[var(--primary)]/5 border-2 border-[var(--primary)]/30 rounded-lg p-4">
      <div className="flex items-start gap-3 mb-3">
        <Sparkles className="w-5 h-5 text-[var(--primary)] flex-shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <h4 className="font-semibold text-[var(--text)] mb-1 truncate">
            Ready to publish: {summary.name}
          </h4>
          {summary.description ? (
            <p className="text-sm text-[var(--text)]/70">{summary.description}</p>
          ) : null}
        </div>
      </div>

      <div className="space-y-2 mb-4 text-xs text-[var(--text)]/80">
        {schedule ? (
          <div className="flex items-start gap-2">
            <Calendar className="w-4 h-4 text-[var(--text)]/60 flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <span className="font-medium">Schedule:</span>{' '}
              {schedule.humanized ?? schedule.cron ?? 'manual trigger'}
              {schedule.tz ? (
                <span className="text-[var(--text)]/50"> ({schedule.tz})</span>
              ) : null}
            </div>
          </div>
        ) : null}

        {mcps.length > 0 ? (
          <div className="flex items-start gap-2">
            <Plug className="w-4 h-4 text-[var(--text)]/60 flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <span className="font-medium">Connectors:</span>{' '}
              {mcps
                .map((m) => m.name ?? m.slug)
                .filter(Boolean)
                .join(', ')}
            </div>
          </div>
        ) : null}

        {deliveryTargets.length > 0 ? (
          <div className="flex items-start gap-2">
            <Clock className="w-4 h-4 text-[var(--text)]/60 flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <span className="font-medium">Delivery:</span>{' '}
              {deliveryTargets
                .map((d) => d.name ?? d.kind)
                .filter(Boolean)
                .join(', ')}
            </div>
          </div>
        ) : null}

        {summary.draft_url ? (
          <div className="text-[var(--text)]/50">
            Draft preview:{' '}
            <a
              href={summary.draft_url}
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-[var(--primary)]"
            >
              {summary.draft_url}
            </a>
          </div>
        ) : null}
      </div>

      <div className="flex gap-2">
        <button
          onClick={() => onRespond(approvalId, 'publish_and_activate')}
          className="flex-1 px-3 py-2 bg-[var(--primary)]/20 hover:bg-[var(--primary)]/30 border border-[var(--primary)]/40 rounded-lg text-[var(--primary)] text-sm font-medium transition-all flex items-center justify-center gap-2"
        >
          <Rocket className="w-4 h-4" />
          Publish &amp; Activate
        </button>

        <button
          onClick={() => onRespond(approvalId, 'save_draft')}
          className="flex-1 px-3 py-2 bg-[var(--surface)] hover:bg-[var(--surface-hover)] border border-[var(--border)] rounded-lg text-[var(--text)] text-sm font-medium transition-all flex items-center justify-center gap-2"
        >
          <Save className="w-4 h-4" />
          Save as draft
        </button>

        <button
          onClick={() => onRespond(approvalId, 'cancel')}
          className="px-3 py-2 bg-transparent hover:bg-red-500/10 border border-transparent hover:border-red-500/30 rounded-lg text-[var(--text)]/60 hover:text-red-500 text-sm font-medium transition-all flex items-center justify-center"
          aria-label="Cancel"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
