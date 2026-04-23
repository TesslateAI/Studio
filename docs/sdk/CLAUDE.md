# Top-level SDK (`sdk/`)

## Purpose

Documents the standalone TypeScript SDK at `/sdk/` that exposes the OpenSail REST API to Node and browser callers. Separate from `packages/tesslate-embed-sdk` (which speaks postMessage inside an iframe) and `packages/tesslate-app-sdk/ts` (which targets the Tesslate Apps REST surface with `tsk_*` keys).

This SDK is published as `@tesslate/sdk` (version `0.1.0`, MIT licensed, ESM + CJS, dts included).

## Key files

| File | Role |
| ---- | ---- |
| `sdk/package.json` | npm manifest. Exports dual ESM (`dist/index.js`) + CJS (`dist/index.cjs`) + types. `build` = tsup, `typecheck` = `tsc --noEmit`. Node `>=18`. |
| `sdk/tsconfig.json` | TypeScript project config (strict mode). |
| `sdk/tsup.config.ts` | tsup build: `entry: src/index.ts`, `format: [esm, cjs]`, `dts`, `clean`, `sourcemap`, `target: es2022`. |
| `sdk/smoke-test.ts` | Live end-to-end smoke test. Creates a project via the SDK, touches every resource, cleans up. Requires `TESSLATE_API_KEY`; `TESSLATE_BASE_URL` defaults to `http://localhost:8899`. Run with `npx tsx smoke-test.ts`. |
| `sdk/src/index.ts` | Public entry. Barrel exports for `TesslateClient`, error classes, resource classes, all type interfaces, and the `parseSSE` utility. |
| `sdk/src/client.ts` | `TesslateClient` class. Constructor builds an `HttpClient` + mounts `projects`, `agent`, `shell` resources. Options: `apiKey`, `baseUrl` (default `https://opensail.tesslate.com`), `timeout` (default 30_000 ms). |
| `sdk/src/http.ts` | `HttpClient` wrapper over fetch. `get` / `post` / `patch` / `delete` / `stream`. Bearer-auths every request. `AbortSignal.timeout(timeout)` on JSON calls; `timeout * 10` on streams. `throwForStatus()` maps HTTP status to typed errors (401 -> `TesslateAuthError`, 403 -> `TesslateForbiddenError`, 404 -> `TesslateNotFoundError`, else `TesslateApiError`). Extracts `detail` from JSON error bodies. |
| `sdk/src/errors.ts` | Error hierarchy. `TesslateError` (base) -> `TesslateApiError(status, body)` -> `TesslateAuthError` / `TesslateForbiddenError` / `TesslateNotFoundError`. |
| `sdk/src/sse.ts` | `parseSSE<T>(response)` async generator. Reads `Response.body`, splits on `\n\n`, extracts `data:` lines, yields parsed JSON. Stops on `data: [DONE]`. Non-JSON payloads are skipped silently. |
| `sdk/src/types.ts` | All shared interfaces: `Project`, `Container`, `FileTreeEntry`, `FileReadResult`, `FileWriteResult`, `FileDeleteResult`, `FileRenameResult`, `FileMkdirResult`, `FileBatchReadResult`, `AgentInvokeOptions`, `AgentInvokeResult`, `AgentTaskStatus`, `AgentEvent`, `ShellSession`, `ShellWriteResult`, `ShellOutputResult`, `GitStatus`, `GitCommitResult`, `GitPushResult`, `GitPullResult`, `GitBranchInfo`, `GitBranchesResult`, and the associated `*CreateOptions` / `*Result` variants. |

## Resources (`sdk/src/resources/`)

Resource classes are factory-bound to specific project identifiers. Each wraps `HttpClient` with typed endpoint methods.

| File | Class | Endpoints |
| ---- | ----- | --------- |
| `projects.ts` | `ProjectsResource` | `list()` -> `GET /api/projects/`. `create(opts)` -> `POST /api/projects/`. `get(slug)` -> `GET /api/projects/{slug}`. `delete(slug)` -> `DELETE /api/projects/{slug}`. Sub-resource factories: `files(slug)` -> `FilesResource`, `containers(slug)` -> `ContainersResource`, `git(projectId)` -> `GitResource`. |
| `containers.ts` | `ContainersResource` | Slug-bound. `list()` -> `GET /api/projects/{slug}/containers`. `startAll()` -> `POST /api/projects/{slug}/containers/start-all`. `stopAll()` -> `POST /api/projects/{slug}/containers/stop-all`. |
| `files.ts` | `FilesResource` | Slug-bound. `tree(containerDir?)`, `read(path, containerDir?)`, `readBatch(paths, containerDir?)`, `write(filePath, content)`, `delete(filePath, isDirectory?)`, `rename(oldPath, newPath)`, `mkdir(dirPath)`. Routes under `/api/projects/{slug}/files/*`. |
| `git.ts` | `GitResource` | Project-ID-bound. `status()`, `commit(message, files?)`, `push(opts)`, `pull(opts)`, `branches()`, `createBranch(name, checkout?)`, `switchBranch(name)`. Routes under `/api/projects/{projectId}/git/*`. |
| `agent.ts` | `AgentResource` | `invoke(opts)` -> `POST /api/external/agent/invoke`. `status(taskId)` -> `GET /api/external/agent/status/{taskId}`. `events(taskId)` async generator -> `GET /api/external/agent/events/{taskId}` as SSE via `parseSSE`. `invokeAndWait(opts, pollIntervalMs=2000)` polls status until terminal (`completed`, `failed`, `cancelled`). |
| `shell.ts` | `ShellResource` | `createSession(opts)`, `write(sessionId, data)`, `readOutput(sessionId)` (decodes base64 output), `close(sessionId)`. Convenience `run(projectId, command, opts?)` opens a session, writes `command + "\nexit\n"`, waits `waitMs` (default 2000), reads output, closes. Routes under `/api/shell/sessions/*`. |

## Authentication

Every request carries `Authorization: Bearer <apiKey>`. The caller provides an OpenSail external API key (`tsk_*`) via `TesslateClientOptions.apiKey`. Because auth is Bearer-only, the server's CSRF middleware does not engage; the SDK never needs to carry a CSRF cookie or header.

## Transport details

- Non-streaming requests use `fetch(url, { signal: AbortSignal.timeout(timeout) })`. Timeouts raise `TesslateError`.
- Streaming requests (SSE) call `HttpClient.stream()`, which does not apply the normal JSON timeout and returns the raw `Response` for `parseSSE` to consume.
- Error responses read JSON first, fall back to text, and surface either the `detail` field or `HTTP {status}` as the message.

## Related contexts

- `docs/packages/CLAUDE.md`: `packages/tesslate-app-sdk/ts` and `packages/tesslate-embed-sdk` (sibling TypeScript SDKs with different concerns)
- `docs/orchestrator/routers/external-agent.md`: backing REST endpoints for `AgentResource`
- `docs/orchestrator/routers/CLAUDE.md`: project, file, git, shell router surfaces

## When to load

- Adding or modifying a resource under `sdk/src/resources/`
- Changing error handling, retry, or transport semantics in `sdk/src/http.ts`
- Updating public type surface in `sdk/src/types.ts` after an API change
- Wiring new SDK methods that must be exercised by `sdk/smoke-test.ts`
