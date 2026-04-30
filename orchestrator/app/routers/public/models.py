from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth_external import require_api_scope
from ...database import get_db
from ...models import UsageLog, User, UserAPIKey
from ...models_team import Team
from ...permissions import Permission
from ...services.credit_service import check_credits, deduct_credits
from ...services.litellm_service import LiteLLMService
from ...services.model_adapters import BUILTIN_PROVIDERS, get_llm_client, resolve_model_name
from ._shared import add_cache_headers

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["public-models"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[dict[str, Any]]
    stream: bool = True
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    stop: list[str] | str | None = None


# ---------------------------------------------------------------------------
# Streaming helper
# ---------------------------------------------------------------------------


async def _stream_response(
    client: Any,
    params: dict[str, Any],
    user: User,
    model_name: str,
    db: AsyncSession,
):
    """Async generator that proxies chunks in OpenAI SSE format and deducts
    credits once the stream completes."""

    tokens_in = 0
    tokens_out = 0

    try:
        stream = await client.chat.completions.create(**params)
        async for chunk in stream:
            chunk_data = chunk.model_dump(exclude_none=True)
            yield f"data: {json.dumps(chunk_data)}\n\n"

            # Capture usage from the final chunk (OpenAI includes it when
            # stream_options.include_usage is set).
            if hasattr(chunk, "usage") and chunk.usage:
                tokens_in = getattr(chunk.usage, "prompt_tokens", 0) or 0
                tokens_out = getattr(chunk.usage, "completion_tokens", 0) or 0

        yield "data: [DONE]\n\n"
    except Exception as e:
        error_data = {"error": {"message": str(e), "type": "proxy_error"}}
        yield f"data: {json.dumps(error_data)}\n\n"
        yield "data: [DONE]\n\n"
        return

    # Fire-and-forget credit deduction with its own session (the request
    # session is already closed by the time the generator finishes).
    try:
        from ...database import AsyncSessionLocal

        async with AsyncSessionLocal() as credit_db:
            await deduct_credits(
                db=credit_db,
                user_id=user.id,
                model_name=model_name,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                team_id=user.default_team_id,
            )
    except Exception:
        logger.warning("Failed to deduct credits after stream", exc_info=True)


# ---------------------------------------------------------------------------
# POST /chat/completions — OpenAI-compatible proxy
# ---------------------------------------------------------------------------


@router.post("/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    user: User = Depends(require_api_scope(Permission.MODELS_PROXY)),
    db: AsyncSession = Depends(get_db),
):
    # Load team for credit checks when applicable.
    team = None
    if user.default_team_id:
        from ...models_team import Team

        result = await db.execute(select(Team).where(Team.id == user.default_team_id))
        team = result.scalar_one_or_none()

    # Credit pre-check.
    can_proceed, error_msg = await check_credits(user, request.model, team)
    if not can_proceed:
        raise HTTPException(status_code=402, detail=error_msg)

    # Obtain the appropriate LLM client (built-in or BYOK).
    try:
        client = await get_llm_client(user.id, request.model, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    # Build provider params.
    resolved = resolve_model_name(request.model)
    params: dict[str, Any] = {
        "model": resolved,
        "messages": request.messages,
        "stream": request.stream,
    }
    if request.stream:
        params["stream_options"] = {"include_usage": True}
    if request.temperature is not None:
        params["temperature"] = request.temperature
    if request.max_tokens is not None:
        params["max_tokens"] = request.max_tokens
    if request.top_p is not None:
        params["top_p"] = request.top_p
    if request.stop is not None:
        params["stop"] = request.stop

    # --- Streaming path ---
    if request.stream:
        return StreamingResponse(
            _stream_response(client, params, user, request.model, db),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # --- Non-streaming path ---
    try:
        response = await client.chat.completions.create(**params)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Upstream provider error: {e}") from None

    tokens_in = getattr(response.usage, "prompt_tokens", 0) if response.usage else 0
    tokens_out = getattr(response.usage, "completion_tokens", 0) if response.usage else 0

    try:
        await deduct_credits(
            db=db,
            user_id=user.id,
            model_name=request.model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            team_id=user.default_team_id,
        )
    except Exception:
        logger.warning("Failed to deduct credits", exc_info=True)

    return response.model_dump(exclude_none=True)


# ---------------------------------------------------------------------------
# GET /models — List available models
# ---------------------------------------------------------------------------


@router.get("/models")
async def list_models(
    response: Response,
    user: User = Depends(require_api_scope(Permission.MODELS_PROXY)),
    db: AsyncSession = Depends(get_db),
):
    litellm = LiteLLMService()
    models: list[dict[str, Any]] = []

    # Fetch system-managed models from LiteLLM.
    try:
        raw_models = await litellm.get_available_models()
        model_info = await litellm.get_model_info()

        # Build pricing map from model_info.
        pricing_map: dict[str, dict[str, float]] = {}
        for entry in model_info:
            info = entry.get("model_info", {})
            model_name = entry.get("model_name", "")
            input_cost = info.get("input_cost_per_token")
            output_cost = info.get("output_cost_per_token")
            if input_cost is not None and output_cost is not None:
                pricing_map[model_name] = {
                    "input_per_1m": round(input_cost * 1_000_000, 2),
                    "output_per_1m": round(output_cost * 1_000_000, 2),
                }

        for m in raw_models:
            model_id = m.get("id", "")
            models.append(
                {
                    "id": f"builtin/{model_id}",
                    "object": "model",
                    "owned_by": "tesslate",
                    "pricing": pricing_map.get(model_id),
                    "is_byok": False,
                }
            )
    except Exception:
        logger.warning("Failed to fetch LiteLLM models", exc_info=True)

    # Batch-check which BYOK providers the user has keys for (single query).
    key_result = await db.execute(
        select(UserAPIKey.provider)
        .where(UserAPIKey.user_id == user.id, UserAPIKey.is_active.is_(True))
        .distinct()
    )
    user_provider_keys = {row[0] for row in key_result.all()}

    providers: list[dict[str, Any]] = []
    for slug, cfg in BUILTIN_PROVIDERS.items():
        providers.append(
            {
                "provider": slug,
                "name": cfg["name"],
                "description": cfg.get("description", ""),
                "has_key": slug in user_provider_keys,
                "website": cfg.get("website", ""),
            }
        )

    add_cache_headers(response, f"models:{len(models)}", max_age=300)
    return {
        "object": "list",
        "data": models,
        "providers": providers,
    }


# ---------------------------------------------------------------------------
# GET /usage — Credits & usage summary
# ---------------------------------------------------------------------------


@router.get("/usage")
async def get_usage(
    user: User = Depends(require_api_scope(Permission.USAGE_READ)),
    db: AsyncSession = Depends(get_db),
):
    team = None
    if user.default_team_id:
        team_result = await db.execute(select(Team).where(Team.id == user.default_team_id))
        team = team_result.scalar_one_or_none()

    credits = {
        "daily": (team.daily_credits if team else 0) or 0,
        "bundled": (team.bundled_credits if team else 0) or 0,
        "bonus": (team.signup_bonus_credits if team else 0) or 0,
        "purchased": (team.purchased_credits if team else 0) or 0,
        "total": team.total_credits if team else 0,
    }

    thirty_days_ago = datetime.now(UTC) - timedelta(days=30)

    # Total summary over the last 30 days.
    total_result = await db.execute(
        select(
            func.count(UsageLog.id),
            func.coalesce(func.sum(UsageLog.cost_total), 0),
            func.coalesce(func.sum(UsageLog.tokens_input), 0),
            func.coalesce(func.sum(UsageLog.tokens_output), 0),
        ).where(
            UsageLog.user_id == user.id,
            UsageLog.created_at >= thirty_days_ago,
        )
    )
    total_row = total_result.one()

    # Per-model breakdown.
    by_model_result = await db.execute(
        select(
            UsageLog.model,
            func.count(UsageLog.id),
            func.coalesce(func.sum(UsageLog.cost_total), 0),
        )
        .where(
            UsageLog.user_id == user.id,
            UsageLog.created_at >= thirty_days_ago,
        )
        .group_by(UsageLog.model)
        .order_by(func.sum(UsageLog.cost_total).desc())
        .limit(20)
    )
    by_model = [
        {"model": row[0], "requests": row[1], "cost_cents": row[2]} for row in by_model_result.all()
    ]

    return {
        "credits": credits,
        "usage_30d": {
            "total_requests": total_row[0],
            "total_cost_cents": total_row[1],
            "total_tokens_in": total_row[2],
            "total_tokens_out": total_row[3],
            "by_model": by_model,
        },
    }
