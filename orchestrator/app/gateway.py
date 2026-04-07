"""
Gateway process entrypoint.

Runs as a standalone process alongside the API and worker pods.
Maintains persistent connections to messaging platforms and dispatches
inbound messages to the agent system.

Usage:
    python -m app.gateway              # shard 0 (default)
    python -m app.gateway --shard=1    # shard 1
"""

import argparse
import asyncio
import fcntl
import logging
import os
import signal
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="Tesslate Gateway Process")
    parser.add_argument(
        "--shard",
        type=int,
        default=int(os.getenv("GATEWAY_SHARD", "0")),
        help="Shard index (default: 0)",
    )
    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger = logging.getLogger("app.gateway")

    # Acquire file lock (defense-in-depth for single-instance guarantee)
    lock_dir = os.getenv("GATEWAY_LOCK_DIR", "/var/run/tesslate")
    os.makedirs(lock_dir, exist_ok=True)
    lock_path = os.path.join(lock_dir, f"gateway-shard-{args.shard}.lock")

    lock_fd = open(lock_path, "w")  # noqa: SIM115 — intentionally kept open for process lifetime
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        logger.error("Gateway shard %d is already running. Exiting.", args.shard)
        sys.exit(1)

    lock_fd.write(str(os.getpid()))
    lock_fd.flush()

    logger.info("Gateway shard %d starting (pid=%d)", args.shard, os.getpid())

    # Create runner and event loop
    from .services.gateway.runner import GatewayRunner

    runner = GatewayRunner(shard=args.shard)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Register signal handlers for graceful shutdown
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.ensure_future(runner.stop()))

    try:
        loop.run_until_complete(_start_gateway(runner))
    except KeyboardInterrupt:
        logger.info("Gateway shard %d interrupted", args.shard)
        loop.run_until_complete(runner.stop())
    finally:
        loop.close()
        lock_fd.close()
        logger.info("Gateway shard %d exited", args.shard)


async def _start_gateway(runner) -> None:
    """Initialize database, Redis, ARQ, and start the gateway runner."""
    from urllib.parse import urlparse

    from arq import create_pool
    from arq.connections import RedisSettings

    from .config import get_settings
    from .database import AsyncSessionLocal

    settings = get_settings()

    # Connect to Redis
    redis = None
    if settings.redis_url:
        import redis.asyncio as aioredis

        redis = aioredis.from_url(settings.redis_url, decode_responses=False)

    # Create ARQ pool for task dispatch
    arq_pool = None
    if settings.redis_url:
        parsed = urlparse(settings.redis_url)
        arq_pool = await create_pool(
            RedisSettings(
                host=parsed.hostname or "redis",
                port=parsed.port or 6379,
                database=int(parsed.path.lstrip("/") or "0"),
                password=parsed.password,
            )
        )

    # Use AsyncSessionLocal as factory
    await runner.start(
        db_factory=AsyncSessionLocal,
        redis=redis,
        arq_pool=arq_pool,
    )


if __name__ == "__main__":
    main()
