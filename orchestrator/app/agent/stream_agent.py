"""
Stream Agent

An agent that streams AI responses directly to the user in real-time.
This encapsulates the original 'stream' mode logic where the AI generates
code and text that is immediately streamed back to the frontend.
"""

from typing import AsyncIterator, Dict, Any
from uuid import UUID
import logging
import re
import asyncio
import os
import aiofiles

from .base import AbstractAgent
from openai import AsyncOpenAI
from ..utils.resource_naming import get_project_path

logger = logging.getLogger(__name__)


class StreamAgent(AbstractAgent):
    """
    An agent that streams the AI's response directly to the user.

    This agent:
    - Calls an LLM with a streaming API
    - Yields text chunks as they arrive
    - Extracts code blocks and saves them as files
    - Notifies the frontend when files are ready
    """

    async def run(
        self,
        user_request: str,
        context: Dict[str, Any]
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Run the stream agent to generate and stream a response.

        Args:
            user_request: The user's message/request
            context: Execution context with:
                - user: User object
                - project_id: Project ID
                - db: Database session
                - project_context_str: Formatted project context (optional)
                - model: Model name to use (optional)
                - api_base: API base URL (optional)
                - has_existing_files: Whether project has files (optional)

        Yields:
            Events with types: stream, file_ready, status, complete, error
        """
        from ..config import get_settings
        settings = get_settings()

        user = context['user']
        project_id = context.get('project_id')
        db = context.get('db')
        project_context_str = context.get('project_context_str', '')

        # Get the model to use
        model = context.get('model') or settings.litellm_default_models.split(",")[0]

        # Create OpenAI client using centralized routing (handles OpenRouter vs LiteLLM)
        from .models import get_llm_client
        try:
            client = await get_llm_client(
                user_id=user.id,
                model_name=model,
                db=db
            )
        except ValueError as e:
            yield {
                'type': 'error',
                'content': str(e)
            }
            return

        # Build the complete prompt starting with system message (with marker substitution)
        processed_system_prompt = self.get_processed_system_prompt(context)
        messages = [
            {"role": "system", "content": processed_system_prompt}
        ]

        # Include chat history if provided (for conversation continuity)
        chat_history = context.get('chat_history', [])
        if chat_history:
            logger.info(f"[StreamAgent] Including {len(chat_history)} previous messages for context")
            messages.extend(chat_history)

        # Add current user message
        messages.append({
            "role": "user",
            "content": f"{project_context_str}\n\nUser request: {user_request}"
        })

        full_response = ""
        processed_files = set()

        try:
            logger.info(f"[StreamAgent] Starting stream for user {user.id}, project {project_id}")
            logger.info(f"[StreamAgent] Using model: {model}")

            # Prepare request parameters
            # Strip openrouter/ prefix if present (OpenRouter API expects just the model ID)
            model_id = model.removeprefix("openrouter/") if model.startswith("openrouter/") else model

            stream_params = {
                "model": model_id,
                "messages": messages,
                "stream": True
            }

            # Add OpenRouter-specific headers if needed
            if model.startswith("openrouter/"):
                stream_params["extra_headers"] = {
                    "HTTP-Referer": "https://tesslate.com",
                    "X-Title": "Tesslate Studio"
                }

            stream = await client.chat.completions.create(**stream_params)

            # Stream chunks to the frontend
            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    full_response += content
                    yield {'type': 'stream', 'content': content}

            logger.info(f"[StreamAgent] Streaming complete, response length: {len(full_response)}")

            # Process all code blocks and save files
            if project_id:
                code_blocks = self._extract_code_blocks(full_response)
                logger.info(f"[StreamAgent] Extracted {len(code_blocks)} code blocks")

                package_json_modified = False

                for i, (file_path, code) in enumerate(code_blocks):
                    if file_path not in processed_files:
                        logger.info(f"[StreamAgent] Saving file {i+1}/{len(code_blocks)}: {file_path}")
                        processed_files.add(file_path)

                        # Save the file
                        success = await self._save_file(
                            file_path=file_path,
                            code=code,
                            project_id=project_id,
                            user_id=user.id,
                            db=db
                        )

                        if success:
                            # Notify frontend
                            yield {
                                'type': 'file_ready',
                                'file_path': file_path,
                                'content': code
                            }

                            # Track if package.json was modified
                            if file_path == "package.json":
                                package_json_modified = True

                        # Small delay to prevent overwhelming dev server
                        if i < len(code_blocks) - 1:
                            await asyncio.sleep(0.2)

                # Run npm install if package.json was modified (K8s only)
                from ..services.orchestration import is_kubernetes_mode
                if package_json_modified and is_kubernetes_mode():
                    logger.info("[StreamAgent] package.json modified, running npm install")
                    yield {'type': 'status', 'content': '📦 Installing dependencies...'}

                    try:
                        from ..services.orchestration import get_orchestrator
                        orchestrator = get_orchestrator()

                        await orchestrator.execute_command(
                            user_id=user.id,
                            project_id=project_id,
                            container_name=None,  # Use default container
                            command=["npm", "install"],
                            timeout=180
                        )

                        yield {'type': 'status', 'content': '✅ Dependencies installed successfully'}
                    except Exception as e:
                        logger.warning(f"[StreamAgent] npm install failed: {e}")
                        yield {'type': 'warning', 'content': f'⚠️ Failed to install dependencies: {str(e)}'}

            # Send completion event
            yield {
                'type': 'complete',
                'data': {'final_response': full_response}
            }

        except Exception as e:
            logger.error(f"[StreamAgent] Error during streaming: {e}", exc_info=True)
            yield {
                'type': 'error',
                'content': f'Error: {str(e)}'
            }

    def _extract_code_blocks(self, content: str):
        """Extract code blocks with file paths from the response."""
        patterns = [
            # Standard: ```language\n// File: path\ncode```
            r'```(?:\w+)?\s*\n(?://|#)\s*File:\s*([^\n]+\.[\w]+)\n(.*?)```',
            # Alternative: ```language\n# File: path\ncode```
            r'```(?:\w+)?\s*\n#\s*File:\s*([^\n]+\.[\w]+)\n(.*?)```',
            # Comment style: ```\n<!-- File: path -->\ncode```
            r'```[^\n]*\n<!--\s*File:\s*([^\n]+\.[\w]+)\s*-->\n(.*?)```',
            # Simple: ```javascript\npath\ncode``` (must have valid extension)
            r'```(?:\w+)?\s*\n([a-zA-Z0-9_/-]+\.[a-zA-Z0-9]+)\n(.*?)```'
        ]

        matches = []
        processed_paths = set()

        for pattern in patterns:
            found_matches = re.findall(pattern, content, re.DOTALL)
            for match in found_matches:
                file_path = match[0].strip()
                code = match[1].strip()

                # Clean up file path
                file_path = re.sub(r'^(?://|#|<!--)\s*(?:File:\s*)?', '', file_path)
                file_path = re.sub(r'\s*(?:-->)?\s*$', '', file_path)
                file_path = file_path.strip()

                # Validate file path
                if (file_path and
                    '.' in file_path and
                    not file_path.startswith('//') and
                    not file_path.startswith('#') and
                    not file_path.startswith('File:') and
                    file_path not in processed_paths and
                    len(file_path) < 200 and
                    re.match(r'^[a-zA-Z0-9_./\-]+\.[a-zA-Z0-9]+$', file_path)):

                    matches.append((file_path, code))
                    processed_paths.add(file_path)
                    logger.debug(f"[StreamAgent] Extracted file: {file_path}")

        return matches

    async def _save_file(
        self,
        file_path: str,
        code: str,
        project_id: UUID,
        user_id: UUID,
        db
    ) -> bool:
        """
        Save file to database and dev container.

        Returns:
            True if successful, False otherwise
        """
        from ..services.orchestration import is_kubernetes_mode
        from ..models import ProjectFile
        from sqlalchemy import select

        try:
            # 1. Save to database
            try:
                result = await db.execute(
                    select(ProjectFile).where(
                        ProjectFile.project_id == project_id,
                        ProjectFile.file_path == file_path
                    )
                )
                db_file = result.scalar_one_or_none()

                if db_file:
                    db_file.content = code
                else:
                    db_file = ProjectFile(
                        project_id=project_id,
                        file_path=file_path,
                        content=code
                    )
                    db.add(db_file)

                await db.commit()
                logger.info(f"[StreamAgent] Saved {file_path} to database")
            except Exception as e:
                await db.rollback()
                logger.error(f"[StreamAgent] Database error saving {file_path}: {e}")
                # Continue to try writing to container

            # 2. Write to dev container (unified for Docker/K8s)
            try:
                from ..services.orchestration import get_orchestrator
                orchestrator = get_orchestrator()

                success = await orchestrator.write_file(
                    user_id=user_id,
                    project_id=project_id,
                    container_name=None,  # Use default container
                    file_path=file_path,
                    content=code
                )

                if success:
                    logger.info(f"[StreamAgent] Wrote {file_path} to container")
                else:
                    logger.warning(f"[StreamAgent] Failed to write {file_path} to container")
            except Exception as e:
                logger.error(f"[StreamAgent] Error writing to container: {e}")

            # Legacy Docker fallback for direct filesystem access
            if not is_kubernetes_mode():
                try:
                    project_dir = get_project_path(user_id, project_id)
                    full_path = os.path.join(project_dir, file_path)

                    # Create parent directory
                    parent_dir = os.path.dirname(full_path)
                    if parent_dir:
                        os.makedirs(parent_dir, exist_ok=True)

                    async with aiofiles.open(full_path, 'w', encoding='utf-8') as f:
                        await f.write(code)

                    logger.info(f"[StreamAgent] Wrote {file_path} to {full_path}")
                except Exception as e:
                    logger.error(f"[StreamAgent] Error writing to filesystem: {e}")

            return True

        except Exception as e:
            logger.error(f"[StreamAgent] Error saving file {file_path}: {e}", exc_info=True)
            return False
