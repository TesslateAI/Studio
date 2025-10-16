from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..database import get_db
from ..models import User, Chat, Message, Project, ProjectFile, Agent as AgentModel
from ..schemas import (
    Chat as ChatSchema, Message as MessageSchema, MessageCreate,
    AgentChatRequest, AgentChatResponse, AgentStepResponse
)
from ..auth import get_current_active_user
from ..config import get_settings
from openai import AsyncOpenAI
import json
import os
import aiofiles
import re
import asyncio
import logging

# Agent imports
from ..agent import UniversalAgent, get_tool_registry
from ..agent.models import get_model_adapter_from_settings

settings = get_settings()
router = APIRouter()
logger = logging.getLogger(__name__)


async def _build_git_context(project: Project, user_id: int, db: AsyncSession) -> Optional[str]:
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

        # Get container/pod info for command examples
        pod_name = f"dev-user{user_id}-project{project.id}"
        namespace = "tesslate-user-environments"
        container_name = f"tesslate-dev-user{user_id}-project{project.id}"

        if settings.deployment_mode == "kubernetes":
            cmd_prefix = f"kubectl exec -n {namespace} {pod_name} --"
            git_cmd_example = f"{cmd_prefix} git status"
        else:
            cmd_prefix = f"docker exec {container_name}"
            git_cmd_example = f"{cmd_prefix} git status"

        # Build comprehensive Git context
        context_lines = [
            "\n=== Git Version Control ===",
            f"Repository: {git_repo.repo_url}",
        ]

        if git_status:
            context_lines.extend([
                f"Current Branch: {git_status['branch']}",
                f"Status: {git_status['status']}",
                f"Uncommitted Changes: {git_status['changes_count']}",
            ])

            if git_status.get('ahead', 0) > 0:
                context_lines.append(f"Ahead of Remote: {git_status['ahead']} commits")
            if git_status.get('behind', 0) > 0:
                context_lines.append(f"Behind Remote: {git_status['behind']} commits")

            if git_status.get('last_commit'):
                last_commit = git_status['last_commit']
                context_lines.append(f"Last Commit: {last_commit['message']} ({last_commit['sha'][:8]})")

        context_lines.extend([
            "",
            "=== Git Operations Available ===",
            "You can perform Git operations using the Bash tool.",
            "",
            "Command Format:",
            f"  {cmd_prefix} <git-command>",
            "",
            "Common Operations:",
            f"  Check status:    {git_cmd_example}",
            f"  View changes:    {cmd_prefix} git diff",
            f"  Stage files:     {cmd_prefix} git add .",
            f"  Create commit:   {cmd_prefix} git commit -m \"your message\"",
            f"  Push changes:    {cmd_prefix} git push origin {git_status['branch'] if git_status else 'main'}",
            f"  Pull updates:    {cmd_prefix} git pull origin {git_status['branch'] if git_status else 'main'}",
            f"  Create branch:   {cmd_prefix} git checkout -b feature/branch-name",
            f"  Switch branch:   {cmd_prefix} git checkout branch-name",
            "",
            "=== Commit Message Guidelines ===",
            "Use conventional commit format for better history:",
            "  feat: New feature",
            "  fix: Bug fix",
            "  docs: Documentation changes",
            "  refactor: Code refactoring",
            "  test: Tests",
            "  chore: Maintenance",
            "",
            "Example:",
            f"  {cmd_prefix} git add .",
            f"  {cmd_prefix} git commit -m \"feat: add user authentication\"",
            "",
            "=== Important Notes ===",
            "- Always commit your changes before making significant modifications",
            "- Use descriptive commit messages",
            "- Check status before and after Git operations",
            "- Ask the user if they want to push changes to remote",
        ])

        if git_repo.auto_push:
            context_lines.append("- Auto-push is ENABLED - commits will be automatically pushed")
        else:
            context_lines.append("- Auto-push is DISABLED - ask user before pushing")

        return "\n".join(context_lines)

    except Exception as e:
        logger.error(f"[GIT-CONTEXT] Failed to build Git context: {e}", exc_info=True)
        return None


