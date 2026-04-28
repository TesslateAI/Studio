# @opensail/connector-sdk (TypeScript)

Typed sugar for calling third-party providers (Slack, GitHub, Linear,
Gmail) through the OpenSail **Connector Proxy** from inside an installed
app. Zero runtime dependencies — uses the global `fetch`.

The OpenSail installer injects two env vars into every app pod:

| Env var                       | Used for                                     |
| ----------------------------- | -------------------------------------------- |
| `OPENSAIL_RUNTIME_URL`        | Base URL of the proxy.                       |
| `OPENSAIL_APPINSTANCE_TOKEN`  | Sent as the `X-OpenSail-AppInstance` header. |

`new ConnectorProxy()` reads both automatically when `process.env` is
available (Node). In browsers, pass them explicitly.

```ts
import { ConnectorProxy } from "@opensail/connector-sdk";

const proxy = new ConnectorProxy();

const result = await proxy.slack.chat.postMessage({
  channel: "C123ABC",
  text: "hello from my OpenSail app",
});
console.log(result.ts);

const commits = await proxy.github.repos.getCommits({
  owner: "octocat",
  repo: "hello-world",
  per_page: 5,
});

const issue = await proxy.linear.issues.create({
  team_id: "LIN-team-id",
  title: "from-app bug report",
  description: "Reported via OpenSail app.",
});

await proxy.gmail.messages.send({
  to: "someone@example.com",
  subject: "hi",
  bodyText: "hello from gmail",
});
```

Errors throw `ConnectorProxyHttpError` for non-2xx, with `.status`,
`.body` (parsed JSON when possible), and `.response` (the raw `Response`).

## Endpoint coverage

The SDK ships hand-curated wrappers for the most-used endpoints; the full
allowlist lives in the orchestrator under
`orchestrator/app/services/apps/connector_proxy/provider_adapters/`.
For an allowlisted endpoint that does not yet have a sugar method, drop
to the raw `_request` call:

```ts
await proxy._request({
  connectorId: "slack",
  method: "POST",
  endpointPath: "reactions.add",
  body: { channel: "C123", name: "thumbsup", timestamp: "1234.5678" },
});
```

| Provider | Sugar |
| -------- | ----- |
| Slack    | `chat.postMessage`, `chat.update`, `chat.delete`, `conversations.list`, `conversations.history`, `users.list`, `users.lookupByEmail` |
| GitHub   | `repos.get`, `repos.getCommits`, `repos.listBranches`, `issues.list`, `issues.create`, `issues.addComment`, `user.get`, `user.listRepos` |
| Linear   | `graphql(...)`, `issues.list`, `issues.create` |
| Gmail    | `messages.list`, `messages.get`, `messages.send` (shorthand or raw), `labels.list` |

## Development

```bash
cd packages/opensail-connector-sdk-ts
npm install
npm test
npm run build
```
