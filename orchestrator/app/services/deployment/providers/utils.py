"""Shared utilities for deployment providers."""

import asyncio
import io
import tarfile
import logging
import zipfile
from typing import Callable, Awaitable, Any

import httpx

from ..base import DeploymentFile

logger = logging.getLogger(__name__)


def create_source_tarball(files: list[DeploymentFile]) -> bytes:
    """Create an in-memory tar.gz from a list of DeploymentFiles."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for f in files:
            info = tarfile.TarInfo(name=f.path)
            info.size = len(f.content)
            tar.addfile(info, io.BytesIO(f.content))
    buf.seek(0)
    return buf.read()


def create_source_zip(files: list[DeploymentFile]) -> bytes:
    """Create an in-memory ZIP from a list of DeploymentFiles."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.writestr(f.path, f.content)
    buf.seek(0)
    return buf.read()


async def poll_until_terminal(
    check_fn: Callable[[], Awaitable[dict]],
    terminal_states: set[str],
    status_key: str = "status",
    interval: int = 5,
    timeout: int = 600,
) -> dict:
    """Poll a status endpoint until a terminal state is reached."""
    elapsed = 0
    result: dict = {}
    while elapsed < timeout:
        result = await check_fn()
        current_status = result.get(status_key, "")
        if current_status in terminal_states:
            return result
        await asyncio.sleep(interval)
        elapsed += interval
    raise TimeoutError(f"Polling timed out after {timeout}s. Last status: {result}")


async def graphql_request(
    client: httpx.AsyncClient,
    url: str,
    query: str,
    variables: dict | None = None,
    headers: dict | None = None,
) -> dict:
    """Execute a GraphQL request and return the data."""
    payload: dict[str, Any] = {"query": query}
    if variables:
        payload["variables"] = variables
    resp = await client.post(url, json=payload, headers=headers or {})
    resp.raise_for_status()
    body = resp.json()
    if "errors" in body and body["errors"]:
        raise ValueError(f"GraphQL errors: {body['errors']}")
    return body.get("data", {})
