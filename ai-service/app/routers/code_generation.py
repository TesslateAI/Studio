from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List

from app.services.ai_provider import AIProvider
from app.schemas import CodeGenerationRequest, CodeGenerationResponse

router = APIRouter()


@router.post("/", response_model=CodeGenerationResponse)
async def generate_code(
    request: CodeGenerationRequest,
    ai_provider: AIProvider = Depends(AIProvider),
):
    try:
        result = await ai_provider.generate_code(
            prompt=request.prompt,
            language=request.language,
            framework=request.framework,
            context=request.context,
            model=request.model,
            temperature=request.temperature,
        )
        return CodeGenerationResponse(
            code=result["code"],
            explanation=result.get("explanation", ""),
            language=request.language,
            tokens_used=result.get("tokens_used", 0),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/refactor", response_model=CodeGenerationResponse)
async def refactor_code(
    request: CodeGenerationRequest,
    ai_provider: AIProvider = Depends(AIProvider),
):
    try:
        result = await ai_provider.refactor_code(
            code=request.context.get("code", ""),
            instructions=request.prompt,
            language=request.language,
            model=request.model,
        )
        return CodeGenerationResponse(
            code=result["code"],
            explanation=result.get("explanation", ""),
            language=request.language,
            tokens_used=result.get("tokens_used", 0),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/explain")
async def explain_code(
    request: CodeGenerationRequest,
    ai_provider: AIProvider = Depends(AIProvider),
):
    try:
        result = await ai_provider.explain_code(
            code=request.context.get("code", ""),
            language=request.language,
            model=request.model,
        )
        return {
            "explanation": result["explanation"],
            "tokens_used": result.get("tokens_used", 0),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))