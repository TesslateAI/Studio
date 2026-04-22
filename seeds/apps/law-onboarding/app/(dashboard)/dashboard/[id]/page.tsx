"use client";

import { useEffect, useState, useCallback } from "react";
import { useSession } from "next-auth/react";
import { useRouter, useParams } from "next/navigation";
import Link from "next/link";
import type { IntakeSubmission, SubmissionStatus, FileRef } from "@/lib/types";

interface AuditEntry {
  id: string;
  occurred_at: string;
  event_type: string;
  actor: string;
  from_status: string | null;
  to_status: string | null;
  detail: Record<string, unknown> | null;
}

interface SubmissionDetail extends IntakeSubmission {
  submitted_at: string;
  audit_entries: AuditEntry[];
}

const STATUS_STYLES: Record<SubmissionStatus, { bg: string; text: string; dot: string }> = {
  New:                 { bg: "bg-gray-800",   text: "text-gray-300",   dot: "bg-gray-400" },
  "Docs Received":     { bg: "bg-amber-950",  text: "text-amber-300",  dot: "bg-amber-400" },
  Redlining:           { bg: "bg-yellow-950", text: "text-yellow-300", dot: "bg-yellow-400" },
  "Ready for Review":  { bg: "bg-blue-950",   text: "text-blue-300",   dot: "bg-blue-400" },
  Complete:            { bg: "bg-green-950",  text: "text-green-300",  dot: "bg-green-400" },
};

function StatusBadge({ status }: { status: SubmissionStatus }) {
  const s = STATUS_STYLES[status] ?? STATUS_STYLES["New"];
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${s.bg} ${s.text}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} />
      {status}
    </span>
  );
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleString("en-US", {
    month: "short", day: "numeric", year: "numeric",
    hour: "numeric", minute: "2-digit", hour12: true,
  });
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-start gap-1">
      <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide w-36 shrink-0 pt-0.5">{label}</dt>
      <dd className="text-sm text-gray-200">{value ?? <span className="text-gray-600">—</span>}</dd>
    </div>
  );
}

