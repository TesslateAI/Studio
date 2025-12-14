from typing import List, Optional, Dict
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..database import get_db
from ..models import User, Chat, Message, Project, ProjectFile, MarketplaceAgent, UserPurchasedAgent, Container
from ..schemas import (
    Chat as ChatSchema, Message as MessageSchema, MessageCreate,
    AgentChatRequest, AgentChatResponse, AgentStepResponse
)
from ..config import get_settings
from ..utils.resource_naming import get_project_path
from openai import AsyncOpenAI
import json
import os
import aiofiles
import re
import asyncio
import logging
import jwt

# Agent imports - new factory-based system
from ..agent import create_agent_from_db_model
from ..agent.models import create_model_adapter
from ..agent.iterative_agent import _convert_uuids_to_strings
from ..users import current_active_user, current_superuser

settings = get_settings()
router = APIRouter()
logger = logging.getLogger(__name__)


async def _build_git_context(project: Project, user_id: UUID, db: AsyncSession) -> Optional[str]:
    """
    Build Git context for agent if project has a Git repository connected.

    Returns formatted string with Git information and command examples, or None if no Git repo.
    """
    try:
        from ..models import GitRepository
        from ..services.git_manager import GitManager

        # Check if project has Git repository
        result = await db.execute(
            select(GitRepository).where(GitRepository.project_id == project.id)
        )
        git_repo = result.scalar_one_or_none()

        if not git_repo:
            return None

        # Get current Git status
        git_manager = GitManager(user_id=user_id, project_id=str(project.id))
        try:
            git_status = await git_manager.get_status()
        except Exception as status_error:
            logger.warning(f"[GIT-CONTEXT] Could not get Git status: {status_error}")
            git_status = None

        # Build concise Git context
        context_lines = [
            "\n=== Git Repository ===",
            f"Repository: {git_repo.repo_url}",
        ]

        if git_status:
            context_lines.append(f"Branch: {git_status['branch']}")

            if git_status.get('status'):
                context_lines.append(f"Status: {git_status['status']}")

            if git_status.get('changes_count', 0) > 0:
                context_lines.append(f"Uncommitted Changes: {git_status['changes_count']}")

            sync_info = []
            if git_status.get('ahead', 0) > 0:
                sync_info.append(f"{git_status['ahead']} ahead")
            if git_status.get('behind', 0) > 0:
                sync_info.append(f"{git_status['behind']} behind")
            if sync_info:
                context_lines.append(f"Remote: {', '.join(sync_info)}")

            if git_status.get('last_commit'):
                last_commit = git_status['last_commit']
                context_lines.append(f"Last Commit: {last_commit['message']} ({last_commit['sha'][:8]})")

        if git_repo.auto_push:
            context_lines.append("Auto-push: ENABLED")
        else:
            context_lines.append("Auto-push: DISABLED")

        return "\n".join(context_lines)

    except Exception as e:
        logger.error(f"[GIT-CONTEXT] Failed to build Git context: {e}", exc_info=True)
        return None


async def _get_chat_history(
    chat_id: UUID,
    db: AsyncSession,
    limit: int = 10
) -> List[Dict[str, str]]:
    """
    Fetch recent chat history for context.

    Args:
        chat_id: Chat ID to fetch messages from
        db: Database session
        limit: Maximum number of message pairs to fetch (default 10, max 20)

    Returns:
        List of message dictionaries with 'role' and 'content' keys
    """
    try:
        # Limit to prevent token overflow
        limit = min(limit, 20)

        # Fetch recent messages, excluding the current one (it will be added separately)
        messages_result = await db.execute(
            select(Message)
            .where(Message.chat_id == chat_id)
            .order_by(Message.created_at.desc())
            .limit(limit * 2)  # *2 to account for user+assistant pairs
        )
        messages = list(messages_result.scalars().all())

        # Reverse to get chronological order (oldest first)
        messages.reverse()

        # Format messages for LLM
        formatted_messages = []
        for msg in messages:
            # Skip system messages or empty content
            if not msg.content or msg.role not in ['user', 'assistant']:
                continue

            # For user messages, just add the content
            if msg.role == 'user':
                formatted_messages.append({
                    "role": msg.role,
                    "content": msg.content
                })
            # For assistant messages, check if there are agent iterations in metadata
            elif msg.role == 'assistant':
                metadata = msg.message_metadata or {}
                steps = metadata.get('steps', [])

                if steps:
                    # Agent message with iterations - reconstruct full conversation
                    # Include each iteration's response as a separate assistant message
                    # to preserve the full context of the agent's thought process
                    for step in steps:
                        # Build a detailed response for each iteration
                        thought = step.get('thought', '')
                        response_text = step.get('response_text', '')
                        tool_calls = step.get('tool_calls', [])

                        iteration_content = ""

                        # Add thought if present
                        if thought:
                            iteration_content += f"THOUGHT: {thought}\n\n"

                        # Add tool calls if present
                        if tool_calls:
                            iteration_content += "Tool Calls:\n"
                            for tc in tool_calls:
                                tool_name = tc.get('name', 'unknown')
                                tool_result = tc.get('result', {})
                                success = tool_result.get('success', False)

                                iteration_content += f"- {tool_name}: {'✓ Success' if success else '✗ Failed'}\n"

                                # Add brief result summary
                                if success and tool_result.get('result'):
                                    result_data = tool_result['result']
                                    if isinstance(result_data, dict):
                                        if 'message' in result_data:
                                            iteration_content += f"  {result_data['message']}\n"
                                    else:
                                        iteration_content += f"  {str(result_data)[:200]}\n"

                            iteration_content += "\n"

                        # Add response text
                        if response_text:
                            iteration_content += response_text

                        if iteration_content.strip():
                            formatted_messages.append({
                                "role": "assistant",
                                "content": iteration_content
                            })

                            # Add tool results as user feedback (simulating the iterative flow)
                            if tool_calls:
                                tool_results_feedback = "Tool Results:\n"
                                for idx, tc in enumerate(tool_calls):
                                    tool_name = tc.get('name', 'unknown')
                                    tool_result = tc.get('result', {})
                                    success = tool_result.get('success', False)

                                    tool_results_feedback += f"\n{idx + 1}. {tool_name}: {'✓ Success' if success else '✗ Failed'}\n"

                                    if tool_result.get('result'):
                                        result_data = tool_result['result']
                                        if isinstance(result_data, dict):
                                            # Add key result fields
                                            for key in ['message', 'content', 'stdout', 'output']:
                                                if key in result_data:
                                                    content = str(result_data[key])[:500]  # Limit content length
                                                    tool_results_feedback += f"   {key}: {content}\n"
                                                    break
                                        else:
                                            tool_results_feedback += f"   {str(result_data)[:500]}\n"

                                formatted_messages.append({
                                    "role": "user",
                                    "content": tool_results_feedback
                                })
                else:
                    # Regular assistant message without iterations
                    formatted_messages.append({
                        "role": msg.role,
                        "content": msg.content
                    })

        logger.info(f"[CHAT-HISTORY] Fetched {len(formatted_messages)} messages for chat {chat_id}")
        return formatted_messages

    except Exception as e:
        logger.error(f"[CHAT-HISTORY] Failed to fetch chat history: {e}", exc_info=True)
        return []


