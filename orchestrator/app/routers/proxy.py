"""
OpenAI-compatible model proxy for the desktop sidecar.

Exposes:
  GET  /v1/models             — lists available models
  POST /v1/chat/completions   — routes completions to cloud or direct LiteLLM

Routing logic:
  - When the desktop is paired with the cloud AND ``settings.litellm_api_base``
    is not set to a local endpoint, calls are proxied to the cloud's
    ``/api/v1/chat/completions`` endpoint using the stored ``tsk_`` bearer.
  - When ``settings.litellm_api_base`` is set (BYOK or local LiteLLM), calls
    are forwarded directly to that base URL with the local API key.
  - When neither is available, a 503 is returned so callers can surface a
    clear "not connected" message rather than a cryptic auth error.

These endpoints run on the FastAPI app regardless of deployment mode, but are
only meaningful when ``DEPLOYMENT_MODE=desktop``. Cloud deployments can safely
ignore them (the sidecar is not present there).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..config import get_settings
from ..services.cloud_client import CircuitOpenError, NotPairedError, get_cloud_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["proxy"])


@router.get("/v1/models", response_model=None)
async def list_models() -> JSONResponse:
    """Return the list of models available on this desktop installation.

    Attempts cloud first (returns whatever the cloud proxy has available for
    the paired user). Falls back to an empty ``data`` list when unpaired or
    the cloud is unreachable — this is not an error; the caller (e.g. a model
    selector dropdown) should treat an empty list as "offline / local only".
    """
    settings = get_settings()

    # Local LiteLLM / BYOK path — proxy directly to the local instance.
    if settings.litellm_api_base:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{settings.litellm_api_base.rstrip('/')}/models")
                resp.raise_for_status()
                return JSONResponse(content=resp.json())
        except Exception as exc:
            logger.debug("/v1/models local litellm failed: %s", exc)
            # Fall through to cloud path.

    # Cloud proxy path.
    try:
        client = await get_cloud_client()
        resp = await client.get("/api/v1/models")
        resp.raise_for_status()
        return JSONResponse(content=resp.json())
    except (NotPairedError, CircuitOpenError) as exc:
        logger.debug("/v1/models cloud unavailable: %s", exc)
    except Exception as exc:
        logger.warning("/v1/models cloud error: %s", exc)

    return JSONResponse(content={"object": "list", "data": []})


@router.post("/v1/chat/completions", response_model=None)
async def chat_completions(request: Request) -> StreamingResponse | JSONResponse:
    """Proxy a chat-completions request to the cloud or a local LiteLLM.

    Transparently forwards both streaming (``"stream": true``) and non-streaming
    requests. The bearer presented to *this* endpoint is the sidecar's own
    loopback bearer (validated by the Tauri host before the request reaches
    here) — the upstream bearer injected by ``CloudClient`` is the ``tsk_``
    cloud token, which is separate.
    """
    settings = get_settings()
    body: dict[str, Any] = await request.json()
    is_stream = bool(body.get("stream", False))

    # ------------------------------------------------------------------
    # Local LiteLLM / BYOK path
    # ------------------------------------------------------------------
    if settings.litellm_api_base:
        base = settings.litellm_api_base.rstrip("/")
        upstream_url = f"{base}/chat/completions"

        if is_stream:
            return StreamingResponse(
                _stream_local(upstream_url, body),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(upstream_url, json=body)
                return JSONResponse(content=resp.json(), status_code=resp.status_code)
        except Exception as exc:
            logger.warning("Local litellm POST failed: %s", exc)
            return JSONResponse(
                status_code=502,
                content={
                    "error": {"message": f"Local LiteLLM unreachable: {exc}", "type": "proxy_error"}
                },
            )

    # ------------------------------------------------------------------
    # Cloud proxy path
    # ------------------------------------------------------------------
    try:
        cloud = await get_cloud_client()
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"error": {"message": "Desktop not paired with cloud", "type": "not_paired"}},
        )

    if is_stream:
        return StreamingResponse(
            _stream_cloud(cloud, body),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        resp = await cloud.post("/api/v1/chat/completions", json=body)
        return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except NotPairedError:
        return JSONResponse(
            status_code=401,
            content={"error": {"message": "Desktop not paired with cloud", "type": "not_paired"}},
        )
    except CircuitOpenError:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "message": "Cloud circuit open; try again shortly",
                    "type": "circuit_open",
                }
            },
        )
    except Exception as exc:
        logger.warning("Cloud chat_completions POST failed: %s", exc)
        return JSONResponse(
            status_code=502,
            content={"error": {"message": str(exc), "type": "proxy_error"}},
        )


# ---------------------------------------------------------------------------
# Streaming helpers
# ---------------------------------------------------------------------------


async def _stream_local(upstream_url: str, body: dict[str, Any]):
    """Forward a streaming request to a local LiteLLM endpoint line by line."""
    try:
        async with (
            httpx.AsyncClient(timeout=httpx.Timeout(5.0, read=120.0)) as client,
            client.stream("POST", upstream_url, json=body) as resp,
        ):
            async for line in resp.aiter_lines():
                if line:
                    yield line + "\n"
    except Exception as exc:
        logger.warning("_stream_local error: %s", exc)
        yield f"data: {json.dumps({'error': str(exc)})}\n\n"
    finally:
        yield "data: [DONE]\n\n"


async def _stream_cloud(cloud: Any, body: dict[str, Any]):
    """Forward a streaming request to the cloud proxy line by line."""
    try:
        async with cloud.stream_post("/api/v1/chat/completions", json=body) as resp:
            async for line in resp.aiter_lines():
                if line:
                    yield line + "\n"
    except (NotPairedError, CircuitOpenError) as exc:
        yield f"data: {json.dumps({'error': str(exc)})}\n\n"
    except Exception as exc:
        logger.warning("_stream_cloud error: %s", exc)
        yield f"data: {json.dumps({'error': str(exc)})}\n\n"
    finally:
        yield "data: [DONE]\n\n"
