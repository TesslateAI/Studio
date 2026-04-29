# tesslate-marketplace-client

Async Python client for the Tesslate federated marketplace `/v1` protocol.

```python
import asyncio
from tesslate_marketplace_client import AsyncTesslateMarketplaceClient

async def main():
    async with AsyncTesslateMarketplaceClient(
        base_url="http://localhost:8800",
        token="tesslate-dev-token",
        pinned_hub_id="...",  # optional anti-hijack pin
    ) as client:
        manifest = await client.get_manifest()
        print(manifest.display_name, manifest.capabilities)

        items = await client.list_items(kind="agent")
        for item in items.items[:5]:
            print(item.slug, item.name)

asyncio.run(main())
```