async def _build_tesslate_context(
    project: Project,
    user_id: UUID,
    db: AsyncSession,
    container_name: Optional[str] = None,
    container_directory: Optional[str] = None
) -> Optional[str]:
    """
    Build TESSLATE.md context for agent.

    Reads TESSLATE.md from the user's project container. For container-scoped agents,
    reads from the container's directory. If it doesn't exist, copies the generic
    template from orchestrator/template/TESSLATE.md.

    Args:
        project: Project model
        user_id: User UUID
        db: Database session
        container_name: Optional container name for multi-container projects
        container_directory: Optional container directory for file path resolution

    Returns the TESSLATE.md content as a formatted string, or None if unable to read.
    """
    try:
        # Read TESSLATE.md from the user's project (deployment-aware)
        tesslate_content = None

        from ..services.orchestration import get_orchestrator, is_kubernetes_mode

        # Try unified orchestrator first
        try:
            orchestrator = get_orchestrator()
            tesslate_content = await orchestrator.read_file(
                user_id=user_id,
                project_id=project.id,
                container_name=container_name,  # Use specific container if provided
                file_path="TESSLATE.md",
                project_slug=project.slug,
                subdir=container_directory  # Read from container's subdirectory
            )

            # If TESSLATE.md doesn't exist, copy the template
            if tesslate_content is None:
                logger.info(f"[TESSLATE-CONTEXT] TESSLATE.md not found in project {project.id}, copying template")

                # Read the generic template
                template_path = os.path.join(os.path.dirname(__file__), "..", "..", "template", "TESSLATE.md")
                try:
                    async with aiofiles.open(template_path, 'r', encoding='utf-8') as f:
                        template_content = await f.read()

                    # Write template to container's subdirectory
                    success = await orchestrator.write_file(
                        user_id=user_id,
                        project_id=project.id,
                        container_name=container_name,
                        file_path="TESSLATE.md",
                        content=template_content,
                        project_slug=project.slug,
                        subdir=container_directory  # Write to container's subdirectory
                    )

                    if success:
                        tesslate_content = template_content
                        logger.info(f"[TESSLATE-CONTEXT] Successfully copied template to project {project.id}")
                    else:
                        logger.warning(f"[TESSLATE-CONTEXT] Failed to write template to container")

                except Exception as e:
                    logger.error(f"[TESSLATE-CONTEXT] Failed to read template file: {e}")

        except Exception as e:
            logger.debug(f"[TESSLATE-CONTEXT] Could not read via orchestrator: {e}")

        # Fallback: Docker mode - read from local filesystem
        if tesslate_content is None and not is_kubernetes_mode():
            # Docker mode: Read from local filesystem
            project_dir = get_project_path(user_id, project.id)
            tesslate_path = os.path.join(project_dir, "TESSLATE.md")

            if os.path.exists(tesslate_path):
                try:
                    async with aiofiles.open(tesslate_path, 'r', encoding='utf-8') as f:
                        tesslate_content = await f.read()
                except Exception as e:
                    logger.error(f"[TESSLATE-CONTEXT] Failed to read TESSLATE.md: {e}")
            else:
                # Copy template
                logger.info(f"[TESSLATE-CONTEXT] TESSLATE.md not found in project {project.id}, copying template")
                template_path = os.path.join(os.path.dirname(__file__), "..", "..", "template", "TESSLATE.md")

                try:
                    # Ensure project directory exists
                    os.makedirs(project_dir, exist_ok=True)

                    async with aiofiles.open(template_path, 'r', encoding='utf-8') as f:
                        template_content = await f.read()

                    async with aiofiles.open(tesslate_path, 'w', encoding='utf-8') as f:
                        await f.write(template_content)

                    tesslate_content = template_content
                    logger.info(f"[TESSLATE-CONTEXT] Successfully copied template to project {project.id}")

                except Exception as e:
                    logger.error(f"[TESSLATE-CONTEXT] Failed to copy template: {e}")

        if tesslate_content:
            # Return formatted context
            return f"\n=== Project Context (TESSLATE.md) ===\n\n{tesslate_content}\n"
        else:
            return None

    except Exception as e:
        logger.error(f"[TESSLATE-CONTEXT] Failed to build TESSLATE context: {e}", exc_info=True)
        return None


@router.get("/", response_model=List[ChatSchema])
async def get_chats(
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Chat).where(Chat.user_id == current_user.id)
    )
    chats = result.scalars().all()
    return chats

