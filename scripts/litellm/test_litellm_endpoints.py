"""
Test different LiteLLM endpoint combinations to find the working one.
"""
import asyncio
import aiohttp
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'orchestrator'))

from app.config import get_settings

settings = get_settings()


async def test_endpoints():
    """Test different endpoint combinations."""

    base_urls_to_test = [
        "https://apin.tesslate.com",  # Without /v1
        "https://apin.tesslate.com/v1",  # With /v1
    ]

    endpoints_to_test = [
        "/key/generate",
        "/user/new",
        "/key/info",
        "/health",
    ]

    headers = {
        "Authorization": f"Bearer {settings.litellm_master_key}",
        "Content-Type": "application/json"
    }

    print("Testing LiteLLM endpoints...")
    print(f"Master Key: {settings.litellm_master_key[:10]}...\n")

    async with aiohttp.ClientSession() as session:
        for base_url in base_urls_to_test:
            print(f"\n{'='*60}")
            print(f"Testing base URL: {base_url}")
            print(f"{'='*60}")

            for endpoint in endpoints_to_test:
                full_url = f"{base_url}{endpoint}"
                try:
                    # Try GET first
                    async with session.get(full_url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        status = resp.status
                        text = await resp.text()
                        print(f"GET  {endpoint:20} -> {status} {text[:100]}")
                except asyncio.TimeoutError:
                    print(f"GET  {endpoint:20} -> TIMEOUT")
                except Exception as e:
                    print(f"GET  {endpoint:20} -> ERROR: {str(e)[:50]}")


if __name__ == "__main__":
    asyncio.run(test_endpoints())
