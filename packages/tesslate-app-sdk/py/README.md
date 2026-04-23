# tesslate-app-sdk (Python)

Async Python SDK for publishing, installing, and invoking Tesslate Apps against
a Studio deployment. Built on `httpx` + `pydantic` with no other runtime
dependencies. Every method is `async`, and `AppClient` is context-manager
friendly so you can share a single connection pool across calls. The
`ManifestBuilder` and `AppManifest_2025_01` pydantic model mirror the subset of
the canonical schema (`docs/specs/app-manifest-2025-01.md`) required to author
manifests without importing orchestrator internals.

Authentication is a Tesslate external API key (`tsk_...`) sent as
`Authorization: Bearer tsk_...`. CSRF is only enforced for cookie-authenticated
browser sessions; because this SDK always uses a Bearer token, no CSRF
cookie/header is required or sent.

```python
import asyncio
from tesslate_app_sdk import AppClient, AppSdkOptions, ManifestBuilder

async def main() -> None:
    opts = AppSdkOptions(base_url="https://opensail.tesslate.com", api_key="tsk_...")
    manifest = (
        ManifestBuilder()
        .app(slug="hello", name="Hello App", version="0.1.0")
        .surface(kind="iframe", entry="index.html")
        .billing(model="wallet-mix", default_budget_usd=0.25)
        .require_features(["apps.v1"])
        .build()
    )
    async with AppClient(opts) as client:
        pub = await client.publish_version(project_id="…", manifest=manifest)
        inst = await client.install_app(
            app_version_id=pub["app_version_id"],
            team_id="…",
            wallet_mix_consent={"accepted": True},
            mcp_consents=[],
        )
        sess = await client.begin_session(
            app_instance_id=inst["app_instance_id"], budget_usd=1.0, ttl_seconds=3600
        )
        try:
            # Use sess["api_key"] against LiteLLM here.
            ...
        finally:
            await client.end_session(sess["session_id"])

asyncio.run(main())
```

## Development

```bash
cd packages/tesslate-app-sdk/py
python3 -m venv .venv
.venv/bin/pip install -e .[dev]
.venv/bin/pytest
```
