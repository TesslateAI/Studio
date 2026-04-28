"use client";

import { useEffect, useState } from "react";
import { useSession, signOut } from "next-auth/react";
import { useRouter } from "next/navigation";

interface Integration {
  id: string;
  name: string;
  description: string;
  status: "connected" | "degraded" | "not_configured";
  detail: string;
  env_vars: string[];
  configured: boolean;
  docs_url?: string;
}

interface ApiResponse {
  integrations: Integration[];
  demo_mode: boolean;
}

const STATUS_CONFIG = {
  connected: {
    dot: "bg-green-400",
    ring: "ring-green-500/20",
    badge: "bg-green-950 text-green-300",
    label: "Connected",
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
      </svg>
    ),
  },
  degraded: {
    dot: "bg-amber-400",
    ring: "ring-amber-500/20",
    badge: "bg-amber-950 text-amber-300",
    label: "Degraded",
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
      </svg>
    ),
  },
  not_configured: {
    dot: "bg-gray-500",
    ring: "ring-gray-500/20",
    badge: "bg-gray-800 text-gray-400",
    label: "Not Configured",
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
      </svg>
    ),
  },
};

const INTEGRATION_ICONS: Record<string, React.ReactNode> = {
  postgres: (
    <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
      <path d="M17.128 0a10.134 10.134 0 00-2.755.403l-.082.025a10.1 10.1 0 00-.88-.235C12.64.069 11.8 0 11.013 0 8.35 0 6.52.657 5.283 1.846 3.768 3.301 3.18 5.19 3.124 7.044c-.03 1.048.07 2.019.275 2.862.207.856.54 1.594.976 2.15.443.564.985.894 1.59.894.735 0 1.35-.338 1.817-.738.252.59.585 1.122.989 1.539.52.535 1.143.838 1.822.838h.002c.676 0 1.26-.302 1.74-.828.486-.534.817-1.286 1.02-2.206.168.048.33.09.487.124.74.156 1.473.174 2.127.032.67-.145 1.277-.441 1.734-.916.45-.466.7-1.06.7-1.755 0-.716-.262-1.344-.698-1.867a5.65 5.65 0 00-1.12-1.012c.168-.344.31-.722.415-1.122.237-.905.25-1.896-.124-2.803-.38-.924-1.104-1.71-2.19-2.282A8.81 8.81 0 0017.128 0zm.872 14.47a.95.95 0 01-.696.35c-.27 0-.547-.135-.823-.464-.207-.248-.385-.605-.524-1.07a4.27 4.27 0 01-.128-1.052 3.92 3.92 0 01.15-.905c.12-.406.318-.752.554-1.004a1.67 1.67 0 011.212-.561c.29 0 .576.12.826.407.253.29.476.746.624 1.38.075.32.114.67.114 1.04 0 .516-.076.944-.215 1.265-.135.313-.32.506-.494.614zm-4.37 1.474c-.33.363-.697.542-1.07.542-.37 0-.73-.178-1.05-.54-.32-.36-.6-.922-.796-1.698-.19-.755-.293-1.654-.293-2.685 0-.974.097-1.837.28-2.563.19-.743.47-1.324.815-1.707.335-.373.717-.563 1.093-.563.374 0 .744.183 1.077.547.34.37.64.944.843 1.712.194.742.295 1.604.295 2.574 0 .968-.1 1.838-.29 2.58-.19.734-.486 1.3-.904 1.801zM5.87 14.004c-.135-.334-.205-.72-.205-1.162 0-.42.065-.844.19-1.25.12-.395.308-.726.538-.974.224-.24.48-.368.74-.368.257 0 .52.124.77.411.256.294.478.753.62 1.393.076.33.116.686.116 1.057 0 .5-.073.926-.21 1.252-.137.32-.33.52-.517.636a.913.913 0 01-.677.34c-.255 0-.515-.127-.762-.43-.208-.253-.39-.607-.523-1.065z"/>
    </svg>
  ),
  legora: (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.456 2.456z" />
    </svg>
  ),
  google_drive: (
    <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
      <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
      <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
      <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
      <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
    </svg>
  ),
  auth: (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z" />
    </svg>
  ),
  automation: (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
    </svg>
  ),
};

