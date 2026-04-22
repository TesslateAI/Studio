export default function Home() {
  return (
    <main className="min-h-screen bg-[var(--background)]">
      {/* Hero */}
      <section className="relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-b from-blue-600/5 via-transparent to-transparent dark:from-blue-500/10" />
        <div className="relative mx-auto max-w-5xl px-6 pt-24 pb-20 sm:pt-32 sm:pb-28">
          <div className="flex flex-col items-center text-center">
            <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--card)] px-4 py-1.5 text-sm text-[var(--muted)]">
              <span className="inline-block h-2 w-2 rounded-full bg-green-500" />
              v16.1.6 -- Latest Stable Release
            </div>

            <h1 className="text-5xl font-bold tracking-tight sm:text-7xl">
              Next.js{" "}
              <span className="bg-gradient-to-r from-blue-600 to-cyan-500 bg-clip-text text-transparent">
                16
              </span>
            </h1>

            <p className="mt-6 max-w-2xl text-lg leading-relaxed text-[var(--muted)] sm:text-xl">
              The fullstack React framework for the web. Build fast, dynamic
              applications with the App Router, React Server Components, and
              Turbopack -- all with zero configuration.
            </p>

            <div className="mt-10 flex flex-wrap items-center justify-center gap-4">
              <a
                href="https://nextjs.org/docs"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 rounded-lg bg-[var(--foreground)] px-6 py-3 text-sm font-medium text-[var(--background)] transition-opacity hover:opacity-90"
              >
                Read the Docs
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 16 16"
                  fill="none"
                  className="opacity-70"
                >
                  <path
                    d="M6.5 3.5L11 8L6.5 12.5"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </a>
              <a
                href="/api/hello"
                target="_blank"
                className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-6 py-3 text-sm font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--card)]"
              >
                Try the API Route
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 16 16"
                  fill="none"
                  className="opacity-50"
                >
                  <path
                    d="M4.5 11.5L11.5 4.5M11.5 4.5H6M11.5 4.5V10"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </a>
            </div>
          </div>
        </div>
      </section>

      {/* Tech Stack Bar */}
      <section className="border-y border-[var(--border)] bg-[var(--card)]/50">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-center gap-x-10 gap-y-4 px-6 py-6 text-sm text-[var(--muted)]">
          <span className="font-medium text-[var(--foreground)]">
            Built with
          </span>
          <span>Next.js 16.1</span>
          <span className="hidden sm:inline text-[var(--border)]">|</span>
          <span>React 19.2</span>
          <span className="hidden sm:inline text-[var(--border)]">|</span>
          <span>TypeScript 5.9</span>
          <span className="hidden sm:inline text-[var(--border)]">|</span>
          <span>Tailwind CSS v4.2</span>
          <span className="hidden sm:inline text-[var(--border)]">|</span>
          <span>Turbopack</span>
        </div>
      </section>

      {/* Features Grid */}
      <section className="mx-auto max-w-5xl px-6 py-20 sm:py-28">
        <div className="mb-12 text-center">
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            Everything you need to ship
          </h2>
          <p className="mt-4 text-lg text-[var(--muted)]">
            Next.js 16 brings the latest from React and the Vercel platform
            together into a single, cohesive developer experience.
          </p>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <FeatureCard
            title="React Compiler"
            description="Automatic memoization of components and hooks. No more manual useMemo or useCallback -- the compiler optimizes your code at build time."
          />
          <FeatureCard
            title="Turbopack"
            description="Rust-powered bundler delivering near-instant dev server startup and fast refresh. Production builds are faster than ever."
          />
          <FeatureCard
            title="App Router"
            description="File-system routing with nested layouts, loading states, error boundaries, and parallel routes built into the framework."
          />
          <FeatureCard
            title="Server Components"
            description="Render on the server by default. Ship zero JavaScript for static content and stream dynamic parts as they resolve."
          />
          <FeatureCard
            title="Server Actions"
            description="Mutate data with type-safe server functions called directly from your components. No API layer to maintain."
          />
          <FeatureCard
            title="View Transitions"
            description="Animate between pages and state changes with the native View Transitions API, deeply integrated into the router."
          />
          <FeatureCard
            title="Cache Components"
            description="Fine-grained caching with the 'use cache' directive. Cache entire pages, individual components, or standalone functions."
          />
          <FeatureCard
            title="Streaming & Suspense"
            description="Progressive rendering with React Suspense. Show instant loading states while data fetches complete in the background."
          />
          <FeatureCard
            title="API Routes"
            description="Build REST or GraphQL endpoints alongside your pages. Full support for middleware, edge runtime, and streaming responses."
          />
        </div>
      </section>

      {/* Code Example */}
      <section className="border-t border-[var(--border)]">
        <div className="mx-auto max-w-5xl px-6 py-20 sm:py-28">
          <div className="grid gap-12 lg:grid-cols-2 lg:items-center">
            <div>
              <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
                Start building in seconds
              </h2>
              <p className="mt-4 text-lg leading-relaxed text-[var(--muted)]">
                This template ships with everything configured. The App Router
                handles your pages, API routes power your backend, and Tailwind
                CSS styles your interface. Just start writing components.
              </p>
              <ul className="mt-8 space-y-3 text-[var(--muted)]">
                <li className="flex items-start gap-3">
                  <span className="mt-1.5 block h-1.5 w-1.5 shrink-0 rounded-full bg-blue-500" />
                  Create pages in <code className="text-sm font-medium text-[var(--foreground)]">app/</code> -- they route automatically
                </li>
                <li className="flex items-start gap-3">
                  <span className="mt-1.5 block h-1.5 w-1.5 shrink-0 rounded-full bg-blue-500" />
                  Add API endpoints in <code className="text-sm font-medium text-[var(--foreground)]">app/api/</code> with route handlers
                </li>
                <li className="flex items-start gap-3">
                  <span className="mt-1.5 block h-1.5 w-1.5 shrink-0 rounded-full bg-blue-500" />
                  Drop components into <code className="text-sm font-medium text-[var(--foreground)]">app/components/</code> and import them
                </li>
                <li className="flex items-start gap-3">
                  <span className="mt-1.5 block h-1.5 w-1.5 shrink-0 rounded-full bg-blue-500" />
                  Style with Tailwind utility classes or edit <code className="text-sm font-medium text-[var(--foreground)]">globals.css</code>
                </li>
              </ul>
            </div>

            <div className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-1">
              <div className="flex items-center gap-1.5 px-4 py-3">
                <span className="h-3 w-3 rounded-full bg-red-500/20" />
                <span className="h-3 w-3 rounded-full bg-yellow-500/20" />
                <span className="h-3 w-3 rounded-full bg-green-500/20" />
                <span className="ml-2 text-xs text-[var(--muted)]">
                  app/page.tsx
                </span>
              </div>
              <pre className="overflow-x-auto px-4 pb-4 text-sm leading-relaxed">
                <code>{`export default function Page() {
  return (
    <main>
      <h1>Hello, Next.js 16</h1>
      <p>Start editing this page.</p>
    </main>
  )
}`}</code>
              </pre>
            </div>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-[var(--border)]">
        <div className="mx-auto flex max-w-5xl flex-col items-center justify-between gap-4 px-6 py-8 sm:flex-row">
          <p className="text-sm text-[var(--muted)]">
            Next.js 16.1 -- React 19.2 -- TypeScript 5.9 -- Tailwind CSS v4.2
          </p>
          <div className="flex gap-6 text-sm text-[var(--muted)]">
            <a
              href="https://nextjs.org/docs"
              target="_blank"
              rel="noopener noreferrer"
              className="transition-colors hover:text-[var(--foreground)]"
            >
              Docs
            </a>
            <a
              href="https://nextjs.org/blog/next-16"
              target="_blank"
              rel="noopener noreferrer"
              className="transition-colors hover:text-[var(--foreground)]"
            >
              Blog
            </a>
            <a
              href="https://github.com/vercel/next.js"
              target="_blank"
              rel="noopener noreferrer"
              className="transition-colors hover:text-[var(--foreground)]"
            >
              GitHub
            </a>
          </div>
        </div>
      </footer>
    </main>
  );
}

function FeatureCard({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="group rounded-xl border border-[var(--border)] bg-[var(--card)]/50 p-6 transition-colors hover:border-[var(--accent)]/30 hover:bg-[var(--card)]">
      <h3 className="text-base font-semibold">{title}</h3>
      <p className="mt-2 text-sm leading-relaxed text-[var(--muted)]">
        {description}
      </p>
    </div>
  );
}
