# @tesslate/sdk

TypeScript SDK for the OpenSail REST API. Source at `/sdk/`.

## Overview

| Item | Value |
| ---- | ----- |
| Package name | `@tesslate/sdk` |
| Version | `0.1.0` |
| License | MIT |
| Runtime | Node `>=18`, browsers with global `fetch` |
| Output formats | ESM (`dist/index.js`) + CJS (`dist/index.cjs`) + `.d.ts` + `.d.cts` |
| Auth | Bearer token (`tsk_*` external API key) |

Distinct from:

- `packages/tesslate-app-sdk/ts`: targets the Tesslate Apps REST surface (manifest publish, install, invoke).
- `packages/tesslate-embed-sdk`: iframe-side postMessage client for apps rendered in the Studio shell.

## Install and build

```bash
cd sdk
npm install
npm run build          # tsup -> dist/
npm run typecheck      # tsc --noEmit
TESSLATE_API_KEY=tsk_... npx tsx smoke-test.ts
```

## Quick start

```ts
import { TesslateClient } from "@tesslate/sdk";

const client = new TesslateClient({
  apiKey: process.env.TESSLATE_API_KEY!,
  baseUrl: "https://opensail.tesslate.com",
});

const projects = await client.projects.list();
const files = client.projects.files(projects[0].slug);
const tree = await files.tree();
```

## Public surface

### Client

- `TesslateClient({ apiKey, baseUrl?, timeout? })`: mounts `.projects`, `.agent`, `.shell`.

### Resources

| Resource | Accessor | Scope | File |
| -------- | -------- | ----- | ---- |
| Projects | `client.projects` | global | `src/resources/projects.ts` |
| Files | `client.projects.files(slug)` | project slug | `src/resources/files.ts` |
| Containers | `client.projects.containers(slug)` | project slug | `src/resources/containers.ts` |
| Git | `client.projects.git(projectId)` | project id | `src/resources/git.ts` |
| Agent | `client.agent` | global | `src/resources/agent.ts` |
| Shell | `client.shell` | global | `src/resources/shell.ts` |

### Errors

All network errors derive from `TesslateError`. HTTP status codes map to:

| Status | Class |
| ------ | ----- |
| 401 | `TesslateAuthError` |
| 403 | `TesslateForbiddenError` |
| 404 | `TesslateNotFoundError` |
| any other non-2xx | `TesslateApiError` |

Each error carries `status`, optional `code`, and parsed `body`.

### Utilities

- `parseSSE<T>(response)`: async generator that yields JSON-decoded server-sent events from a `Response.body` stream. Terminates on `[DONE]`. Used internally by `AgentResource.events()`.

## Agent streaming example

```ts
const { task_id } = await client.agent.invoke({
  project_id: "proj-abc",
  message: "add a readme",
});

for await (const event of client.agent.events(task_id)) {
  console.log(event);
}

// Or block until terminal:
const final = await client.agent.invokeAndWait(
  { project_id: "proj-abc", message: "..." },
  2000,
);
```

## Shell convenience

```ts
const output = await client.shell.run(
  projectId,
  "ls -la && cat package.json",
  { waitMs: 3000 },
);
```

`run()` opens a session, writes `command + "\nexit\n"`, waits `waitMs`, reads base64-decoded output, closes the session.

## Smoke test

`sdk/smoke-test.ts` exercises every resource end-to-end against a live backend. It:

1. Creates a disposable project.
2. Reads and writes files in it.
3. Starts containers, runs a shell command, stops containers.
4. Invokes an agent and streams a few events.
5. Deletes the project.

Required env:

| Var | Purpose |
| --- | ------- |
| `TESSLATE_API_KEY` | External API key (`tsk_...`) |
| `TESSLATE_BASE_URL` | Backend URL (default `http://localhost:8899`) |

## Related docs

- [docs/sdk/CLAUDE.md](CLAUDE.md): per-file index
- [docs/orchestrator/routers/external-agent.md](../orchestrator/routers/external-agent.md): backing REST endpoints
- [docs/packages/CLAUDE.md](../packages/CLAUDE.md): sibling TypeScript packages