export default function IntegrationsPage() {
  const { data: session, status } = useSession();
  const router = useRouter();
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [demoMode, setDemoMode] = useState(false);
  const [loading, setLoading] = useState(true);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    if (status === "unauthenticated") router.push("/login");
  }, [status, router]);

  const load = async () => {
    setChecking(true);
    try {
      const res = await fetch("/api/integrations");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json: ApiResponse = await res.json();
      setIntegrations(json.integrations);
      setDemoMode(json.demo_mode);
      setLastChecked(new Date());
    } catch {
      // keep stale data
    } finally {
      setLoading(false);
      setChecking(false);
    }
  };

  useEffect(() => {
    if (status === "authenticated") load();
  }, [status]);

  if (status === "loading" || status === "unauthenticated") {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  const connected = integrations.filter((i) => i.status === "connected").length;
  const degraded = integrations.filter((i) => i.status === "degraded").length;
  const unconfigured = integrations.filter((i) => i.status === "not_configured").length;

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      {/* Nav */}
      <header className="border-b border-gray-800 bg-gray-900/50 backdrop-blur-sm sticky top-0 z-10">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <button
              onClick={() => router.push("/dashboard")}
              className="flex items-center gap-2 text-gray-400 hover:text-white transition text-sm"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
              </svg>
              Dashboard
            </button>
            <span className="text-gray-700">/</span>
            <div className="flex items-center gap-2">
              <svg className="w-4 h-4 text-indigo-400" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
              </svg>
              <h1 className="text-base font-semibold">Integrations</h1>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs text-gray-500">
              {lastChecked ? `Checked ${lastChecked.toLocaleTimeString()}` : ""}
            </span>
            <button
              onClick={load}
              disabled={checking}
              className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-white transition px-3 py-1.5 rounded-lg hover:bg-gray-800 disabled:opacity-50"
            >
              <svg className={`w-3.5 h-3.5 ${checking ? "animate-spin" : ""}`} fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
              Recheck
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

      <main className="max-w-5xl mx-auto px-6 py-8">
        {/* Header */}
        <div className="mb-8">
          <h2 className="text-2xl font-bold mb-1">API Integrations</h2>
          <p className="text-gray-400 text-sm">
            Real-time status of all external services connected to this application.
          </p>
        </div>

        {/* Demo mode banner */}
        {demoMode && (
          <div className="mb-6 flex items-start gap-3 px-4 py-3 rounded-xl bg-indigo-950/60 border border-indigo-800/50 text-sm text-indigo-300">
            <svg className="w-4 h-4 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <span>
              <strong>Demo mode active.</strong> The app is running without a live database. Connect a{" "}
              <span className="font-mono text-indigo-200">DATABASE_URL</span> to enable persistence.
            </span>
          </div>
        )}

        {/* Summary stats */}
        {!loading && (
          <div className="grid grid-cols-3 gap-4 mb-8">
            <div className="bg-gray-900 border border-gray-800 rounded-xl px-5 py-4">
              <div className="flex items-center gap-2 mb-1">
                <span className="w-2 h-2 rounded-full bg-green-400" />
                <span className="text-xs text-gray-400 font-medium">Connected</span>
              </div>
              <span className="text-2xl font-bold text-white">{connected}</span>
            </div>
            <div className="bg-gray-900 border border-gray-800 rounded-xl px-5 py-4">
              <div className="flex items-center gap-2 mb-1">
                <span className="w-2 h-2 rounded-full bg-amber-400" />
                <span className="text-xs text-gray-400 font-medium">Degraded</span>
              </div>
              <span className="text-2xl font-bold text-white">{degraded}</span>
            </div>
            <div className="bg-gray-900 border border-gray-800 rounded-xl px-5 py-4">
              <div className="flex items-center gap-2 mb-1">
                <span className="w-2 h-2 rounded-full bg-gray-500" />
                <span className="text-xs text-gray-400 font-medium">Not Configured</span>
              </div>
              <span className="text-2xl font-bold text-white">{unconfigured}</span>
            </div>
          </div>
        )}

        {/* Integration cards */}
        {loading ? (
          <div className="flex items-center justify-center py-20 gap-3 text-gray-400">
            <div className="w-5 h-5 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
            <span className="text-sm">Checking integrations…</span>
          </div>
        ) : (
          <div className="space-y-4">
            {integrations.map((integration) => {
              const cfg = STATUS_CONFIG[integration.status];
              return (
                <div
                  key={integration.id}
                  className={`bg-gray-900 border border-gray-800 rounded-2xl p-5 ring-1 ${cfg.ring}`}
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex items-start gap-4 min-w-0">
                      {/* Icon */}
                      <div className="w-10 h-10 rounded-xl bg-gray-800 flex items-center justify-center flex-shrink-0 text-gray-300">
                        {INTEGRATION_ICONS[integration.id] ?? (
                          <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M14.25 6.087c0-.355.186-.676.401-.959.221-.29.349-.634.349-1.003 0-1.036-1.007-1.875-2.25-1.875s-2.25.84-2.25 1.875c0 .369.128.713.349 1.003.215.283.401.604.401.959v0a.64.64 0 01-.657.643 48.39 48.39 0 01-4.163-.3c.186 1.613.293 3.25.315 4.907a.656.656 0 01-.658.663v0c-.355 0-.676-.186-.959-.401a1.647 1.647 0 00-1.003-.349c-1.036 0-1.875 1.007-1.875 2.25s.84 2.25 1.875 2.25c.369 0 .713-.128 1.003-.349.283-.215.604-.401.959-.401v0c.31 0 .555.26.532.57a48.039 48.039 0 01-.642 5.056c1.518.19 3.058.309 4.616.354a.64.64 0 00.657-.643v0c0-.355-.186-.676-.401-.959a1.647 1.647 0 01-.349-1.003c0-1.035 1.008-1.875 2.25-1.875 1.243 0 2.25.84 2.25 1.875 0 .369-.128.713-.349 1.003-.215.283-.401.604-.401.959v0c0 .333.277.599.61.58a48.1 48.1 0 005.427-.63 48.05 48.05 0 00.582-4.717.532.532 0 00-.533-.57v0c-.355 0-.676.186-.959.401-.29.221-.634.349-1.003.349-1.035 0-1.875-1.007-1.875-2.25s.84-2.25 1.875-2.25c.37 0 .713.128 1.003.349.283.215.604.401.959.401v0a.656.656 0 00.658-.663 48.422 48.422 0 00-.37-5.36c-1.886.342-3.81.574-5.766.689a.578.578 0 01-.61-.58z" />
                          </svg>
                        )}
                      </div>

                      {/* Info */}
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <h3 className="text-base font-semibold text-white">{integration.name}</h3>
                          <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium ${cfg.badge}`}>
                            <span className={`w-1.5 h-1.5 rounded-full ${cfg.dot}`} />
                            {cfg.label}
                          </span>
                        </div>
                        <p className="text-sm text-gray-400 mt-0.5">{integration.description}</p>
                        <p className="text-xs text-gray-500 mt-2 flex items-center gap-1.5">
                          <span className={`${integration.status === "connected" ? "text-green-400" : integration.status === "degraded" ? "text-amber-400" : "text-gray-500"}`}>
                            {cfg.icon}
                          </span>
                          {integration.detail}
                        </p>
                      </div>
                    </div>

                    {/* Docs link */}
                    {integration.docs_url && (
                      <a
                        href={integration.docs_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex-shrink-0 text-xs text-gray-500 hover:text-indigo-400 transition flex items-center gap-1"
                      >
                        Docs
                        <svg className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                        </svg>
                      </a>
                    )}
                  </div>

                  {/* Env vars */}
                  <div className="mt-4 pt-4 border-t border-gray-800 flex flex-wrap gap-2">
                    <span className="text-xs text-gray-600 self-center mr-1">Env vars:</span>
                    {integration.env_vars.map((v) => (
                      <span key={v} className="font-mono text-xs px-2 py-0.5 rounded bg-gray-800 text-gray-400 border border-gray-700">
                        {v}
                      </span>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </main>
    </div>
  );
}