@router.post("/", response_model=ChatSchema)
async def create_chat(
    chat_data: dict,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    project_id = chat_data.get('project_id')
    
    # Check if chat already exists for this user and project
    if project_id:
        result = await db.execute(
            select(Chat).where(
                Chat.user_id == current_user.id,
                Chat.project_id == project_id
            )
        )
        existing_chat = result.scalar_one_or_none()
        if existing_chat:
            return existing_chat
    
    db_chat = Chat(
        user_id=current_user.id,
        project_id=project_id
    )
    db.add(db_chat)
    await db.commit()
    await db.refresh(db_chat)
    return db_chat

@router.get("/{project_id}/messages", response_model=List[MessageSchema])
async def get_project_messages(
    project_id: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all messages for a specific project's chat."""
    # Get the chat for this user and project
    result = await db.execute(
        select(Chat).where(
            Chat.user_id == current_user.id,
            Chat.project_id == project_id
        )
    )
    chat = result.scalar_one_or_none()

    if not chat:
        # No chat exists yet for this project, return empty list
        return []

    # Get all messages for this chat
    messages_result = await db.execute(
        select(Message)
        .where(Message.chat_id == chat.id)
        .order_by(Message.created_at.asc())
    )
    messages = messages_result.scalars().all()
    return messages


@router.delete("/{project_id}/messages")
async def delete_project_messages(
    project_id: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete all messages for a specific project's chat (clear chat history)."""
    try:
        # Get the chat for this user and project
        result = await db.execute(
            select(Chat).where(
                Chat.user_id == current_user.id,
                Chat.project_id == project_id
            )
        )
        chat = result.scalar_one_or_none()

        if not chat:
            # No chat exists, nothing to delete
            return {"success": True, "message": "No chat history found", "deleted_count": 0}

        # Clear approval tracking for this session
        from ..agent.tools.approval_manager import get_approval_manager
        approval_mgr = get_approval_manager()
        approval_mgr.clear_session_approvals(chat.id)
        logger.info(f"[CHAT] Cleared approvals for chat session {chat.id}")

        # Delete all messages for this chat
        from sqlalchemy import delete as sql_delete
        delete_result = await db.execute(
            sql_delete(Message).where(Message.chat_id == chat.id)
        )
        deleted_count = delete_result.rowcount

        await db.commit()

        logger.info(f"[CHAT] Deleted {deleted_count} messages for project {project_id}, user {current_user.id}")

        return {
            "success": True,
            "message": f"Deleted {deleted_count} messages",
            "deleted_count": deleted_count
        }

    except Exception as e:
        await db.rollback()
        logger.error(f"[CHAT] Failed to delete messages for project {project_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete chat history: {str(e)}"
        )


@router.post("/agent", response_model=AgentChatResponse)
async def agent_chat(
    request: AgentChatRequest,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    HTTP Agent Chat - uses IterativeAgent via factory system.

    This endpoint demonstrates the factory-based agent system with HTTP.
    The agent can read/write files, execute commands, and manage the project
    autonomously using any language model.

    **Key Difference from WebSocket:**
    - Returns complete result after all iterations finish
    - No real-time streaming
    - Better for non-interactive use cases

    Args:
        request: Agent chat request with project_id, message, agent_id
        current_user: Authenticated user
        db: Database session

    Returns:
        Complete agent execution result with all steps and final response
    """
    logger.info(f"[HTTP-AGENT] Starting agent chat - user: {current_user.id}, project: {request.project_id}")
    try:
        # Verify project ownership
        try:
            result = await db.execute(
                select(Project).where(
                    Project.id == request.project_id,
                    Project.owner_id == current_user.id
                )
            )
            project = result.scalar_one_or_none()

            if not project:
                raise HTTPException(
                    status_code=404,
                    detail="Project not found or access denied"
                )
        except HTTPException:
            raise
        except Exception as e:
            await db.rollback()
            logger.error(f"Database error during project verification: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Database error: {str(e)}"
            )

        logger.info(
            f"[HTTP-AGENT] Agent chat started - user: {current_user.id}, "
            f"project: {request.project_id}, message: {request.message[:100]}..."
        )

        # ============================================================================
        # NEW: Factory-Based Agent Creation
        # ============================================================================

        # 1. Fetch agent from database (prefer IterativeAgent for HTTP)
        agent_model = None
        if request.agent_id:
            agent_result = await db.execute(
                select(MarketplaceAgent).where(
                    MarketplaceAgent.id == request.agent_id,
                    MarketplaceAgent.is_active == True
                )
            )
            agent_model = agent_result.scalar_one_or_none()

            if not agent_model:
                raise HTTPException(
                    status_code=404,
                    detail=f"Agent with ID {request.agent_id} not found or inactive"
                )
        else:
            # Default: Use first IterativeAgent available
            agent_result = await db.execute(
                select(MarketplaceAgent).where(
                    MarketplaceAgent.is_active == True,
                    MarketplaceAgent.agent_type == 'IterativeAgent'
                ).limit(1)
            )
            agent_model = agent_result.scalar_one_or_none()

            if not agent_model:
                raise HTTPException(
                    status_code=404,
                    detail="No IterativeAgent found. Please configure an agent."
                )

        logger.info(
            f"[HTTP-AGENT] Using agent: {agent_model.name} "
            f"(type: {agent_model.agent_type}, slug: {agent_model.slug})"
        )

        # 2. Check user has LiteLLM key
        if not current_user.litellm_api_key:
            raise HTTPException(
                status_code=500,
                detail="User does not have a LiteLLM API key. Please contact support."
            )

        # 2.5. Get user's selected model override (if any)
        try:
            user_purchase_result = await db.execute(
                select(UserPurchasedAgent).where(
                    UserPurchasedAgent.user_id == current_user.id,
                    UserPurchasedAgent.agent_id == agent_model.id
                )
            )
            user_purchase = user_purchase_result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"[HTTP-AGENT] Error fetching user purchase: {e}", exc_info=True)
            await db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Error fetching user purchase: {str(e)}"
            )

        # Use user's selected model if available, otherwise use agent's default model
        model_name = (user_purchase.selected_model if user_purchase and user_purchase.selected_model
                     else agent_model.model or settings.litellm_default_models.split(",")[0])

        logger.info(f"[HTTP-AGENT] Using model: {model_name}")

        # 3. Create model adapter for IterativeAgent
        logger.info(f"[HTTP-AGENT] Creating model adapter for user_id: {current_user.id}, model: {model_name}")
        try:
            model_adapter = await create_model_adapter(
                model_name=model_name,
                user_id=current_user.id,
                db=db
            )
            logger.info(f"[HTTP-AGENT] Model adapter created successfully")
        except Exception as e:
            logger.error(f"[HTTP-AGENT] Error creating model adapter: {e}", exc_info=True)
            await db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Error creating model adapter: {str(e)}"
            )

        # 4. Create agent via factory
        logger.info(f"[HTTP-AGENT] Creating agent via factory")
        try:
            agent_instance = await create_agent_from_db_model(
                agent_model=agent_model,
                model_adapter=model_adapter
            )
            logger.info(f"[HTTP-AGENT] Agent instance created successfully")
        except Exception as e:
            logger.error(f"[HTTP-AGENT] Error creating agent instance: {e}", exc_info=True)
            await db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Error creating agent instance: {str(e)}"
            )

        # Set max_iterations for IterativeAgent
        if hasattr(agent_instance, 'max_iterations'):
            agent_instance.max_iterations = request.max_iterations
        if hasattr(agent_instance, 'minimal_prompts'):
            agent_instance.minimal_prompts = request.minimal_prompts

        logger.info(f"[HTTP-AGENT] Agent created successfully with max_iterations={request.max_iterations}")

        # Get or create chat for message history
        try:
            chat_result = await db.execute(
                select(Chat).where(
                    Chat.user_id == current_user.id,
                    Chat.project_id == request.project_id
                )
            )
            chat = chat_result.scalar_one_or_none()

            if not chat:
                chat = Chat(user_id=current_user.id, project_id=request.project_id)
                db.add(chat)
                await db.commit()
                await db.refresh(chat)

        except Exception as e:
            await db.rollback()
            logger.error(f"Database error during chat setup: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Database error while setting up chat: {str(e)}"
            )

        # Fetch chat history for context
        chat_history = await _get_chat_history(chat.id, db, limit=10)

        # Fetch container info for multi-container project support
        # If container_id is provided, agent is scoped to that container (files at root)
        # If not, agent defaults to first container but at project level
        container_id = None
        container_name = None
        container_directory = None

        if request.container_id:
            logger.info(f"[AGENT-CHAT] Looking up container_id: {request.container_id} for project: {request.project_id}")
            try:
                from uuid import UUID
                # Convert string to UUID if needed
                container_uuid = UUID(str(request.container_id)) if not isinstance(request.container_id, UUID) else request.container_id
                container_result = await db.execute(
                    select(Container).where(
                        Container.id == container_uuid,
                        Container.project_id == request.project_id
                    )
                )
                container = container_result.scalar_one_or_none()
                if container:
                    container_id = container.id
                    # Use directory as service name for shell ops (it's already sanitized)
                    # This gets prefixed with project_slug in _get_container_name()
                    container_name = container.directory if container.directory and container.directory != '.' else None
                    # Set container directory for scoped file operations
                    if container.directory and container.directory != '.':
                        container_directory = container.directory
                        logger.info(f"[AGENT-CHAT] Container-scoped agent: {container_name} ({container_id}), directory: {container_directory}")
                    else:
                        logger.info(f"[AGENT-CHAT] Using specified container: {container_name} ({container_id})")
                else:
                    logger.warning(f"[AGENT-CHAT] Container not found: {request.container_id}")
            except Exception as e:
                logger.warning(f"[AGENT-CHAT] Could not get container: {e}", exc_info=True)
        else:
            # Default to first container in project
            container_result = await db.execute(
                select(Container).where(Container.project_id == request.project_id).limit(1)
            )
            container = container_result.scalar_one_or_none()
            if container:
                container_id = container.id
                # Use directory as service name for shell ops (it's already sanitized)
                container_name = container.directory if container.directory and container.directory != '.' else None
                logger.info(f"[AGENT-CHAT] Using default container: {container_name} ({container_id})")

        # Prepare context for tool execution
        context = {
            "user_id": current_user.id,
            "project_id": request.project_id,
            "project_slug": project.slug,  # For shared volume file access
            "container_directory": container_directory,  # Container subdirectory for file ops
            "chat_id": chat.id,
            "db": db,
            "chat_history": chat_history,
            "edit_mode": request.edit_mode,
            # Multi-container support
            "container_id": container_id,
            "container_name": container_name,
        }

        # Get project context
        project_context = {
            "project_name": project.name,
            "project_description": project.description
        }

        # Build TESSLATE.md context (project-specific documentation for AI agents)
        tesslate_context = await _build_tesslate_context(
            project, current_user.id, db,
            container_name=container_name,
            container_directory=container_directory
        )
        if tesslate_context:
            project_context["tesslate_context"] = tesslate_context
            logger.info(f"[AGENT-CHAT] Added TESSLATE.md context for project {project.id}")

        # Check if project has Git repository connected and inject Git context
        git_context = await _build_git_context(project, current_user.id, db)
        if git_context:
            project_context["git_context"] = git_context

        # ============================================================================
        # NEW: Run Agent and Collect Events (HTTP Adapter for AsyncIterator)
        # ============================================================================

        logger.info(f"[HTTP-AGENT] Running agent (collecting all events for HTTP response)")

        # Collect all events from the async generator
        steps_response = []
        final_response = ""
        success = False
        iterations = 0
        tool_calls_made = 0
        completion_reason = "unknown"
        error = None

        try:
            async for event in agent_instance.run(request.message, context):
                event_type = event.get('type')

                if event_type == 'agent_step':
                    # Collect step data
                    step_data = event.get('data', {})

                    # Convert tool calls to ToolCallDetail format
                    from ..schemas import ToolCallDetail
                    tool_call_details = []
                    for tc_data in step_data.get('tool_calls', []):
                        # Get corresponding result from tool_results
                        tc_index = len(tool_call_details)
                        result = step_data.get('tool_results', [])[tc_index] if tc_index < len(step_data.get('tool_results', [])) else None

                        tool_call_details.append(ToolCallDetail(
                            name=tc_data.get('name'),
                            parameters=tc_data.get('parameters'),
                            result=result
                        ))

                    steps_response.append(AgentStepResponse(
                        iteration=step_data.get('iteration', 0),
                        thought=step_data.get('thought'),
                        tool_calls=tool_call_details,
                        response_text=step_data.get('response_text', ''),
                        is_complete=step_data.get('is_complete', False),
                        timestamp=step_data.get('timestamp', '')
                    ))

                elif event_type == 'complete':
                    # Extract final result data
                    data = event.get('data', {})
                    success = data.get('success', True)
                    iterations = data.get('iterations', 0)
                    final_response = data.get('final_response', '')
                    tool_calls_made = data.get('tool_calls_made', 0)
                    completion_reason = data.get('completion_reason', 'complete')

                elif event_type == 'error':
                    error = event.get('content', 'Unknown error')
                    success = False

        except Exception as e:
            logger.error(f"[HTTP-AGENT] Error during agent execution: {e}", exc_info=True)
            error = str(e)
            success = False

        logger.info(
            f"[HTTP-AGENT] Agent execution complete - "
            f"success: {success}, iterations: {iterations}, tool_calls: {tool_calls_made}"
        )


        # Save to chat history (chat was already created/fetched earlier)
        try:
            # Save user message
            user_message = Message(
                chat_id=chat.id,
                role="user",
                content=request.message
            )
            db.add(user_message)

            # Increment usage_count for the agent
            if agent_model:
                agent_model.usage_count = (agent_model.usage_count or 0) + 1
                db.add(agent_model)
                logger.info(f"[USAGE-TRACKING] Incremented usage_count for agent {agent_model.name} to {agent_model.usage_count}")

            await db.commit()
        except Exception as e:
            await db.rollback()
            logger.error(f"Database error during chat history setup: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Database error while saving chat: {str(e)}"
            )

        # Save agent response with metadata for UI restoration
        agent_metadata = {
            "agent_mode": True,
            "agent_type": agent_model.agent_type,
            "iterations": iterations,
            "tool_calls_made": tool_calls_made,
            "completion_reason": completion_reason,
            "steps": [
                {
                    "iteration": step.iteration,
                    "thought": step.thought,
                    "tool_calls": [
                        {
                            "name": tc.name,
                            "parameters": _convert_uuids_to_strings(tc.parameters),
                            "result": _convert_uuids_to_strings(tc.result)
                        }
                        for tc in step.tool_calls
                    ],
                    "response_text": step.response_text,
                    "is_complete": step.is_complete,
                    "timestamp": step.timestamp.isoformat() if hasattr(step.timestamp, 'isoformat') else str(step.timestamp)
                }
                for step in steps_response
            ]
        }

        assistant_message = Message(
            chat_id=chat.id,
            role="assistant",
            content=final_response,
            message_metadata=agent_metadata
        )
        db.add(assistant_message)
        await db.commit()

        # Cleanup: Close any bash session that was opened during this agent run
        if context.get("_bash_session_id"):
            try:
                from ..services.shell_session_manager import get_shell_session_manager
                shell_manager = get_shell_session_manager()
                await shell_manager.close_session(context["_bash_session_id"])
                logger.info(f"[HTTP-AGENT] Cleaned up bash session {context['_bash_session_id']}")
            except Exception as cleanup_err:
                logger.warning(f"[HTTP-AGENT] Failed to cleanup bash session: {cleanup_err}")

        logger.info(
            f"[HTTP-AGENT] Agent chat completed - success: {success}, "
            f"iterations: {iterations}, tool_calls: {tool_calls_made}"
        )

        return AgentChatResponse(
            success=success,
            iterations=iterations,
            final_response=final_response,
            tool_calls_made=tool_calls_made,
            completion_reason=completion_reason,
            steps=steps_response,
            error=error
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_traceback = traceback.format_exc()
        logger.error(f"Agent chat error: {e}")
        logger.error(f"Full traceback:\n{error_traceback}")
        raise HTTPException(
            status_code=500,
            detail=f"Agent execution failed: {str(e)}"
        )


@router.post("/agent/approval")
async def handle_agent_approval(
    approval_data: dict,
    current_user: User = Depends(current_active_user)
):
    """
    Handle approval response for agent tool execution.

    This endpoint allows the frontend to respond to approval requests
    when using SSE streaming (which is one-way communication).

    Args:
        approval_data: {approval_id: str, response: str}
        current_user: Authenticated user

    Returns:
        Success confirmation
    """
    from ..agent.tools.approval_manager import get_approval_manager

    approval_id = approval_data.get("approval_id")
    response = approval_data.get("response")  # 'allow_once', 'allow_all', 'stop'

    if not approval_id or not response:
        raise HTTPException(
            status_code=400,
            detail="approval_id and response are required"
        )

    logger.info(f"[APPROVAL] Received approval response: {response} for {approval_id}")

    approval_mgr = get_approval_manager()
    approval_mgr.respond_to_approval(approval_id, response)

    return {"success": True, "message": "Approval response processed"}


@router.post("/agent/stream")
async def agent_chat_stream(
    request: AgentChatRequest,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    SSE Streaming Agent Chat - uses IterativeAgent with real-time event streaming.

    This endpoint streams agent execution events in real-time using Server-Sent Events (SSE).
    Prevents Cloudflare timeouts by continuously sending data during long-running tasks.

    **Event Types:**
    - text_chunk: LLM text generation as it happens
    - agent_step: Tool calls and results when iteration completes
    - approval_required: Tool needs user approval (SSE is one-way, use /agent/approval endpoint to respond)
    - complete: Final response when task finishes
    - error: Error information if execution fails

    Args:
        request: Agent chat request with project_id, message, agent_id
        current_user: Authenticated user
        db: Database session

    Returns:
        StreamingResponse with SSE format events
    """
    from fastapi.responses import StreamingResponse
    import json

    logger.info(f"[SSE-AGENT] Starting streaming agent chat - user: {current_user.id}, project: {request.project_id}, container_id: {request.container_id}")

    async def event_generator():
        try:
            # Verify project ownership
            result = await db.execute(
                select(Project).where(
                    Project.id == request.project_id,
                    Project.owner_id == current_user.id
                )
            )
            project = result.scalar_one_or_none()

            if not project:
                error_event = {
                    'type': 'error',
                    'data': {'message': 'Project not found or access denied'}
                }
                yield f"data: {json.dumps(error_event)}\n\n"
                return

            # Track activity for idle cleanup (database-based)
            from ..services.activity_tracker import track_project_activity
            await track_project_activity(db, project.id, "agent")

            # Fetch container info for multi-container project support
            container_id = None
            container_name = None
            container_directory = None
            project_slug = project.slug

            if request.container_id:
                container_result = await db.execute(
                    select(Container).where(
                        Container.id == request.container_id,
                        Container.project_id == request.project_id
                    )
                )
                container = container_result.scalar_one_or_none()
                if container:
                    container_id = container.id
                    # Use directory as service name for shell ops (it's already sanitized)
                    container_name = container.directory if container.directory and container.directory != '.' else None
                    # Capture container directory for scoped file operations
                    if container.directory and container.directory != '.':
                        container_directory = container.directory
                    logger.info(f"[SSE-AGENT] Using container: {container_name} (id: {container_id}), directory: {container_directory}")

            # Get or create chat for message history persistence
            chat_result = await db.execute(
                select(Chat).where(
                    Chat.user_id == current_user.id,
                    Chat.project_id == request.project_id
                )
            )
            chat = chat_result.scalar_one_or_none()

            if not chat:
                chat = Chat(user_id=current_user.id, project_id=request.project_id)
                db.add(chat)
                await db.commit()
                await db.refresh(chat)

            # Fetch chat history BEFORE saving current message to avoid duplication
            chat_history = await _get_chat_history(chat.id, db, limit=10)

            # Save user message after fetching history
            user_message = Message(
                chat_id=chat.id,
                role="user",
                content=request.message
            )
            db.add(user_message)
            await db.commit()

            # Create agent using same pattern as HTTP endpoint
            from ..agent.factory import create_agent_from_db_model
            from ..agent.models import create_model_adapter
            from ..config import get_settings

            settings = get_settings()

            # 1. Fetch agent from database
            agent_model = None
            if request.agent_id:
                agent_result = await db.execute(
                    select(MarketplaceAgent).where(
                        MarketplaceAgent.id == request.agent_id,
                        MarketplaceAgent.is_active == True
                    )
                )
                agent_model = agent_result.scalar_one_or_none()

                if not agent_model:
                    error_event = {
                        'type': 'error',
                        'data': {'message': f'Agent with ID {request.agent_id} not found or inactive'}
                    }
                    yield f"data: {json.dumps(error_event)}\n\n"
                    return
            else:
                # Default: Use first IterativeAgent available
                agent_result = await db.execute(
                    select(MarketplaceAgent).where(
                        MarketplaceAgent.is_active == True,
                        MarketplaceAgent.agent_type == 'IterativeAgent'
                    ).limit(1)
                )
                agent_model = agent_result.scalar_one_or_none()

                if not agent_model:
                    error_event = {
                        'type': 'error',
                        'data': {'message': 'No IterativeAgent found. Please configure an agent.'}
                    }
                    yield f"data: {json.dumps(error_event)}\n\n"
                    return

            # 2. Get user's selected model
            user_purchase_result = await db.execute(
                select(UserPurchasedAgent).where(
                    UserPurchasedAgent.user_id == current_user.id,
                    UserPurchasedAgent.agent_id == agent_model.id
                )
            )
            user_purchase = user_purchase_result.scalar_one_or_none()

            model_name = (user_purchase.selected_model if user_purchase and user_purchase.selected_model
                         else agent_model.model or settings.litellm_default_models.split(",")[0])

            # 3. Create model adapter
            model_adapter = await create_model_adapter(
                model_name=model_name,
                user_id=current_user.id,
                db=db
            )

            # 4. Create agent via factory
            agent_instance = await create_agent_from_db_model(
                agent_model=agent_model,
                model_adapter=model_adapter
            )

            # Set max_iterations
            if hasattr(agent_instance, 'max_iterations'):
                agent_instance.max_iterations = request.max_iterations or 20

            # Build project context with TESSLATE.md and Git info
            project_context = {
                "project_name": project.name,
                "project_description": project.description
            }

            # Build TESSLATE.md context
            tesslate_context = await _build_tesslate_context(
                project, current_user.id, db,
                container_name=container_name,
                container_directory=container_directory
            )
            if tesslate_context:
                project_context["tesslate_context"] = tesslate_context
                logger.info(f"[SSE-AGENT] Added TESSLATE.md context for project {project.id}")

            # Build Git context
            git_context = await _build_git_context(project, current_user.id, db)
            if git_context:
                project_context["git_context"] = git_context
                logger.info(f"[SSE-AGENT] Added Git context for project {project.id}")

            # Prepare execution context
            # Note: container_directory was already captured during initial container lookup above
            context = {
                "user_id": current_user.id,
                "project_id": request.project_id,
                "project_slug": project.slug,  # For shared volume file access
                "container_directory": container_directory,  # Container subdirectory for file ops
                "chat_id": chat.id,
                "db": db,
                "chat_history": chat_history,
                "project_context": project_context,
                "edit_mode": request.edit_mode,
                "container_id": container_id,
                "container_name": container_name,
                "project_slug": project_slug
            }

            # Accumulate results for database persistence
            collected_steps = []
            final_response = ""
            iterations = 0
            tool_calls_made = 0
            completion_reason = "task_complete"

            # Stream events from agent and collect metadata
            async for event in agent_instance.run(request.message, context):
                # Collect step data for persistence
                if event['type'] == 'agent_step':
                    collected_steps.append(event['data'])
                elif event['type'] == 'complete':
                    final_response = event['data'].get('final_response', '')
                    iterations = event['data'].get('iterations', iterations)
                    tool_calls_made = event['data'].get('tool_calls_made', tool_calls_made)
                    completion_reason = event['data'].get('completion_reason', completion_reason)

                # Send event in SSE format
                yield f"data: {json.dumps(event)}\n\n"

            # Increment usage_count for the agent
            if agent_model:
                agent_model.usage_count = (agent_model.usage_count or 0) + 1
                db.add(agent_model)
                logger.info(f"[USAGE-TRACKING] Incremented usage_count for agent {agent_model.name} to {agent_model.usage_count}")

            # Save agent response with metadata (same format as HTTP endpoint)
            agent_metadata = {
                "agent_mode": True,
                "agent_type": agent_model.agent_type,
                "iterations": iterations,
                "tool_calls_made": tool_calls_made,
                "completion_reason": completion_reason,
                "steps": [
                    {
                        "iteration": step.get('iteration'),
                        "thought": step.get('thought'),
                        "tool_calls": [
                            {
                                "name": tc.get('name'),
                                "parameters": _convert_uuids_to_strings(tc.get('parameters', {})),
                                "result": _convert_uuids_to_strings(step.get('tool_results', [])[idx] if idx < len(step.get('tool_results', [])) else {})
                            }
                            for idx, tc in enumerate(step.get('tool_calls', []))
                        ],
                        "response_text": step.get('response_text', ''),
                        "is_complete": step.get('is_complete', False),
                        "timestamp": step.get('timestamp', '')
                    }
                    for step in collected_steps
                ]
            }

            assistant_message = Message(
                chat_id=chat.id,
                role="assistant",
                content=final_response,
                message_metadata=agent_metadata
            )
            db.add(assistant_message)
            await db.commit()

            # Cleanup: Close any bash session that was opened during this agent run
            if context.get("_bash_session_id"):
                try:
                    from ..services.shell_session_manager import get_shell_session_manager
                    shell_manager = get_shell_session_manager()
                    await shell_manager.close_session(context["_bash_session_id"])
                    logger.info(f"[SSE-AGENT] Cleaned up bash session {context['_bash_session_id']}")
                except Exception as cleanup_err:
                    logger.warning(f"[SSE-AGENT] Failed to cleanup bash session: {cleanup_err}")

            logger.info(f"[SSE-AGENT] Streaming complete - user: {current_user.id}, project: {request.project_id}, saved to database")

        except Exception as e:
            import traceback
            error_traceback = traceback.format_exc()
            logger.error(f"SSE Agent error: {e}")
            logger.error(f"Full traceback:\n{error_traceback}")

            error_event = {
                'type': 'error',
                'data': {'message': str(e)}
            }
            yield f"data: {json.dumps(error_event)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
            "Connection": "keep-alive"
        }
    )


class ConnectionManager:
    def __init__(self):
        # Use (user_id, project_id) tuple as key to support multiple projects per user
        self.active_connections: dict[tuple[UUID, UUID], WebSocket] = {}

    def disconnect(self, user_id: UUID, project_id: UUID):
        connection_key = (user_id, project_id)
        if connection_key in self.active_connections:
            del self.active_connections[connection_key]
            logger.info(f"WebSocket disconnected: user {user_id}, project {project_id}")

    async def send_personal_message(self, message: str, user_id: UUID, project_id: UUID):
        connection_key = (user_id, project_id)
        if connection_key in self.active_connections:
            await self.active_connections[connection_key].send_text(message)

manager = ConnectionManager()

@router.websocket("/ws/{token}")
async def websocket_endpoint(websocket: WebSocket, token: str, db: AsyncSession = Depends(get_db)):
    user = None
    project_id = None
    try:
        # Verify token and get user
        # Accept both old tokens (no audience) and new fastapi-users tokens (audience: ["fastapi-users:auth"])
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.algorithm],
            options={"verify_aud": False}  # Don't verify audience for backward compatibility
        )
        user_id_or_username = payload.get("sub")

        # Try to find user by ID (UUID) first (fastapi-users), then by username (old system)
        try:
            from uuid import UUID
            user_uuid = UUID(user_id_or_username)
            result = await db.execute(select(User).where(User.id == user_uuid))
            user = result.scalar_one_or_none()
        except (ValueError, TypeError):
            # Not a valid UUID, try username lookup
            result = await db.execute(select(User).where(User.username == user_id_or_username))
            user = result.scalar_one_or_none()

        if not user:
            await websocket.close(code=1008)
            return

        # Accept connection first (required before receiving messages)
        await websocket.accept()

        # Wait for first message to get project_id
        try:
            first_message = await websocket.receive_json()
            project_id = first_message.get("project_id")

            if not project_id:
                logger.error("WebSocket: No project_id in first message")
                await websocket.close(code=1008, reason="project_id required")
                return

            # Now register the connection with user_id and project_id
            # Note: We already called accept() above, so we need to update connect() logic
            connection_key = (user.id, project_id)

            # Close any existing connection for this user+project combination
            if connection_key in manager.active_connections:
                try:
                    old_ws = manager.active_connections[connection_key]
                    await old_ws.close(code=1000, reason="New connection established")
                except Exception as e:
                    logger.warning(f"Failed to close old WebSocket for user {user.id}, project {project_id}: {e}")

            manager.active_connections[connection_key] = websocket
            logger.info(f"WebSocket connected: user {user.id}, project {project_id}")

            # Process the first message
            await handle_chat_message(first_message, user, db, websocket)

        except Exception as e:
            logger.error(f"Error processing first WebSocket message: {e}")
            await websocket.close(code=1011, reason="Failed to initialize connection")
            return

        # Continue processing messages
        while True:
            try:
                data = await websocket.receive_json()
                await handle_chat_message(data, user, db, websocket)
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"Error handling message: {e}")
                try:
                    await websocket.send_json({
                        "type": "error",
                        "content": f"Error: {str(e)}"
                    })
                except:
                    break

    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        if user and project_id:
            manager.disconnect(user.id, project_id)

