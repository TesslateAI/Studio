from typing import Dict, Any, List, AsyncGenerator, Optional
import os
from openai import AsyncOpenAI
from anthropic import AsyncAnthropic

from app.config import settings
from app.schemas import ChatMessage


class AIProvider:
    def __init__(self):
        self.openai_client = None
        self.anthropic_client = None

        if settings.OPENAI_API_KEY:
            self.openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

        if settings.ANTHROPIC_API_KEY:
            self.anthropic_client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    async def generate_code(
        self,
        prompt: str,
        language: str = "python",
        framework: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        model: str = "gpt-4o",
        temperature: float = 0.7,
    ) -> Dict[str, Any]:
        system_prompt = f"""You are an expert {language} developer.
        Generate clean, efficient, and well-documented code.
        {'Use the ' + framework + ' framework.' if framework else ''}
        Return only the code without markdown formatting."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        if context:
            messages.insert(1, {"role": "user", "content": f"Context: {context}"})

        response = await self._call_model(messages, model, temperature)

        return {
            "code": response["content"],
            "explanation": "Code generated successfully",
            "tokens_used": response.get("tokens_used", 0),
        }

    async def refactor_code(
        self,
        code: str,
        instructions: str,
        language: str = "python",
        model: str = "gpt-4o",
    ) -> Dict[str, Any]:
        prompt = f"""Refactor the following {language} code according to these instructions:
        {instructions}

        Original code:
        {code}

        Return the refactored code and a brief explanation of changes."""

        messages = [
            {"role": "system", "content": f"You are an expert {language} developer."},
            {"role": "user", "content": prompt},
        ]

        response = await self._call_model(messages, model, temperature=0.3)

        return {
            "code": response["content"],
            "explanation": "Code refactored successfully",
            "tokens_used": response.get("tokens_used", 0),
        }

    async def explain_code(
        self,
        code: str,
        language: str = "python",
        model: str = "gpt-4o",
    ) -> Dict[str, Any]:
        prompt = f"""Explain the following {language} code in detail:
        {code}

        Provide a clear explanation covering:
        1. What the code does
        2. How it works
        3. Key concepts used
        4. Potential improvements"""

        messages = [
            {"role": "system", "content": "You are a programming teacher."},
            {"role": "user", "content": prompt},
        ]

        response = await self._call_model(messages, model, temperature=0.5)

        return {
            "explanation": response["content"],
            "tokens_used": response.get("tokens_used", 0),
        }

    async def chat(
        self,
        messages: List[ChatMessage],
        model: str = "gpt-4o",
        temperature: float = 0.7,
        stream: bool = False,
    ) -> Dict[str, Any]:
        formatted_messages = [
            {"role": msg.role, "content": msg.content} for msg in messages
        ]

        if stream:
            return self._stream_model(formatted_messages, model, temperature)

        response = await self._call_model(formatted_messages, model, temperature)

        return {
            "message": response["content"],
            "tokens_used": response.get("tokens_used", 0),
        }

    async def chat_stream(
        self,
        messages: List[ChatMessage],
        model: str = "gpt-4o",
        temperature: float = 0.7,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        formatted_messages = [
            {"role": msg.role, "content": msg.content} for msg in messages
        ]

        async for chunk in self._stream_model(formatted_messages, model, temperature):
            yield chunk

    async def analyze_context(
        self,
        messages: List[ChatMessage],
        model: str = "gpt-4o",
    ) -> Dict[str, Any]:
        analysis_prompt = """Analyze the conversation context and provide:
        1. A brief summary
        2. Key points discussed
        3. Suggested next actions"""

        formatted_messages = [
            {"role": msg.role, "content": msg.content} for msg in messages
        ]
        formatted_messages.append({"role": "user", "content": analysis_prompt})

        response = await self._call_model(formatted_messages, model, temperature=0.3)

        return {
            "summary": response["content"],
            "key_points": [],
            "suggested_actions": [],
            "tokens_used": response.get("tokens_used", 0),
        }

    async def _call_model(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float,
    ) -> Dict[str, Any]:
        if model.startswith("gpt") and self.openai_client:
            response = await self.openai_client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=settings.DEFAULT_MAX_TOKENS,
            )
            return {
                "content": response.choices[0].message.content,
                "tokens_used": response.usage.total_tokens if response.usage else 0,
            }
        elif model.startswith("claude") and self.anthropic_client:
            response = await self.anthropic_client.messages.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=settings.DEFAULT_MAX_TOKENS,
            )
            return {
                "content": response.content[0].text,
                "tokens_used": response.usage.input_tokens + response.usage.output_tokens,
            }
        else:
            raise ValueError(f"Unsupported model: {model}")

    async def _stream_model(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        if model.startswith("gpt") and self.openai_client:
            stream = await self.openai_client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                stream=True,
                max_tokens=settings.DEFAULT_MAX_TOKENS,
            )
            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield {"content": chunk.choices[0].delta.content}
        elif model.startswith("claude") and self.anthropic_client:
            async with self.anthropic_client.messages.stream(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=settings.DEFAULT_MAX_TOKENS,
            ) as stream:
                async for chunk in stream:
                    if hasattr(chunk, "delta") and hasattr(chunk.delta, "text"):
                        yield {"content": chunk.delta.text}
        else:
            raise ValueError(f"Unsupported model: {model}")