export default function SubmissionDetailPage() {
  const { status: authStatus } = useSession();
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const id = params.id;

  const [sub, setSub] = useState<SubmissionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Notes
  const [notes, setNotes] = useState("");
  const [savingNotes, setSavingNotes] = useState(false);
  const [notesSaved, setNotesSaved] = useState(false);

  // Action state
  const [actionLoading, setActionLoading] = useState<"redline" | "complete" | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // Audit panel
  const [auditOpen, setAuditOpen] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/submissions/${id}`);
      if (!res.ok) {
        if (res.status === 404) { router.push("/dashboard"); return; }
        throw new Error(`HTTP ${res.status}`);
      }
      const data: SubmissionDetail = await res.json();
      setSub(data);
      setNotes(data.notes ?? "");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [id, router]);

  useEffect(() => {
    if (authStatus === "unauthenticated") router.push("/login");
  }, [authStatus, router]);

  useEffect(() => {
    if (authStatus === "authenticated") load();
  }, [authStatus, load]);

  const saveNotes = async () => {
    if (!id) return;
    setSavingNotes(true);
    try {
      await fetch(`/api/submissions/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ notes }),
      });
      setNotesSaved(true);
      setTimeout(() => setNotesSaved(false), 2000);
    } finally {
      setSavingNotes(false);
    }
  };

  const runRedline = async () => {
    if (!id || !sub) return;
    setActionError(null);
    setActionLoading("redline");
    try {
      const res = await fetch(`/api/submissions/${id}/run-redline`, { method: "POST" });
      if (!res.ok) throw new Error((await res.json()).error ?? "Error");
      // Optimistic status update
      setSub((prev) => prev ? { ...prev, status: "Redlining" } : prev);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Failed to trigger redline");
    } finally {
      setActionLoading(null);
    }
  };

  const markComplete = async () => {
    if (!id || !sub) return;
    setActionError(null);
    setActionLoading("complete");
    try {
      const res = await fetch(`/api/submissions/${id}/mark-complete`, { method: "POST" });
      if (!res.ok) throw new Error((await res.json()).error ?? "Error");
      setSub((prev) => prev ? { ...prev, status: "Complete", needs_attention: false } : prev);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Failed to mark complete");
    } finally {
      setActionLoading(null);
    }
  };

  if (authStatus === "loading" || loading) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (error || !sub) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center">
        <p className="text-red-400">{error ?? "Submission not found"}</p>
      </div>
    );
  }

  const canRedline = ["Docs Received", "Ready for Review"].includes(sub.status);
  const canComplete = ["Ready for Review", "Redlining", "Docs Received"].includes(sub.status);

  const uploadedRefs: FileRef[] =
    typeof sub.uploaded_file_refs === "string"
      ? JSON.parse(sub.uploaded_file_refs)
      : sub.uploaded_file_refs ?? [];

  const redlineRefs: FileRef[] =
    typeof sub.redline_file_refs === "string"
      ? JSON.parse(sub.redline_file_refs as unknown as string)
      : sub.redline_file_refs ?? [];

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      {/* Top nav */}
      <header className="border-b border-gray-800 bg-gray-900/50 backdrop-blur-sm sticky top-0 z-10">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center gap-4">
          <Link
            href="/dashboard"
            className="text-gray-400 hover:text-white transition text-sm flex items-center gap-1.5"
          >
            ← Queue
          </Link>
          <span className="text-gray-700">/</span>
          <span className="text-sm text-gray-300 font-medium">
            {sub.last_name}, {sub.first_name}
          </span>
          <StatusBadge status={sub.status} />
          {sub.needs_attention && (
            <span className="inline-flex items-center gap-1.5 text-xs font-medium text-red-400 ml-1">
              <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
              Needs Attention
            </span>
          )}
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-8 space-y-6">

        {/* Needs Attention Banner */}
        {sub.needs_attention && (
          <div className="bg-red-950/50 border border-red-800 rounded-xl px-5 py-4 flex items-start gap-3">
            <svg className="w-5 h-5 text-red-400 mt-0.5 shrink-0" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
            </svg>
            <div>
              <p className="text-sm font-semibold text-red-300">Attention Required</p>
              <p className="text-xs text-red-400 mt-0.5">
                An automation step encountered an issue. Review the audit log for details.
              </p>
            </div>
          </div>
        )}

        {/* Action buttons */}
        <div className="flex flex-wrap gap-3">
          {canRedline && (
            <button
              onClick={runRedline}
              disabled={!!actionLoading}
              className="px-5 py-2.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50
                         disabled:cursor-not-allowed rounded-xl text-sm font-semibold transition-colors
                         flex items-center gap-2"
            >
              {actionLoading === "redline" ? (
                <>
                  <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Triggering…
                </>
              ) : (
                <>
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
                  </svg>
                  Run Redline
                </>
              )}
            </button>
          )}

          {canComplete && (
            <button
              onClick={markComplete}
              disabled={!!actionLoading}
              className="px-5 py-2.5 bg-green-700 hover:bg-green-600 disabled:opacity-50
                         disabled:cursor-not-allowed rounded-xl text-sm font-semibold transition-colors
                         flex items-center gap-2"
            >
              {actionLoading === "complete" ? (
                <>
                  <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Saving…
                </>
              ) : (
                <>
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  Mark Complete
                </>
              )}
            </button>
          )}

          {actionError && (
            <p className="text-red-400 text-sm self-center">{actionError}</p>
          )}
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Main content — left 2 columns */}
          <div className="lg:col-span-2 space-y-6">

            {/* Intake answers */}
            <section className="bg-gray-900 border border-gray-800 rounded-2xl p-6">
              <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-5">
                Intake Details
              </h2>
              <dl className="space-y-4">
                <InfoRow label="Client" value={`${sub.first_name} ${sub.last_name}`} />
                <InfoRow label="Email" value={
                  <a href={`mailto:${sub.email}`} className="text-indigo-400 hover:underline">{sub.email}</a>
                } />
                <InfoRow label="Phone" value={sub.phone} />
                <InfoRow label="Matter Type" value={sub.matter_type} />
                <InfoRow label="Submitted" value={formatDate(sub.submitted_at)} />
                <InfoRow label="Description" value={
                  <span className="whitespace-pre-wrap text-gray-300">{sub.description}</span>
                } />
                {sub.drive_folder_url && (
                  <InfoRow label="Drive Folder" value={
                    <a
                      href={sub.drive_folder_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-indigo-400 hover:underline flex items-center gap-1"
                    >
                      Open in Drive ↗
                    </a>
                  } />
                )}
              </dl>
            </section>

            {/* Uploaded files */}
            {uploadedRefs.length > 0 && (
              <section className="bg-gray-900 border border-gray-800 rounded-2xl p-6">
                <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-4">
                  Client Documents ({uploadedRefs.length})
                </h2>
                <ul className="space-y-2">
                  {uploadedRefs.map((f) => (
                    <li key={f.id} className="flex items-center justify-between bg-gray-800/50 rounded-lg px-4 py-3">
                      <div className="flex items-center gap-3 min-w-0">
                        <div className={`w-7 h-7 rounded flex items-center justify-center text-xs font-bold shrink-0 ${
                          f.mime === "application/pdf" ? "bg-red-900 text-red-300" : "bg-blue-900 text-blue-300"
                        }`}>
                          {f.mime === "application/pdf" ? "PDF" : "DOC"}
                        </div>
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-gray-200 truncate">{f.name}</p>
                          <p className="text-xs text-gray-500">{f.size ? formatBytes(f.size) : ""}</p>
                        </div>
                      </div>
                      {f.drive_url && (
                        <a
                          href={f.drive_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-xs text-indigo-400 hover:underline shrink-0 ml-3"
                        >
                          View ↗
                        </a>
                      )}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {/* Redlined files */}
            {redlineRefs.length > 0 && (
              <section className="bg-gray-900 border border-gray-800 rounded-2xl p-6">
                <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-4">
                  Redlined Documents ({redlineRefs.length})
                </h2>
                <ul className="space-y-2">
                  {redlineRefs.map((f) => (
                    <li key={f.id} className="flex items-center justify-between bg-gray-800/50 rounded-lg px-4 py-3">
                      <div className="flex items-center gap-3 min-w-0">
                        <div className="w-7 h-7 rounded flex items-center justify-center text-xs font-bold shrink-0 bg-purple-900 text-purple-300">
                          DOC
                        </div>
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-gray-200 truncate">{f.name}</p>
                          {f.legora_confidence !== undefined && (
                            <p className={`text-xs font-medium mt-0.5 ${
                              f.legora_confidence >= 0.75 ? "text-green-400" : "text-red-400"
                            }`}>
                              Confidence: {(f.legora_confidence * 100).toFixed(0)}%
                            </p>
                          )}
                        </div>
                      </div>
                      {f.drive_url && (
                        <a
                          href={f.drive_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-xs text-indigo-400 hover:underline shrink-0 ml-3"
                        >
                          View ↗
                        </a>
                      )}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {/* Audit log */}
            <section className="bg-gray-900 border border-gray-800 rounded-2xl overflow-hidden">
              <button
                onClick={() => setAuditOpen((o) => !o)}
                className="w-full flex items-center justify-between px-6 py-4 text-left hover:bg-gray-800/50 transition-colors"
              >
                <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide">
                  Audit Log ({sub.audit_entries?.length ?? 0})
                </h2>
                <svg
                  className={`w-4 h-4 text-gray-500 transition-transform ${auditOpen ? "rotate-180" : ""}`}
                  fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                </svg>
              </button>

              {auditOpen && (
                <div className="border-t border-gray-800 px-6 py-4">
                  {(!sub.audit_entries || sub.audit_entries.length === 0) ? (
                    <p className="text-sm text-gray-600">No audit entries yet.</p>
                  ) : (
                    <ol className="relative border-l border-gray-700 space-y-4 ml-2">
                      {sub.audit_entries.map((entry) => (
                        <li key={entry.id} className="ml-4">
                          <span className="absolute -left-1.5 w-3 h-3 rounded-full border-2 border-gray-900 bg-gray-500" />
                          <div className="flex flex-wrap items-center gap-2 mb-1">
                            <span className="text-xs font-semibold text-gray-300 bg-gray-800 px-2 py-0.5 rounded">
                              {entry.event_type}
                            </span>
                            {entry.from_status && entry.to_status && (
                              <span className="text-xs text-gray-500">
                                {entry.from_status} → {entry.to_status}
                              </span>
                            )}
                            <span className="text-xs text-gray-600">
                              {entry.actor} · {formatDate(entry.occurred_at)}
                            </span>
                          </div>
                          {entry.detail && (
                            <p className="text-xs text-gray-500 font-mono">
                              {typeof entry.detail === "string"
                                ? entry.detail
                                : JSON.stringify(entry.detail)}
                            </p>
                          )}
                        </li>
                      ))}
                    </ol>
                  )}
                </div>
              )}
            </section>
          </div>

          {/* Sidebar */}
          <div className="space-y-6">
            {/* Status card */}
            <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5">
              <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Status</h3>
              <StatusBadge status={sub.status} />
            </div>

            {/* Notes */}
            <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5">
              <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
                Attorney Notes
              </h3>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={6}
                placeholder="Add notes…"
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2.5 text-sm
                           text-gray-200 placeholder-gray-600 resize-none
                           focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
              <button
                onClick={saveNotes}
                disabled={savingNotes}
                className="mt-2 w-full py-2 px-3 bg-gray-700 hover:bg-gray-600 disabled:opacity-50
                           rounded-lg text-sm font-medium text-gray-200 transition-colors"
              >
                {savingNotes ? "Saving…" : notesSaved ? "✓ Saved" : "Save Notes"}
              </button>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