async def handle_chat_message(data: dict, user: User, db: AsyncSession, websocket: WebSocket):
    """
    Handle chat message using the unified agent factory system.

    This function now uses the agent factory to instantiate any type of agent
    (StreamAgent, IterativeAgent, or future agent types) based on the database
    configuration.
    """
    # Handle heartbeat ping
    if data.get("type") == "ping":
        await websocket.send_json({"type": "pong"})
        return

    # Handle approval response (Ask Before Edit mode)
    if data.get("type") == "approval_response":
        from ..agent.tools.approval_manager import get_approval_manager
        approval_mgr = get_approval_manager()

        approval_id = data.get("approval_id")
        response = data.get("response")  # 'allow_once', 'allow_all', 'stop'

        logger.info(f"[WebSocket] Received approval response: {response} for {approval_id}")

        if approval_id and response:
            approval_mgr.respond_to_approval(approval_id, response)
        else:
            logger.warning(f"[WebSocket] Invalid approval response: missing approval_id or response")

        return

    message_content = data.get("message")
    project_id = data.get("project_id")
    agent_id = data.get("agent_id")  # Get agent_id from request
    container_id = data.get("container_id")  # Get container_id for container-scoped agents
    edit_mode = data.get("edit_mode", "ask")  # Get edit_mode from request, default to ask

    logger.info(f"[WebSocket] Received message - project_id: {project_id}, container_id: {container_id}, agent_id: {agent_id}")

    try:
        # Get or create chat for this user and project
        if project_id:
            result = await db.execute(
                select(Chat).where(
                    Chat.user_id == user.id,
                    Chat.project_id == project_id
                )
            )
            chat = result.scalar_one_or_none()

            if not chat:
                # Create new chat for this project
                chat = Chat(user_id=user.id, project_id=project_id)
                db.add(chat)
                await db.commit()
                await db.refresh(chat)

            chat_id = chat.id
        else:
            # Fallback to chat_id from frontend (for backwards compatibility)
            chat_id = data.get("chat_id", 1)

        # Fetch chat history BEFORE saving current message to avoid duplication
        chat_history = await _get_chat_history(chat_id, db, limit=10)

        # Save user message after fetching history
        user_message = Message(
            chat_id=chat_id,
            role="user",
            content=message_content
        )
        db.add(user_message)
        await db.commit()

        # ============================================================================
        # NEW: Unified Agent Factory System
        # ============================================================================

        # 1. Fetch the agent configuration from the database
        agent_model = None
        if agent_id:
            # Use the specified agent
            agent_result = await db.execute(
                select(MarketplaceAgent).where(
                    MarketplaceAgent.id == agent_id,
                    MarketplaceAgent.is_active == True
                )
            )
            agent_model = agent_result.scalar_one_or_none()
            if not agent_model:
                await websocket.send_json({
                    "type": "error",
                    "content": f"Agent with ID {agent_id} not found or inactive"
                })
                return
        else:
            # Fallback to default agent (first active agent or create a default)
            agent_result = await db.execute(
                select(MarketplaceAgent).where(
                    MarketplaceAgent.is_active == True
                ).limit(1)
            )
            agent_model = agent_result.scalar_one_or_none()

            if not agent_model:
                await websocket.send_json({
                    "type": "error",
                    "content": "No active agents available. Please configure an agent."
                })
                return

        logger.info(
            f"[UNIFIED-CHAT] Using agent: {agent_model.name} "
            f"(type: {agent_model.agent_type}, slug: {agent_model.slug})"
        )

        # Increment usage_count for the agent
        try:
            agent_model.usage_count = (agent_model.usage_count or 0) + 1
            db.add(agent_model)
            await db.commit()
            logger.info(f"[USAGE-TRACKING] Incremented usage_count for agent {agent_model.name} to {agent_model.usage_count}")
        except Exception as e:
            await db.rollback()
            logger.error(f"[USAGE-TRACKING] Failed to increment usage_count: {e}")
            # Continue anyway - this is not critical

        # 2. Build project context
        project_context_str = ""
        has_existing_files = False
        selected_files_content = ""

        if project_id:
            result = await db.execute(
                select(ProjectFile).where(ProjectFile.project_id == project_id)
            )
            files = result.scalars().all()
            if files:
                has_existing_files = True

                # Build file list for the AI to see
                file_list = "\n\nExisting files in project:"
                for file in files:
                    file_size = len(file.content) if file.content else 0
                    file_list += f"\n- {file.file_path} ({file_size} chars)"

                context = file_list

                # Selective file reading: Use AI to decide which files are relevant
                # This prevents token limit errors while still providing context
                # Maximum context size: ~15k tokens (~60k chars) to stay well under 65k limit
                MAX_CONTEXT_CHARS = 60000

                # First, try to identify obviously relevant files based on user message
                message_lower = message_content.lower()
                relevant_files = []

                for file in files:
                    file_path_lower = file.file_path.lower()

                    # Check if file is explicitly mentioned
                    if file.file_path in message_content or any(part in message_lower for part in file_path_lower.split('/')):
                        relevant_files.append(file)
                        continue

                    # Include key configuration files
                    if file_path_lower in ['package.json', 'vite.config.js', 'tsconfig.json', '.env', 'readme.md']:
                        relevant_files.append(file)
                        continue

                    # Include main entry points
                    if 'main' in file_path_lower or 'index' in file_path_lower or 'app' in file_path_lower:
                        relevant_files.append(file)

                # Get the most recent assistant response to include related files
                if chat_id:
                    last_msg_result = await db.execute(
                        select(Message).where(
                            Message.chat_id == chat_id,
                            Message.role == "assistant"
                        ).order_by(Message.created_at.desc()).limit(1)
                    )
                    last_assistant_msg = last_msg_result.scalar_one_or_none()

                    # If there's a previous response, try to identify files mentioned in it
                    if last_assistant_msg and last_assistant_msg.content:
                        for file in files:
                            if file not in relevant_files and file.file_path in last_assistant_msg.content:
                                relevant_files.append(file)

                # Limit total context size
                total_chars = 0
                selected_files = []

                for file in relevant_files:
                    file_chars = len(file.content) if file.content else 0
                    if total_chars + file_chars < MAX_CONTEXT_CHARS:
                        selected_files.append(file)
                        total_chars += file_chars
                    else:
                        break

                # Build context with selected files
                if selected_files:
                    selected_files_content = "\n\nRelevant files for context:"
                    for file in selected_files:
                        selected_files_content += f"\n\n{'='*60}\nFile: {file.file_path}\n{'='*60}\n{file.content}\n"

                    project_context_str += selected_files_content
                    logger.info(f"Selected {len(selected_files)} files for context ({total_chars} chars total)")

        # 3. Get project metadata (for TESSLATE.md and Git context)
        project = None
        if project_id:
            project_result = await db.execute(select(Project).where(Project.id == project_id))
            project = project_result.scalar_one_or_none()

        # Get container info for file operations (container-scoped agents)
        container_directory = None
        container_name = None  # Need this for TESSLATE context
        if container_id and project_id:
            try:
                # Container is already imported at module level (line 7)
                container_result = await db.execute(
                    select(Container).where(
                        Container.id == container_id,
                        Container.project_id == project_id
                    )
                )
                container = container_result.scalar_one_or_none()
                if container:
                    # Use directory as service name for shell ops (it's already sanitized)
                    container_name = container.directory if container.directory and container.directory != '.' else None
                    if container.directory and container.directory != '.':
                        container_directory = container.directory
                    logger.info(f"[UNIFIED-CHAT] Container-scoped agent: {container_name}, directory: {container_directory}")
            except Exception as e:
                logger.warning(f"[UNIFIED-CHAT] Could not get container info: {e}")

        if not container_id:
            logger.info(f"[UNIFIED-CHAT] Project-level agent (no container_id)")

        # Build TESSLATE context
        tesslate_context = None
        if project:
            tesslate_context = await _build_tesslate_context(
                project, user.id, db,
                container_name=container_name,
                container_directory=container_directory
            )

        # Build Git context
        git_context = None
        if project:
            git_context = await _build_git_context(project, user.id, db)

        # Combine all context
        if tesslate_context:
            project_context_str += tesslate_context
        if git_context:
            project_context_str += git_context

    except Exception as e:
        await db.rollback()
        logger.error(f"[UNIFIED-CHAT] Error building context: {e}", exc_info=True)
        await websocket.send_json({
            "type": "error",
            "content": f"Error building context: {str(e)}"
        })
        return

    # 3. Create the agent instance using the factory
    try:
        logger.info(f"[UNIFIED-CHAT] Creating agent instance via factory")

        # Get user's selected model override (if any)
        user_purchase_result = await db.execute(
            select(UserPurchasedAgent).where(
                UserPurchasedAgent.user_id == user.id,
                UserPurchasedAgent.agent_id == agent_model.id
            )
        )
        user_purchase = user_purchase_result.scalar_one_or_none()

        # Use user's selected model if available, otherwise use agent's default model
        model_name = (user_purchase.selected_model if user_purchase and user_purchase.selected_model
                     else agent_model.model or settings.litellm_default_models.split(",")[0])

        logger.info(f"[UNIFIED-CHAT] Using model: {model_name}")

        # For IterativeAgent, we need to create a model adapter
        model_adapter = None
        if agent_model.agent_type == "IterativeAgent":
            model_adapter = await create_model_adapter(
                model_name=model_name,
                user_id=user.id,
                db=db
            )
            logger.info(f"[UNIFIED-CHAT] Created model adapter for IterativeAgent")

        # Create the agent
        agent_instance = await create_agent_from_db_model(
            agent_model=agent_model,
            model_adapter=model_adapter
        )

        logger.info(
            f"[UNIFIED-CHAT] Successfully created {agent_model.agent_type} "
            f"for agent '{agent_model.name}'"
        )

        # Set max_iterations for IterativeAgent (default to 20 for complex tasks)
        if hasattr(agent_instance, 'max_iterations'):
            # Use client-provided value or default to 20
            max_iters = data.get('max_iterations', 20)
            agent_instance.max_iterations = max_iters
            logger.info(f"[UNIFIED-CHAT] Set max_iterations to {max_iters}")

    except Exception as e:
        logger.error(f"[UNIFIED-CHAT] Failed to create agent: {e}", exc_info=True)
        await websocket.send_json({
            "type": "error",
            "content": f"Failed to create agent: {str(e)}"
        })
        return

    # 4. Prepare execution context
    execution_context = {
        'user': user,
        'user_id': user.id,
        'project_id': project_id,
        'project_slug': project.slug if project else None,  # For shared volume file access
        'container_directory': container_directory,  # Container subdirectory for file ops
        'chat_id': chat_id,
        'db': db,
        'project_context_str': project_context_str,
        'has_existing_files': has_existing_files,
        'model': model_name,  # Use the resolved model name (user's selection or agent's default)
        'api_base': settings.litellm_api_base,
        'chat_history': chat_history,
        'edit_mode': edit_mode
    }

    # Add project context if available
    try:
        if project:
            execution_context['project_context'] = {
                "project_name": project.name,
                "project_description": project.description
            }

            # Add tesslate_context if available
            if tesslate_context:
                execution_context['project_context']["tesslate_context"] = tesslate_context
                logger.info(f"[UNIFIED-CHAT] Added TESSLATE.md context for project {project.id}")

            # Add git_context if available
            if git_context:
                execution_context['project_context']["git_context"] = git_context
                logger.info(f"[UNIFIED-CHAT] Added Git context for project {project.id}")
    except NameError as e:
        logger.warning(f"[UNIFIED-CHAT] Context variables not available: {e}")

    # 5. Run the agent and stream events back to the client
    full_response = ""
    agent_metadata = None

    try:
        logger.info(f"[UNIFIED-CHAT] Running agent for user request: {message_content[:100]}...")

        async for event in agent_instance.run(message_content, execution_context):
            event_type = event.get('type')

            # Send event to WebSocket
            try:
                await websocket.send_json(event)
            except Exception as e:
                logger.error(f"[UNIFIED-CHAT] WebSocket error: {e}")
                return

            # Track response for saving to database
            if event_type == 'stream':
                full_response += event.get('content', '')
            elif event_type == 'complete':
                data = event.get('data', {})
                final_response = data.get('final_response', '')
                if final_response:
                    full_response = final_response

                # For IterativeAgent, update metadata with completion info
                if agent_model.agent_type == 'IterativeAgent':
                    if agent_metadata is None:
                        agent_metadata = {
                            "agent_mode": True,
                            "agent_type": agent_model.agent_type,
                            "steps": []
                        }
                    # Add summary fields from completion event
                    agent_metadata["iterations"] = data.get('iterations', 0)
                    agent_metadata["tool_calls_made"] = data.get('tool_calls_made', 0)
                    agent_metadata["completion_reason"] = data.get('completion_reason', 'unknown')
            elif event_type == 'agent_step':
                # Collect steps for metadata
                if agent_metadata is None:
                    agent_metadata = {
                        "agent_mode": True,
                        "agent_type": agent_model.agent_type,
                        "steps": []
                    }
                agent_metadata.setdefault('steps', []).append(event.get('data', {}))

        logger.info(f"[UNIFIED-CHAT] Agent execution completed successfully")

    except Exception as e:
        logger.error(f"[UNIFIED-CHAT] Error during agent execution: {e}", exc_info=True)
        try:
            await websocket.send_json({
                "type": "error",
                "content": f"Agent error: {str(e)}"
            })
        except:
            pass
        return

    # 6. Save assistant message to database
    try:
        assistant_message = Message(
            chat_id=chat_id,
            role="assistant",
            content=full_response,
            message_metadata=agent_metadata  # Save agent metadata if available
        )
        db.add(assistant_message)
        await db.commit()
        logger.info(f"[UNIFIED-CHAT] Saved assistant message to database")
    except Exception as e:
        await db.rollback()
        logger.error(f"[UNIFIED-CHAT] Error saving message: {e}", exc_info=True)
        # Continue anyway - the response was already sent to user

