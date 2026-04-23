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
