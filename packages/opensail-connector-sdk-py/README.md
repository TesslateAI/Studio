# opensail-connector-sdk (Python)

Typed Python sugar for calling third-party providers (Slack, GitHub,
Linear, Gmail) through the OpenSail **Connector Proxy** from inside an
installed app pod.

The OpenSail installer injects two env vars into every app pod:

| Env var                       | Used for                                     |
| ----------------------------- | -------------------------------------------- |
| `OPENSAIL_RUNTIME_URL`        | Base URL of the proxy.                       |
| `OPENSAIL_APPINSTANCE_TOKEN`  | Sent as the `X-OpenSail-AppInstance` header. |

`ConnectorProxy()` reads both automatically — pass them explicitly only
when running outside an app pod (e.g. integration tests):

```python
import asyncio
from opensail_connector_sdk import ConnectorProxy

async def main() -> None:
    async with ConnectorProxy() as proxy:
        result = await proxy.slack.chat.postMessage(
            channel="C123ABC",
            text="hello from my OpenSail app",
        )
        print(result["ts"])

        commits = await proxy.github.repos.get_commits(
            owner="octocat", repo="hello-world", per_page=5
        )
        print([c["sha"] for c in commits])

        issue = await proxy.linear.issues.create(
            team_id="LIN-team-id",
            title="from-app bug report",
            description="Reported via OpenSail app.",
        )
        print(issue["data"]["issueCreate"]["issue"]["url"])

        await proxy.gmail.messages.send(
            to="someone@example.com",
            subject="hi",
            body_text="hello from gmail",
        )

asyncio.run(main())
```

Errors return as `ConnectorProxyHttpError` for non-2xx responses, with
`.status`, `.body` (parsed JSON when possible), and `.response` (the raw
`httpx.Response`).

## Endpoint coverage

The SDK ships hand-curated wrappers for the most-used endpoints; the full
allowlist lives in the orchestrator under
`orchestrator/app/services/apps/connector_proxy/provider_adapters/`.
For an allowlisted endpoint that does not yet have a sugar method, drop
to the raw `_request` call:

```python
await proxy._request(
    connector_id="slack",
    method="POST",
    endpoint_path="reactions.add",
    json={"channel": "C123", "name": "thumbsup", "timestamp": "1234.5678"},
)
```

| Provider | Sugar |
| -------- | ----- |
| Slack    | `chat.postMessage`, `chat.update`, `chat.delete`, `conversations.list`, `conversations.history`, `users.list`, `users.lookupByEmail` |
| GitHub   | `repos.get`, `repos.get_commits`, `repos.list_branches`, `issues.list`, `issues.create`, `issues.add_comment`, `user.get`, `user.list_repos` |
| Linear   | `graphql(...)`, `issues.list`, `issues.create` |
| Gmail    | `messages.list`, `messages.get`, `messages.send` (with shorthand or raw), `labels.list` |

## Development

```bash
cd packages/opensail-connector-sdk-py
uv sync --extra dev
uv run pytest tests/ -x -q
```
