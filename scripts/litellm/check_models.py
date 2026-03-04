"""
Check LiteLLM models availability and test each model with a small completion.

Usage:
    # Auto-fetch URL and key from beta k8s cluster
    python scripts/litellm/check_models.py --beta

    # Auto-fetch from production k8s cluster
    python scripts/litellm/check_models.py --production

    # Override URL and key directly
    python scripts/litellm/check_models.py --url https://litellm.your-domain.com --key sk-xxx

    # Use env vars (reads from orchestrator config / .env)
    python scripts/litellm/check_models.py

    # Skip the completion test (just list models)
    python scripts/litellm/check_models.py --beta --list-only

    # Test specific models only
    python scripts/litellm/check_models.py --beta --models claude-sonnet-4-20250514,gpt-4o
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time

import aiohttp

# Allow importing from orchestrator
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "orchestrator"))

# Environment configs: domain and litellm public URL pattern
ENV_CONFIGS = {
    "beta": {"domain": "your-domain.com"},
    "production": {"domain": "your-domain.com"},
}


def get_config_from_settings():
    """Try to load URL and key from orchestrator settings."""
    try:
        from app.config import get_settings

        settings = get_settings()
        base_url = settings.litellm_api_base or ""
        master_key = settings.litellm_master_key or ""
        # Strip /v1 for management endpoints
        if base_url.rstrip("/").endswith("/v1"):
            base_url = base_url.rstrip("/")[:-3]
        return base_url.rstrip("/"), master_key
    except Exception:
        return "", ""


def get_config_from_k8s(env: str) -> tuple[str, str]:
    """Fetch LiteLLM URL and master key from the k8s cluster for the given environment."""
    cfg = ENV_CONFIGS[env]
    base_url = f"https://litellm.{cfg['domain']}"

    # Pull LITELLM_MASTER_KEY from the tesslate-app-secrets k8s secret
    print(f"Fetching master key from k8s secret (namespace=tesslate)...")
    try:
        result = subprocess.run(
            [
                "kubectl", "get", "secret", "tesslate-app-secrets",
                "-n", "tesslate",
                "-o", "jsonpath={.data.LITELLM_MASTER_KEY}",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            env={**os.environ, "MSYS_NO_PATHCONV": "1"},
        )
        if result.returncode != 0:
            print(f"  kubectl error: {result.stderr.strip()}")
            sys.exit(1)

        import base64
        master_key = base64.b64decode(result.stdout.strip()).decode()
        if not master_key:
            print("  ERROR: LITELLM_MASTER_KEY is empty in tesslate-app-secrets")
            sys.exit(1)

        return base_url, master_key

    except FileNotFoundError:
        print("  ERROR: kubectl not found. Install kubectl or use --url/--key instead.")
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print("  ERROR: kubectl timed out. Is the cluster reachable?")
        sys.exit(1)


async def get_models(base_url: str, headers: dict) -> list[dict]:
    """GET /models — returns list of model objects."""
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{base_url}/models",
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                print(f"  ERROR fetching /models: {resp.status} {text[:200]}")
                return []
            data = await resp.json()
            return data.get("data", [])


async def get_model_info(base_url: str, headers: dict) -> dict[str, dict]:
    """GET /model/info — returns pricing and metadata per model."""
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(
                f"{base_url}/model/info",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json()
                info_map = {}
                for item in data.get("data", []):
                    model_name = item.get("model_name", "")
                    model_info = item.get("model_info", {})
                    litellm_params = item.get("litellm_params", {})
                    info_map[model_name] = {
                        "provider": litellm_params.get("custom_llm_provider", "")
                        or litellm_params.get("model", "").split("/")[0]
                        if "/" in litellm_params.get("model", "")
                        else "",
                        "litellm_model": litellm_params.get("model", ""),
                        "input_cost": model_info.get("input_cost_per_token"),
                        "output_cost": model_info.get("output_cost_per_token"),
                        "max_tokens": model_info.get("max_tokens"),
                        "max_input_tokens": model_info.get("max_input_tokens"),
                        "max_output_tokens": model_info.get("max_output_tokens"),
                        "mode": model_info.get("mode", ""),
                    }
                return info_map
        except Exception as e:
            print(f"  Warning: could not fetch /model/info: {e}")
            return {}


async def test_model(base_url: str, headers: dict, model_id: str) -> dict:
    """Send a tiny completion request to verify the model works."""
    url = f"{base_url}/v1/chat/completions"
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 5,
        "temperature": 0,
    }

    start = time.monotonic()
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                url,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                elapsed = time.monotonic() - start
                body = await resp.json()

                if resp.status == 200:
                    content = (
                        body.get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", "")
                    )
                    return {
                        "status": "ok",
                        "latency_s": round(elapsed, 2),
                        "response": content.strip()[:50],
                    }
                else:
                    error = body.get("error", {})
                    msg = error.get("message", "") if isinstance(error, dict) else str(error)
                    return {
                        "status": "error",
                        "latency_s": round(elapsed, 2),
                        "error": f"HTTP {resp.status}: {msg[:120]}",
                    }
        except asyncio.TimeoutError:
            elapsed = time.monotonic() - start
            return {
                "status": "timeout",
                "latency_s": round(elapsed, 2),
                "error": "Request timed out (30s)",
            }
        except Exception as e:
            elapsed = time.monotonic() - start
            return {
                "status": "error",
                "latency_s": round(elapsed, 2),
                "error": str(e)[:120],
            }


async def main():
    parser = argparse.ArgumentParser(description="Check LiteLLM model availability")
    env_group = parser.add_mutually_exclusive_group()
    env_group.add_argument(
        "--beta", action="store_true",
        help="Auto-fetch URL and key from beta k8s cluster",
    )
    env_group.add_argument(
        "--production", action="store_true",
        help="Auto-fetch URL and key from production k8s cluster",
    )
    parser.add_argument("--url", help="LiteLLM base URL (without /v1)")
    parser.add_argument("--key", help="LiteLLM master key")
    parser.add_argument(
        "--list-only", action="store_true", help="Only list models, skip completion test"
    )
    parser.add_argument(
        "--models", help="Comma-separated list of specific models to test"
    )
    parser.add_argument(
        "--json", action="store_true", help="Output results as JSON"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="Max concurrent model tests (default: 3)",
    )
    args = parser.parse_args()

    # Resolve URL and key — priority: --beta/--production > --url/--key > env vars > settings
    base_url = ""
    master_key = ""

    if args.beta:
        base_url, master_key = get_config_from_k8s("beta")
    elif args.production:
        base_url, master_key = get_config_from_k8s("production")

    if args.url:
        base_url = args.url
    if args.key:
        master_key = args.key

    if not base_url or not master_key:
        env_url = os.environ.get("LITELLM_API_BASE", "")
        env_key = os.environ.get("LITELLM_MASTER_KEY", "")
        cfg_url, cfg_key = get_config_from_settings()
        base_url = base_url or env_url or cfg_url
        master_key = master_key or env_key or cfg_key

    base_url = base_url.rstrip("/")

    # Strip /v1 if present (we add it when needed)
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]

    if not base_url:
        print("ERROR: No LiteLLM URL. Use --url, LITELLM_API_BASE env, or .env file.")
        sys.exit(1)
    if not master_key:
        print("ERROR: No master key. Use --key, LITELLM_MASTER_KEY env, or .env file.")
        sys.exit(1)

    headers = {
        "Authorization": f"Bearer {master_key}",
        "Content-Type": "application/json",
    }

    print(f"LiteLLM URL: {base_url}")
    print(f"Master Key:  {master_key[:8]}...{master_key[-4:]}")
    print()

    # Fetch models and info in parallel
    print("Fetching models...")
    models_list, info_map = await asyncio.gather(
        get_models(base_url, headers),
        get_model_info(base_url, headers),
    )

    if not models_list:
        print("No models returned from /models endpoint.")
        sys.exit(1)

    # Extract model IDs
    model_ids = sorted(set(m.get("id", "") for m in models_list if m.get("id")))

    # Filter if --models specified
    if args.models:
        filter_set = set(args.models.split(","))
        model_ids = [m for m in model_ids if m in filter_set]
        missing = filter_set - set(model_ids)
        if missing:
            print(f"Warning: models not found on server: {', '.join(missing)}")

    print(f"Found {len(model_ids)} models\n")

    # Print model list with info
    col_model = max(len(m) for m in model_ids) if model_ids else 20
    col_model = max(col_model, 10)

    header = f"{'Model':<{col_model}}  {'Provider':<20}  {'Mode':<8}  {'Max Input':>12}  {'Max Output':>12}  {'$/1M In':>10}  {'$/1M Out':>10}"
    print(header)
    print("-" * len(header))

    for mid in model_ids:
        info = info_map.get(mid, {})
        provider = info.get("provider", "-") or info.get("litellm_model", "-").split("/")[0] if info else "-"
        mode = info.get("mode", "-") or "-"
        max_in = info.get("max_input_tokens")
        max_out = info.get("max_output_tokens")
        in_cost = info.get("input_cost")
        out_cost = info.get("output_cost")

        max_in_str = f"{max_in:,}" if max_in else "-"
        max_out_str = f"{max_out:,}" if max_out else "-"
        in_cost_str = f"${in_cost * 1_000_000:.2f}" if in_cost else "-"
        out_cost_str = f"${out_cost * 1_000_000:.2f}" if out_cost else "-"

        print(
            f"{mid:<{col_model}}  {provider:<20}  {mode:<8}  {max_in_str:>12}  {max_out_str:>12}  {in_cost_str:>10}  {out_cost_str:>10}"
        )

    if args.list_only:
        return

    # Test each model
    print(f"\nTesting models (concurrency={args.concurrency})...\n")

    semaphore = asyncio.Semaphore(args.concurrency)
    results = {}

    async def test_with_semaphore(model_id: str):
        async with semaphore:
            print(f"  Testing {model_id}...", end="", flush=True)
            result = await test_model(base_url, headers, model_id)
            status_icon = {
                "ok": " PASS",
                "error": " FAIL",
                "timeout": " TIMEOUT",
            }.get(result["status"], " ???")
            latency = f"({result['latency_s']}s)"
            extra = result.get("response", result.get("error", ""))
            print(f"\r  {status_icon} {model_id:<{col_model}}  {latency:<10}  {extra}")
            results[model_id] = result

    tasks = [test_with_semaphore(mid) for mid in model_ids]
    await asyncio.gather(*tasks)

    # Summary
    passed = [m for m, r in results.items() if r["status"] == "ok"]
    failed = [m for m, r in results.items() if r["status"] != "ok"]

    print(f"\n{'='*60}")
    print(f"Results: {len(passed)}/{len(results)} models working")
    if failed:
        print(f"\nFailed models:")
        for m in failed:
            r = results[m]
            print(f"  {m}: {r.get('error', r['status'])}")
    print(f"{'='*60}")

    if args.json:
        output = {
            "url": base_url,
            "total_models": len(model_ids),
            "passed": len(passed),
            "failed": len(failed),
            "results": results,
        }
        print(f"\n{json.dumps(output, indent=2)}")

    # Exit with non-zero if any models failed
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
