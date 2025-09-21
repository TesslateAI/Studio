from fastapi import APIRouter, HTTPException, Depends, WebSocket, WebSocketDisconnect
from typing import List, Optional
import json

from app.services.ai_provider import AIProvider
from app.schemas import ChatMessage, ChatRequest, ChatResponse

router = APIRouter()


@router.post("/", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    ai_provider: AIProvider = Depends(AIProvider),
):
    try:
        result = await ai_provider.chat(
            messages=request.messages,
            model=request.model,
            temperature=request.temperature,
            stream=False,
        )
        return ChatResponse(
            message=result["message"],
            tokens_used=result.get("tokens_used", 0),
            model=request.model,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.websocket("/stream")
async def chat_stream(websocket: WebSocket):
    await websocket.accept()
    ai_provider = AIProvider()

    try:
        while True:
            data = await websocket.receive_text()
            request = json.loads(data)

            messages = [ChatMessage(**msg) for msg in request.get("messages", [])]
            model = request.get("model", "gpt-4o")
            temperature = request.get("temperature", 0.7)

            async for chunk in ai_provider.chat_stream(
                messages=messages,
                model=model,
                temperature=temperature,
            ):
                await websocket.send_json(chunk)

    except WebSocketDisconnect:
        print("WebSocket disconnected")
    except Exception as e:
        await websocket.send_json({"error": str(e)})
        await websocket.close()


@router.post("/context-analysis")
async def analyze_context(
    request: ChatRequest,
    ai_provider: AIProvider = Depends(AIProvider),
):
    try:
        result = await ai_provider.analyze_context(
            messages=request.messages,
            model=request.model,
        )
        return {
            "summary": result["summary"],
            "key_points": result.get("key_points", []),
            "suggested_actions": result.get("suggested_actions", []),
            "tokens_used": result.get("tokens_used", 0),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))