def extract_complete_code_blocks(content: str):
    """Extract only complete code blocks with file paths"""
    # Improved pattern to catch proper file paths and avoid malformed ones
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
            
            # Clean up file path - remove any leading comment markers or "File:" text
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
                len(file_path) < 200 and  # Reasonable path length limit
                re.match(r'^[a-zA-Z0-9_./\-]+\.[a-zA-Z0-9]+$', file_path)):  # Valid characters only
                
                matches.append((file_path, code))
                processed_paths.add(file_path)
                print(f"Extracted file: {file_path}")
    
    return matches

async def save_file(file_path: str, code: str, project_id: UUID, user_id: UUID, db: AsyncSession, websocket: WebSocket):
    """
    Save file to database and dev container (Docker or K8s).

    Deployment-aware file saving:
    - Docker mode: Writes to local filesystem in users/{user_id}/projects/{project_id}/
    - Kubernetes mode: Writes to pod via K8s API

    Both modes trigger hot module reload for instant preview updates.
    """
    print(f"💾 Saving file: {file_path}")
    settings = get_settings()

    try:
        # 1. Save to database (for backup/version history)
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
            print(f"[DB] Saved {file_path} to database")
        except Exception as e:
            await db.rollback()
            logger.error(f"Database error saving file {file_path}: {e}", exc_info=True)
            # Continue to try writing to container even if DB save fails

        # 2. Write file to dev container (deployment mode aware)
        from ..services.orchestration import get_orchestrator, is_kubernetes_mode

        # Try unified orchestrator first
        orchestrator_success = False
        try:
            orchestrator = get_orchestrator()
            success = await orchestrator.write_file(
                user_id=user_id,
                project_id=project_id,
                container_name=None,  # Use default container
                file_path=file_path,
                content=code
            )

            if success:
                print(f"[ORCHESTRATOR] ✅ Wrote {file_path} to container - Vite HMR will trigger")
                orchestrator_success = True
            else:
                print(f"[ORCHESTRATOR] ⚠️ Warning: Failed to write to container")

        except Exception as e:
            print(f"[ORCHESTRATOR] ⚠️ Warning: Failed to write via orchestrator: {e}")
            # Don't fail the entire operation - file is in DB

        # Fallback: Docker mode - write to local filesystem
        if not orchestrator_success and not is_kubernetes_mode():
            # Docker: Write to local filesystem
            try:
                project_dir = get_project_path(user_id, project_id)
                full_path = os.path.join(project_dir, file_path)

                # Create parent directory (with safety check for Windows Docker volumes)
                parent_dir = os.path.dirname(full_path)
                if parent_dir:
                    try:
                        os.makedirs(parent_dir, exist_ok=True)
                    except FileExistsError:
                        # Handle race condition on Windows Docker volumes - verify it exists
                        if not os.path.exists(parent_dir):
                            raise

                async with aiofiles.open(full_path, 'w', encoding='utf-8') as f:
                    await f.write(code)

                print(f"[DOCKER] ✅ Wrote {file_path} to {full_path} - Vite HMR will trigger")

            except Exception as e:
                print(f"[DOCKER] ⚠️ Warning: Failed to write to filesystem: {e}")
                print(f"[DOCKER] File saved to DB but filesystem not updated - HMR won't trigger")
                # Don't fail the entire operation - file is in DB

        # 3. Notify frontend with the file
        try:
            await websocket.send_json({
                "type": "file_ready",
                "file_path": file_path,
                "content": code
            })
            print(f"✅ File ready notification sent: {file_path}")
        except Exception as e:
            print(f"WebSocket error notifying file ready: {e}")

    except Exception as e:
        print(f"❌ Error saving file {file_path}: {e}")
        import traceback
        traceback.print_exc()