async def _build_tesslate_context(project: Project, user_id: int, db: AsyncSession) -> Optional[str]:
    """
    Build TESSLATE.md context for agent.

    Reads TESSLATE.md from the user's project container. If it doesn't exist,
    copies the generic template from orchestrator/template/TESSLATE.md.

    Returns the TESSLATE.md content as a formatted string, or None if unable to read.
    """
    try:
        # Read TESSLATE.md from the user's project (deployment-aware)
        tesslate_content = None

        if settings.deployment_mode == "kubernetes":
            # Kubernetes mode: Read from pod
            from ..k8s_client import get_k8s_manager
            k8s_manager = get_k8s_manager()

            tesslate_content = await k8s_manager.read_file_from_pod(
                user_id=user_id,
                project_id=str(project.id),
                file_path="TESSLATE.md"
            )

            # If TESSLATE.md doesn't exist, copy the template
            if tesslate_content is None:
                logger.info(f"[TESSLATE-CONTEXT] TESSLATE.md not found in project {project.id}, copying template")

                # Read the generic template
                template_path = os.path.join(os.path.dirname(__file__), "..", "..", "template", "TESSLATE.md")
                try:
                    async with aiofiles.open(template_path, 'r', encoding='utf-8') as f:
                        template_content = await f.read()

                    # Write template to pod
                    success = await k8s_manager.write_file_to_pod(
                        user_id=user_id,
                        project_id=str(project.id),
                        file_path="TESSLATE.md",
                        content=template_content
                    )

                    if success:
                        tesslate_content = template_content
                        logger.info(f"[TESSLATE-CONTEXT] Successfully copied template to project {project.id}")
                    else:
                        logger.warning(f"[TESSLATE-CONTEXT] Failed to write template to pod")

                except Exception as e:
                    logger.error(f"[TESSLATE-CONTEXT] Failed to read template file: {e}")

        else:
            # Docker mode: Read from local filesystem
            project_dir = f"users/{user_id}/{project.id}"
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
    current_user: User = Depends(get_current_active_user),
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
    current_user: User = Depends(get_current_active_user),
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
    project_id: int,
    current_user: User = Depends(get_current_active_user),
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


