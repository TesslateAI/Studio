"use client";

import { useEffect, useState, useCallback } from "react";
import { useSession, signOut } from "next-auth/react";
import { useRouter } from "next/navigation";
import type { IntakeSubmission, SubmissionStatus } from "@/lib/types";

const STATUS_STYLES: Record<SubmissionStatus, { bg: string; text: string; dot: string; label: string }> = {
  New:               { bg: "bg-gray-800",   text: "text-gray-300",  dot: "bg-gray-400",   label: "New" },
  "Docs Received":   { bg: "bg-amber-950",  text: "text-amber-300", dot: "bg-amber-400",  label: "Docs Received" },
  Redlining:         { bg: "bg-yellow-950", text: "text-yellow-300",dot: "bg-yellow-400", label: "Redlining" },
  "Ready for Review":{ bg: "bg-blue-950",   text: "text-blue-300",  dot: "bg-blue-400",   label: "Ready for Review" },
  Complete:          { bg: "bg-green-950",  text: "text-green-300", dot: "bg-green-400",  label: "Complete" },
};

interface SubmissionRow extends IntakeSubmission {
  submitted_at: string;
}

interface ApiResponse {
  data: SubmissionRow[];
  total: number;
  page: number;
  pages: number;
}

function StatusBadge({ status }: { status: SubmissionStatus }) {
  const s = STATUS_STYLES[status] ?? STATUS_STYLES["New"];
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${s.bg} ${s.text}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} />
      {s.label}
    </span>
  );
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

export default function DashboardPage() {
  const { data: session, status } = useSession();
  const router = useRouter();
  const [rows, setRows] = useState<SubmissionRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterStatus, setFilterStatus] = useState("");
  const [filterAttention, setFilterAttention] = useState(false);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const params = new URLSearchParams();
    if (filterStatus) params.set("status", filterStatus);
    if (filterAttention) params.set("attention", "true");
    params.set("page", String(page));
    params.set("limit", "25");

    try {
      const res = await fetch(`/api/submissions?${params}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json: ApiResponse = await res.json();
      setRows(json.data);
      setTotal(json.total);
      setPages(json.pages);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load submissions");
    } finally {
      setLoading(false);
    }
  }, [filterStatus, filterAttention, page]);

  useEffect(() => {
    if (status === "unauthenticated") router.push("/login");
  }, [status, router]);

  useEffect(() => {
    if (status === "authenticated") load();
  }, [status, load]);

  if (status === "loading" || status === "unauthenticated") {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      {/* Top nav */}
      <header className="border-b border-gray-800 bg-gray-900/50 backdrop-blur-sm sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center">
              <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round"
                  d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </div>
            <div>
              <h1 className="text-base font-bold leading-tight">Intake Queue</h1>
              <p className="text-xs text-gray-400">
                {total} submission{total !== 1 ? "s" : ""}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <span className="text-sm text-gray-400 hidden sm:inline">
              {session?.user?.name}
            </span>
            <button
              onClick={() => router.push("/dashboard/integrations")}
              className="text-xs text-gray-400 hover:text-white transition px-3 py-1.5 rounded-lg hover:bg-gray-800 flex items-center gap-1.5"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
              </svg>
              Integrations
            </button>
            <button
              onClick={() => signOut({ callbackUrl: "/login" })}
              className="text-xs text-gray-500 hover:text-gray-300 transition px-3 py-1.5 rounded-lg hover:bg-gray-800"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-6">
        {/* Filters */}
        <div className="flex flex-wrap gap-3 mb-5">
          <select
            value={filterStatus}
            onChange={(e) => { setFilterStatus(e.target.value); setPage(1); }}
            className="px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            <option value="">All Statuses</option>
            <option value="New">New</option>
            <option value="Docs Received">Docs Received</option>
            <option value="Redlining">Redlining</option>
            <option value="Ready for Review">Ready for Review</option>
            <option value="Complete">Complete</option>
          </select>

          <label className="flex items-center gap-2 px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-sm text-gray-200 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={filterAttention}
              onChange={(e) => { setFilterAttention(e.target.checked); setPage(1); }}
              className="rounded accent-indigo-500"
            />
            Needs Attention Only
          </label>

          <button
            onClick={load}
            className="ml-auto px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-sm text-gray-300 hover:bg-gray-700 transition"
          >
            ↺ Refresh
          </button>
        </div>

        {/* Table */}
        <div className="bg-gray-900 border border-gray-800 rounded-2xl overflow-hidden shadow-xl">
          {error ? (
            <div className="px-6 py-12 text-center">
              <p className="text-red-400 text-sm">{error}</p>
              <button onClick={load} className="mt-3 text-xs text-gray-400 underline">
                Try again
              </button>
            </div>
          ) : loading ? (
            <div className="px-6 py-12 flex items-center justify-center gap-3">
              <div className="w-5 h-5 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
              <span className="text-sm text-gray-400">Loading submissions…</span>
            </div>
          ) : rows.length === 0 ? (
            <div className="px-6 py-12 text-center text-gray-500 text-sm">
              No submissions found.
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-800">
                      <th className="text-left px-5 py-3.5 font-semibold text-gray-400 whitespace-nowrap">Client</th>
                      <th className="text-left px-5 py-3.5 font-semibold text-gray-400 whitespace-nowrap">Matter Type</th>
                      <th className="text-left px-5 py-3.5 font-semibold text-gray-400 whitespace-nowrap">Submitted</th>
                      <th className="text-left px-5 py-3.5 font-semibold text-gray-400 whitespace-nowrap">Status</th>
                      <th className="text-left px-5 py-3.5 font-semibold text-gray-400 whitespace-nowrap">Attention</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row) => (
                      <tr
                        key={row.id}
                        onClick={() => router.push(`/dashboard/${row.id}`)}
                        className="border-b border-gray-800/60 hover:bg-gray-800/40 cursor-pointer transition-colors group"
                      >
                        <td className="px-5 py-4">
                          <span className="font-medium text-white group-hover:text-indigo-300 transition-colors">
                            {row.last_name}, {row.first_name}
                          </span>
                        </td>
                        <td className="px-5 py-4 text-gray-300">{row.matter_type}</td>
                        <td className="px-5 py-4 text-gray-400 whitespace-nowrap">{formatDate(row.submitted_at)}</td>
                        <td className="px-5 py-4"><StatusBadge status={row.status} /></td>
                        <td className="px-5 py-4">
                          {row.needs_attention ? (
                            <span className="inline-flex items-center gap-1.5 text-xs font-medium text-red-400">
                              <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
                              Needs Attention
                            </span>
                          ) : (
                            <span className="text-gray-600 text-xs">—</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {pages > 1 && (
                <div className="px-5 py-3 border-t border-gray-800 flex items-center justify-between text-xs text-gray-400">
                  <span>Page {page} of {pages}</span>
                  <div className="flex gap-2">
                    <button
                      disabled={page <= 1}
                      onClick={() => setPage((p) => p - 1)}
                      className="px-2.5 py-1 rounded bg-gray-800 hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      ← Prev
                    </button>
                    <button
                      disabled={page >= pages}
                      onClick={() => setPage((p) => p + 1)}
                      className="px-2.5 py-1 rounded bg-gray-800 hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      Next →
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </main>
    </div>
  );
}
