"""POST /api/asr/cleanup — server-side transcript cleanup for browser-side ASR.

The browser captures and transcribes microphone audio entirely on-device using
Transformers.js. Only the resulting raw text is posted here for a small LLM
pass that fixes punctuation/casing and removes filler words before the user
sees it land in the chat input.

Audio is never uploaded. The privacy guarantee for voice input is enforced by
the client; this endpoint only ever receives plain text.

The cleanup model is supplied by the caller — there is no server-side default.
If the user hasn't explicitly chosen a cleanup model in their settings, the
client should never call this endpoint. We reject calls with no model rather
than silently falling back to whatever the orchestrator's default model is,
so an unconfigured user never burns credits on a feature they didn't opt into.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..config import get_settings
from ..models_auth import User
from ..users import current_active_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/asr", tags=["asr"])

CLEANUP_TIMEOUT_SECONDS = 3.0
MAX_TRANSCRIPT_CHARS = 8000
MAX_MODEL_NAME_CHARS = 200

CLEANUP_SYSTEM_PROMPT = (
    "You are a transcript cleanup assistant. The user dictated a message and "
    "speech recognition produced raw text. Fix punctuation and casing, remove "
    "filler words (um, uh, like, you know) and false starts, and join broken "
    "sentences. Preserve the meaning verbatim — do not paraphrase, summarize, "
    "translate, or add anything the speaker did not say. Return ONLY the "
    "cleaned text with no preamble, quotes, or commentary."
)


class CleanupRequest(BaseModel):
    transcript: str = Field(..., min_length=1, max_length=MAX_TRANSCRIPT_CHARS)
    # Required. The user must explicitly pick a cleanup model in Settings —
    # we never fall back to a server-side default.
    model: str = Field(..., min_length=1, max_length=MAX_MODEL_NAME_CHARS)


class CleanupResponse(BaseModel):
    cleaned: str


async def _cleanup_with_llm(transcript: str, model: str) -> str:
    """Run the cleanup pass via the LiteLLM proxy. Raises on failure."""
    settings = get_settings()
    if not settings.litellm_api_base:
        raise RuntimeError("litellm_api_base not configured")

    # Lazy import so this router doesn't hard-require the openai package on
    # deployment modes that never use it.
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=settings.litellm_master_key or "na",
        base_url=settings.litellm_api_base,
    )

    # Cap output length so a runaway model can't burn budget. ~half the input
    # plus a small floor is plenty for cleanup since we're not paraphrasing.
    max_tokens = max(64, min(2000, len(transcript) // 2 + 128))

    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": CLEANUP_SYSTEM_PROMPT},
            {"role": "user", "content": transcript},
        ],
        max_tokens=max_tokens,
        temperature=0.0,
    )
    choice = response.choices[0] if response.choices else None
    cleaned = (choice.message.content if choice and choice.message else "") or ""
    cleaned = cleaned.strip().strip('"').strip()
    return cleaned or transcript


@router.post("/cleanup", response_model=CleanupResponse)
async def cleanup(
    payload: CleanupRequest,
    user: Annotated[User, Depends(current_active_user)],
) -> CleanupResponse:
    """Clean up a dictated transcript using a user-chosen model.

    Returns the original transcript verbatim on any LLM failure or timeout —
    dictation must never block on this best-effort step.
    """
    transcript = payload.transcript.strip()
    if not transcript:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="transcript must not be empty",
        )
    model = payload.model.strip()
    if not model:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="model must not be empty",
        )

    try:
        cleaned = await asyncio.wait_for(
            _cleanup_with_llm(transcript, model), timeout=CLEANUP_TIMEOUT_SECONDS
        )
        return CleanupResponse(cleaned=cleaned)
    except asyncio.TimeoutError:
        logger.info(
            "asr.cleanup: timeout (model=%s) for user %s, returning raw", model, user.id
        )
    except Exception as exc:  # noqa: BLE001 — best-effort; fall through to raw
        logger.info(
            "asr.cleanup: error (model=%s) for user %s (%s), returning raw",
            model,
            user.id,
            exc,
        )

    return CleanupResponse(cleaned=transcript)
