/**
 * AdminSubmissionWorkbenchPage
 *
 * Route: /admin/marketplace/submissions/:submissionId
 *
 * Single submission detail + decision UI. Left column: manifest preview.
 * Right column: checks grouped by stage + advance/reject controls.
 *
 * Client-side VALID_TRANSITIONS mirrors
 * orchestrator/app/services/apps/submissions.py — keep these in sync.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Navigate, useNavigate, useParams } from 'react-router-dom';
import toast from 'react-hot-toast';
import { useAuth } from '../contexts/AuthContext';
import { useRequiredAdmin } from '../contexts/AdminContext';
import {
  appSubmissionsApi,
  type SubmissionDetail,
  type SubmissionCheck,
} from '../lib/api';

// Mirrors backend VALID_TRANSITIONS. Keep in sync.
export const VALID_TRANSITIONS: Record<string, readonly string[]> = {
  stage0: ['stage1', 'rejected'],
  stage1: ['stage2', 'rejected'],
  stage2: ['stage3', 'rejected'],
  stage3: ['approved', 'rejected'],
  approved: [],
  rejected: [],
};

type CheckStatus = 'passed' | 'failed' | 'warning' | 'errored';

export default function AdminSubmissionWorkbenchPage() {
  const { user } = useAuth();
  const { submissionId } = useParams<{ submissionId: string }>();
  const navigate = useNavigate();
  if (!user?.is_superuser) return <Navigate to="/dashboard" replace />;

  const admin = useRequiredAdmin();
  const [submission, setSubmission] = useState<SubmissionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);

  const loadSubmission = useCallback(async () => {
    if (!submissionId) return;
    setLoading(true);
    try {
      const data = await appSubmissionsApi.get(submissionId);
      setSubmission(data);
    } catch (e) {
      toast.error(`Failed to load: ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [submissionId]);

  useEffect(() => {
    void loadSubmission();
  }, [loadSubmission]);

  const nextStages = useMemo(() => {
    if (!submission) return [];
    return VALID_TRANSITIONS[submission.stage] ?? [];
  }, [submission]);

  const onAdvance = async (toStage: string) => {
    if (!submission) return;
    setBusy(true);
    try {
      await admin.advanceSubmission(submission.id, toStage, notes || undefined);
      toast.success(`Advanced to ${toStage}`);
      setNotes('');
      await loadSubmission();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <div className="p-8 text-sm text-[var(--text-muted)]">Loading…</div>;
  if (!submission) return <div className="p-8 text-sm">Submission not found.</div>;

  return (
    <div className="min-h-screen bg-[var(--bg)] text-[var(--text)]">
      <header className="border-b border-[var(--border)] px-8 py-5 flex items-center justify-between">
        <div>
          <button
            onClick={() => navigate('/admin/marketplace')}
            className="text-xs text-[var(--text-muted)] hover:text-[var(--text)]"
          >
            ← Back to queue
          </button>
          <h1 className="text-2xl font-semibold mt-1">
            Submission{' '}
            <span className="font-mono text-sm text-[var(--text-muted)]">
              {submission.id.slice(0, 8)}
            </span>
          </h1>
          <p className="text-sm text-[var(--text-muted)] mt-1">
            Stage <code>{submission.stage}</code> · Decision{' '}
            <code>{submission.decision}</code>
          </p>
        </div>
      </header>

      <main className="grid grid-cols-1 lg:grid-cols-2 gap-8 p-8">
        <ManifestColumn submission={submission} />
        <DecisionColumn
          submission={submission}
          nextStages={nextStages}
          notes={notes}
          onNotesChange={setNotes}
          busy={busy}
          onAdvance={onAdvance}
          onChecksChanged={loadSubmission}
        />
      </main>
    </div>
  );
}

// ---------------------------------------------------------------------------

function ManifestColumn({ submission }: { submission: SubmissionDetail }) {
  return (
    <section>
      <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--text-muted)] mb-3">
        Manifest
      </h2>
      <pre className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4 overflow-auto text-xs max-h-[70vh]">
        {JSON.stringify(
          {
            id: submission.id,
            app_version_id: submission.app_version_id,
            submitter_user_id: submission.submitter_user_id,
            stage: submission.stage,
            decision: submission.decision,
            reviewer_user_id: submission.reviewer_user_id,
            decision_notes: submission.decision_notes,
          },
          null,
          2
        )}
      </pre>
    </section>
  );
}

// ---------------------------------------------------------------------------

interface DecisionColumnProps {
  submission: SubmissionDetail;
  nextStages: readonly string[];
  notes: string;
  onNotesChange: (v: string) => void;
  busy: boolean;
  onAdvance: (toStage: string) => Promise<void>;
  onChecksChanged: () => Promise<void>;
}

function DecisionColumn(props: DecisionColumnProps) {
  const { submission, nextStages, notes, onNotesChange, busy, onAdvance } = props;

  const checksByStage = useMemo(() => {
    const acc: Record<string, SubmissionCheck[]> = {};
    submission.checks.forEach((c) => {
      acc[c.stage] = acc[c.stage] ?? [];
      acc[c.stage].push(c);
    });
    return acc;
  }, [submission.checks]);

  return (
    <section className="space-y-6">
      <div>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--text-muted)] mb-3">
          Checks
        </h2>
        {Object.keys(checksByStage).length === 0 && (
          <p className="text-sm text-[var(--text-muted)]">No checks recorded.</p>
        )}
        {Object.entries(checksByStage).map(([stage, checks]) => (
          <div key={stage} className="mb-4">
            <div className="text-xs uppercase tracking-wide text-[var(--text-muted)] mb-1">
              {stage}
            </div>
            <ul className="space-y-1">
              {checks.map((c) => (
                <li
                  key={c.id}
                  className="flex items-center justify-between rounded border border-[var(--border)] px-3 py-1.5 text-sm"
                >
                  <span>{c.check_name}</span>
                  <span className={statusColor(c.status)}>{c.status}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <AddCheckForm
        submissionId={submission.id}
        currentStage={submission.stage}
        onCreated={props.onChecksChanged}
      />

      <div>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--text-muted)] mb-3">
          Decision
        </h2>
        <textarea
          value={notes}
          onChange={(e) => onNotesChange(e.target.value)}
          placeholder="Decision notes (optional)"
          className="w-full rounded border border-[var(--border)] bg-[var(--surface)] p-2 text-sm"
          rows={4}
        />
        <div className="mt-3 flex flex-wrap gap-2">
          {nextStages.length === 0 && (
            <span className="text-xs text-[var(--text-muted)]">
              Terminal state — no further transitions.
            </span>
          )}
          {nextStages.map((s) => {
            const isReject = s === 'rejected';
            return (
              <button
                key={s}
                data-testid={`advance-${s}`}
                disabled={busy}
                onClick={() => void onAdvance(s)}
                className={`px-3 py-1.5 rounded text-sm disabled:opacity-50 ${
                  isReject
                    ? 'bg-red-600 text-white'
                    : 'bg-[var(--primary)] text-white'
                }`}
              >
                {isReject ? 'Reject' : `Advance → ${s}`}
              </button>
            );
          })}
        </div>
      </div>
    </section>
  );
}

function statusColor(status: string): string {
  switch (status) {
    case 'passed':
      return 'text-emerald-400';
    case 'failed':
      return 'text-red-400';
    case 'warning':
      return 'text-amber-400';
    default:
      return 'text-[var(--text-muted)]';
  }
}

// ---------------------------------------------------------------------------

function AddCheckForm({
  submissionId,
  currentStage,
  onCreated,
}: {
  submissionId: string;
  currentStage: string;
  onCreated: () => Promise<void>;
}) {
  const [stage, setStage] = useState(currentStage);
  const [checkName, setCheckName] = useState('');
  const [status, setStatus] = useState<CheckStatus>('passed');
  const [details, setDetails] = useState('{}');
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!checkName) {
      toast.error('check_name required');
      return;
    }
    let parsed: Record<string, unknown> = {};
    try {
      parsed = JSON.parse(details) as Record<string, unknown>;
    } catch {
      toast.error('details must be valid JSON');
      return;
    }
    setBusy(true);
    try {
      await appSubmissionsApi.recordCheck(submissionId, {
        stage,
        check_name: checkName,
        status,
        details: parsed,
      });
      toast.success('Check recorded');
      setCheckName('');
      setDetails('{}');
      await onCreated();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded border border-dashed border-[var(--border)] p-3">
      <div className="text-xs uppercase tracking-wide text-[var(--text-muted)] mb-2">
        Record check
      </div>
      <div className="grid grid-cols-2 gap-2 text-sm">
        <input
          value={stage}
          onChange={(e) => setStage(e.target.value)}
          placeholder="stage"
          className="rounded border border-[var(--border)] bg-[var(--surface)] px-2 py-1"
        />
        <input
          value={checkName}
          onChange={(e) => setCheckName(e.target.value)}
          placeholder="check_name"
          className="rounded border border-[var(--border)] bg-[var(--surface)] px-2 py-1"
        />
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value as CheckStatus)}
          className="rounded border border-[var(--border)] bg-[var(--surface)] px-2 py-1"
        >
          <option value="passed">passed</option>
          <option value="failed">failed</option>
          <option value="warning">warning</option>
          <option value="errored">errored</option>
        </select>
        <input
          value={details}
          onChange={(e) => setDetails(e.target.value)}
          placeholder="details JSON"
          className="rounded border border-[var(--border)] bg-[var(--surface)] px-2 py-1 font-mono text-xs"
        />
      </div>
      <button
        disabled={busy}
        onClick={() => void submit()}
        className="mt-3 px-3 py-1.5 rounded bg-[var(--primary)] text-white text-sm disabled:opacity-50"
      >
        Add check
      </button>
    </div>
  );
}
