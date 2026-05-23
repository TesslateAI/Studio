# @tesslate/app-sdk (TypeScript)

Headless SDK for authoring, publishing, installing, and invoking Tesslate Apps
against a Studio deployment. It wraps the REST API with typed method calls,
ships zero runtime dependencies (uses global `fetch`), and accepts an
injectable fetch for tests. A fluent `ManifestBuilder` produces manifests that
conform to the `2025-01` schema (see `docs/specs/app-manifest-2025-01.md`).

Authentication uses a Tesslate external API key (`tsk_...`) sent as
`Authorization: Bearer tsk_...`. Because the SDK always authenticates with a
Bearer token, the server's CSRF middleware does not apply — CSRF cookies and
the `X-CSRF-Token` header are only required for cookie-authenticated browser
sessions, which this SDK does not use.

```ts
import { AppClient, ManifestBuilder } from "@tesslate/app-sdk";

const client = new AppClient({
  baseUrl: "https://opensail.tesslate.com",
  apiKey: process.env.TESSLATE_API_KEY!, // "tsk_..."
});

const manifest = new ManifestBuilder()
  .app({ slug: "hello", name: "Hello App", version: "0.1.0" })
  .surface({ kind: "iframe", entry: "index.html" })
  .billing({ model: "wallet-mix", default_budget_usd: 0.25 })
  .requireFeatures(["apps.v1"])
  .build();

const published = await client.publishVersion({
  projectId: "…",
  manifest,
});

const install = await client.installApp({
  appVersionId: published.app_version_id,
  teamId: "…",
  walletMixConsent: { accepted: true },
  mcpConsents: [],
});

const session = await client.beginSession({
  appInstanceId: install.app_instance_id,
  budgetUsd: 1.0,
  ttlSeconds: 3600,
});
// Use session.api_key against LiteLLM, then:
await client.endSession(session.session_id);
```

## Reading + writing the project's Workspace Data Store

Every Tesslate App installed into a project automatically inherits the
project's built-in Workspace Data Store env-var contract. The platform
auto-injects these on container start AND on every external deploy:

| Runtime               | URL var                                 | Key var                            |
| --------------------- | --------------------------------------- | ---------------------------------- |
| Server (Node, Python, Go) | `OPENSAIL_DATA_API_URL`             | `OPENSAIL_DATA_KEY`                |
| Vite browser bundle   | `VITE_OPENSAIL_DATA_API_URL`            | `VITE_OPENSAIL_DATA_KEY`           |
| Next.js client comp   | `NEXT_PUBLIC_OPENSAIL_DATA_API_URL`     | `NEXT_PUBLIC_OPENSAIL_DATA_KEY`    |

The key is a stable per-project HMAC-derived anon key — it survives
container restarts and deploys (no need to refresh it after rotation).

HTTP shape (no `/collections/` prefix, no `/records` suffix):

```
POST   ${URL}/{collection}                 JSON body         -> 201 {id, data, ...}
GET    ${URL}/{collection}?limit=&offset=  -> 200 {records, total, limit, offset}
GET    ${URL}/{collection}/{record_id}
PATCH  ${URL}/{collection}/{record_id}     JSON body         (replaces document)
DELETE ${URL}/{collection}/{record_id}     -> 204
```

A drop-in TypeScript helper exists at `packages/tesslate-marketplace`'s
`workspace-data-sdk` skill (`load_skill workspace-data-sdk`) and is
auto-scaffolded into every project created from a Next.js / Vite base.
App authors writing custom code should mirror that helper — see
`docs/apps/CLAUDE.md` for the architecture notes.

The same data your app writes is queryable by the user's Tesslate Agent
via the `workspace_data` tool (`@app:<your-slug>` in chat surfaces the
collections to the agent so it can summarize/aggregate without leaving
the conversation).