@router.post("/agent", response_model=AgentChatResponse)
async def agent_chat(
    request: AgentChatRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Agent mode chat - uses Universal Agent with tool calling.

    The agent can read/write files, execute commands, and manage the project
    autonomously using any language model (Cerebras, GPT, Claude, etc.)

    This is an alternative to the streaming WebSocket chat that gives the AI
    more autonomy and tool access.

    Args:
        request: Agent chat request with project_id and message
        current_user: Authenticated user
        db: Database session

    Returns:
        Agent execution result with steps and final response
    """
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
            raise HTTPException(
                status_code=404,
                detail="Project not found or access denied"
            )

        logger.info(
            f"Agent chat started - user: {current_user.id}, "
            f"project: {request.project_id}, message: {request.message[:100]}..."
        )

        # Load agent configuration if agent_id is provided
        agent_system_prompt = None
        agent_name = "Universal Agent"
        if request.agent_id:
            try:
                agent_result = await db.execute(
                    select(AgentModel).where(
                        AgentModel.id == request.agent_id,
                        AgentModel.is_active == True
                    )
                )
                db_agent = agent_result.scalar_one_or_none()
                if db_agent:
                    agent_system_prompt = db_agent.system_prompt
                    agent_name = db_agent.name
                    logger.info(f"Using agent '{agent_name}' (ID: {request.agent_id}) with custom system prompt")
                else:
                    logger.warning(f"Agent ID {request.agent_id} not found or inactive, using default agent")
            except Exception as e:
                logger.error(f"Error loading agent configuration: {e}")

        # Create model adapter
        model_adapter = get_model_adapter_from_settings(settings)

        # Create agent with optional system prompt
        agent = UniversalAgent(
            model=model_adapter,
            tool_registry=get_tool_registry(),
            max_iterations=request.max_iterations,
            minimal_prompts=request.minimal_prompts,
            system_prompt=agent_system_prompt  # Pass the agent's system prompt if available
        )

        # Prepare context for tool execution
        context = {
            "user_id": current_user.id,
            "project_id": request.project_id,
            "db": db
        }

        # Get project context
        project_context = {
            "project_name": project.name,
            "project_description": project.description
        }

        # Build TESSLATE.md context (project-specific documentation for AI agents)
        tesslate_context = await _build_tesslate_context(project, current_user.id, db)
        if tesslate_context:
            project_context["tesslate_context"] = tesslate_context
            logger.info(f"[AGENT-CHAT] Added TESSLATE.md context for project {project.id}")

        # Check if project has Git repository connected and inject Git context
        git_context = await _build_git_context(project, current_user.id, db)
        if git_context:
            project_context["git_context"] = git_context

        # Run agent
        agent_result = await agent.run(
            user_request=request.message,
            context=context,
            project_context=project_context
        )

        # Convert steps to response format
        steps_response = [
            AgentStepResponse(
                iteration=step.iteration,
                thought=step.thought,
                tool_calls=[tc.name for tc in step.tool_calls],
                response_text=step.response_text,
                is_complete=step.is_complete,
                timestamp=step.timestamp.isoformat()
            )
            for step in agent_result.steps
        ]

        # Save to chat history
        # Get or create chat for this project
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

        # Save user message
        user_message = Message(
            chat_id=chat.id,
            role="user",
            content=request.message
        )
        db.add(user_message)

        # Save agent response
        assistant_message = Message(
            chat_id=chat.id,
            role="assistant",
            content=f"[Agent Mode - {agent_result.tool_calls_made} tool calls]\n\n{agent_result.final_response}"
        )
        db.add(assistant_message)
        await db.commit()

        logger.info(
            f"Agent chat completed - success: {agent_result.success}, "
            f"iterations: {agent_result.iterations}, tool_calls: {agent_result.tool_calls_made}"
        )

        return AgentChatResponse(
            success=agent_result.success,
            iterations=agent_result.iterations,
            final_response=agent_result.final_response,
            tool_calls_made=agent_result.tool_calls_made,
            completion_reason=agent_result.completion_reason,
            steps=steps_response,
            error=agent_result.error
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Agent chat error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Agent execution failed: {str(e)}"
        )


class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[int, WebSocket] = {}

    async def connect(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        self.active_connections[user_id] = websocket

    def disconnect(self, user_id: int):
        if user_id in self.active_connections:
            del self.active_connections[user_id]

    async def send_personal_message(self, message: str, user_id: int):
        if user_id in self.active_connections:
            await self.active_connections[user_id].send_text(message)

manager = ConnectionManager()

@router.websocket("/ws/{token}")
async def websocket_endpoint(websocket: WebSocket, token: str, db: AsyncSession = Depends(get_db)):
    user = None
    try:
        # Verify token and get user
        from ..auth import jwt, settings, JWTError
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        username = payload.get("sub")
        
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        if not user:
            await websocket.close(code=1008)
            return
        
        await manager.connect(websocket, user.id)
        
        while True:
            try:
                data = await websocket.receive_json()
                await handle_chat_message(data, user, db, websocket)
            except WebSocketDisconnect:
                break
            except Exception as e:
                print(f"Error handling message: {e}")
                try:
                    await websocket.send_json({
                        "type": "error",
                        "content": f"Error: {str(e)}"
                    })
                except:
                    break
                    
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        if user:
            manager.disconnect(user.id)

async def handle_chat_message(data: dict, user: User, db: AsyncSession, websocket: WebSocket):
    message_content = data.get("message")
    project_id = data.get("project_id")
    agent_id = data.get("agent_id")  # Get agent_id from request

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

        # Save user message
        user_message = Message(
            chat_id=chat_id,
            role="user",
            content=message_content
        )
        db.add(user_message)
        await db.commit()

        # Get project context if available
        context = ""
        has_existing_files = False
        if project_id:
            result = await db.execute(
                select(ProjectFile).where(ProjectFile.project_id == project_id)
            )
            files = result.scalars().all()
            if files:
                has_existing_files = True
                context = "\n\nProject files:\n"
                for file in files:
                    context += f"\nFile: {file.file_path}\n{file.content}\n"
    except Exception as e:
        await db.rollback()
        logger.error(f"Database error in initial chat setup: {e}", exc_info=True)
        await websocket.send_json({
            "type": "error",
            "content": f"Database error: {str(e)}"
        })
        return
    
    # WebSocket is already connected if we got here
    
    # Stream response from OpenAI
    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_api_base
    )
    
    full_response = ""
    processed_files = set()
    
    # Get agent and use its system prompt
    agent = None
    base_system_prompt = """You are an expert React developer. Generate clean, modern React code for Vite applications using Tailwind CSS.

CRITICAL RULES:
1. DO EXACTLY WHAT IS ASKED.
2. USE STANDARD TAILWIND CLASSES ONLY. No `bg-background` or `text-foreground`. Use `bg-white`, `text-black`, `bg-blue-500`, etc.
3. FILE COUNT LIMITS: A simple change should only modify 1-2 files.
4. NO ROUTING LIBRARIES like `react-router-dom` unless explicitly asked. Use `<a>` tags.
5. PRESERVATION IS KEY (for edits): Do not rewrite entire components. Integrate your changes surgically. Preserve all existing logic, props, and state.
6. COMPLETENESS: Each file must be COMPLETE from the first line to the last. NO "..." or truncation.
7. NO CONVERSATION: Your output must contain ONLY code wrapped in the specified format.
8. When providing code, ALWAYS specify the filename at the top of the code block like:
```javascript
// File: path/to/file.js
<code>
9. ALWAYS PLAN AND MAKE A MULTIPAGE WEB APPLICATION. DO NOT CREATE SINGLE PAGE APPS. THEY SHOULD ALL BE CONNECTED.
```"""

    # Fetch agent if agent_id is provided
    if agent_id:
        try:
            agent_result = await db.execute(
                select(AgentModel).where(AgentModel.id == agent_id, AgentModel.is_active == True)
            )
            agent = agent_result.scalar_one_or_none()
            if agent:
                base_system_prompt = agent.system_prompt
                logger.info(f"Using agent '{agent.name}' (ID: {agent.id}) with custom system prompt")
            else:
                logger.warning(f"Agent ID {agent_id} not found or inactive, using default system prompt")
        except Exception as e:
            logger.error(f"Error fetching agent: {e}")
            # Continue with default prompt

    surgical_edit_prompt = """

CRITICAL: THIS IS AN EDIT TO AN EXISTING APPLICATION.

You MUST follow these rules:
1. DO NOT regenerate the entire application.
2. ONLY edit the EXACT files needed for the requested change.
3. If the user says "update the header", ONLY edit the Header component.
4. When adding a new component:
   - Create the new component file.
   - UPDATE ONLY the parent component that will use it.
5. NEVER TRUNCATE FILES. Always return COMPLETE files with ALL content. No "..." ellipsis.
6. You are a SURGEON making a precise incision, not an artist repainting the canvas. 99% of the original code should remain untouched."""

    system_prompt = base_system_prompt
    if has_existing_files:
        system_prompt += surgical_edit_prompt

    try:
        print(f"Calling AI API with model: {settings.openai_model}")
        print(f"API Base: {settings.openai_api_base}")
        
        stream = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"{context}\n\nUser request: {message_content}"}
            ],
            stream=True,
            temperature=0.7
        )
        
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                full_response += content
                
                # Send stream chunk
                try:
                    await websocket.send_json({
                        "type": "stream",
                        "content": content
                    })
                except Exception as e:
                    print(f"WebSocket error during streaming: {e}")
                    return
        
        # Process all files at the end when response is complete
        if project_id:
            code_blocks = extract_complete_code_blocks(full_response)
            print(f"Processing {len(code_blocks)} files from completed response")

            package_json_modified = False

            for i, (file_path, code) in enumerate(code_blocks):
                if file_path not in processed_files:
                    print(f"📁 Saving file {i+1}/{len(code_blocks)}: {file_path}")
                    processed_files.add(file_path)
                    await save_file(file_path, code, project_id, user.id, db, websocket)

                    # Track if package.json was modified
                    if file_path == "package.json":
                        package_json_modified = True

                    # Small delay between files to prevent overwhelming dev server
                    if i < len(code_blocks) - 1:  # Don't delay after the last file
                        await asyncio.sleep(0.2)

            # Run npm install if package.json was modified (K8s only - Docker handles this automatically)
            if package_json_modified and settings.deployment_mode == "kubernetes":
                print("[NPM] package.json was modified, running npm install...")
                try:
                    from ..k8s_client import get_k8s_manager
                    k8s_manager = get_k8s_manager()

                    await websocket.send_json({
                        "type": "status",
                        "content": "📦 Installing dependencies..."
                    })

                    output = await k8s_manager.execute_command_in_pod(
                        user_id=user.id,
                        project_id=str(project_id),
                        command=["npm", "install"],
                        timeout=180  # 3 minutes for npm install
                    )

                    print(f"[NPM] ✅ npm install completed")
                    print(f"[NPM] Output: {output[:500]}")  # Log first 500 chars

                    await websocket.send_json({
                        "type": "status",
                        "content": "✅ Dependencies installed successfully"
                    })

                except Exception as e:
                    print(f"[NPM] ⚠️ Failed to run npm install: {e}")
                    await websocket.send_json({
                        "type": "warning",
                        "content": f"⚠️ Failed to install dependencies: {str(e)}"
                    })
                
    except Exception as e:
        print(f"Error during AI stream: {e}")
        await websocket.send_json({
            "type": "error",
            "content": f"Error: {str(e)}"
        })
        return
    
    # Save assistant message
    try:
        assistant_message = Message(
            chat_id=chat_id,
            role="assistant",
            content=full_response
        )
        db.add(assistant_message)
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"Database error saving assistant message: {e}", exc_info=True)
        # Continue anyway - the AI response was already sent to the user

    # Send completion message
    try:
        await websocket.send_json({
            "type": "complete",
            "content": full_response
        })
        print("✅ Sent completion message to WebSocket")
    except Exception as e:
        print(f"❌ Error sending completion message: {e}")

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

async def save_file(file_path: str, code: str, project_id: int, user_id: int, db: AsyncSession, websocket: WebSocket):
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
        if settings.deployment_mode == "kubernetes":
            # Kubernetes: Write to pod via K8s API
            try:
                from ..dev_server_manager import get_container_manager
                k8s_manager = get_container_manager()

                success = await k8s_manager.write_file_to_pod(
                    user_id=user_id,
                    project_id=str(project_id),
                    file_path=file_path,
                    content=code
                )

                if not success:
                    raise RuntimeError("Failed to write file to pod")

                print(f"[K8S] ✅ Wrote {file_path} to pod - Vite HMR will trigger")

            except Exception as e:
                print(f"[K8S] ⚠️ Warning: Failed to write to pod: {e}")
                print(f"[K8S] File saved to DB but pod not updated - HMR won't trigger")
                # Don't fail the entire operation - file is in DB

        else:
            # Docker: Write to local filesystem
            try:
                project_dir = f"users/{user_id}/{project_id}"
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