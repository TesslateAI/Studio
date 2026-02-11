"""
Subagent Manager

Manages specialized subagents that can be invoked by the main TesslateAgent.
Ported from minimal-codex's subagents.py and adapted for Tesslate's async
infrastructure, container-based execution, and SSE event streaming.

Subagents are lightweight agent instances with scoped tool access and focused
system prompts. They run their own agent loop but CANNOT invoke other subagents
(no nesting).

Built-in subagent types:
- general-purpose: All tools, handles complex multi-step tasks
- Plan: Read-only tools, creates implementation plans
- Explore: Read-only tools, fast codebase exploration

Extended features (1:1 from minimal-codex):
- Resumable sessions via agent_id / resume_id
- Custom subagents from container (.tesslate/agents/*.md)
- Custom subagents from DB (MarketplaceAgent item_type="subagent")
"""

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from .prompt_templates import load_prompt
from .tools.registry import ToolRegistry, create_scoped_tool_registry

logger = logging.getLogger(__name__)

# Maximum concurrent subagent invocations (matches minimal-codex)
MAX_CONCURRENT = 10

# Read-only tools for restricted subagents
READ_ONLY_TOOLS = [
    "read_file",
    "get_project_info",
    "todo_read",
    "save_plan",
    "update_plan",
]

# All standard tools (everything except invoke_subagent)
ALL_STANDARD_TOOLS = [
    "read_file",
    "write_file",
    "patch_file",
    "multi_edit",
    "apply_patch",
    "bash_exec",
    "shell_open",
    "shell_exec",
    "shell_close",
    "get_project_info",
    "todo_read",
    "todo_write",
    "save_plan",
    "update_plan",
    "web_fetch",
]


@dataclass
class SubagentConfig:
    """Configuration for a subagent type."""

    name: str
    description: str
    tools: list[str] | None  # None = all standard tools
    system_prompt: str
    max_turns: int = 10


@dataclass
class SubagentSession:
    """Tracks a subagent execution session (resumable)."""

    agent_id: str
    name: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    result: str | None = None
    turns_used: int = 0


# Built-in subagent configurations
def _get_builtin_configs() -> dict[str, SubagentConfig]:
    """Load built-in subagent configurations from prompt templates."""
    return {
        "general-purpose": SubagentConfig(
            name="general-purpose",
            description="General-purpose agent for complex multi-step tasks. Has access to all tools.",
            tools=None,  # All standard tools
            system_prompt=load_prompt("general_purpose", subdir="subagent"),
            max_turns=15,
        ),
        "Plan": SubagentConfig(
            name="Plan",
            description="Software architect agent for designing implementation plans. Read-only tools only.",
            tools=READ_ONLY_TOOLS,
            system_prompt=load_prompt("plan", subdir="subagent"),
            max_turns=10,
        ),
        "Explore": SubagentConfig(
            name="Explore",
            description="Fast exploration agent for searching codebases. Read-only tools, 3-5 tool calls.",
            tools=READ_ONLY_TOOLS,
            system_prompt=load_prompt("explore", subdir="subagent"),
            max_turns=8,
        ),
    }


class SubagentManager:
    """
    Manages subagent invocation and lifecycle.

    Subagents are lightweight TesslateAgent instances with:
    - Scoped tool access (determined by SubagentConfig)
    - No invoke_subagent tool (prevents nesting)
    - Resumable sessions via agent_id
    - Custom subagents from container files or DB
    - Max turn limits for safety
    """

    def __init__(
        self,
        model_adapter,
        base_tool_registry: ToolRegistry,
        context: dict[str, Any],
    ):
        self.model_adapter = model_adapter
        self.base_registry = base_tool_registry
        self.context = context
        self._configs = _get_builtin_configs()
        self._sessions: dict[str, SubagentSession] = {}
        self._sessions_lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    def get_available_subagents(self) -> list[dict[str, str]]:
        """Get list of available subagent types with descriptions."""
        return [
            {"name": cfg.name, "description": cfg.description} for cfg in self._configs.values()
        ]

    def get_invoke_tool_description(self) -> str:
        """Generate the description for the invoke_subagent tool."""
        agents_list = "\n".join(
            f"  - {cfg.name}: {cfg.description}" for cfg in self._configs.values()
        )
        return (
            f"Invoke a specialized subagent to handle a task. "
            f"Available subagents:\n{agents_list}\n\n"
            f"The subagent runs its own agent loop with scoped tools and returns "
            f"the result as text. Use this for parallel exploration, planning, "
            f"or delegating complex subtasks.\n\n"
            f"Pass resume_id to continue a previous subagent session."
        )

    # -------------------------------------------------------------------------
    # Custom Subagent Loading
    # -------------------------------------------------------------------------

    async def load_custom_subagents(self):
        """Load custom subagents from container .tesslate/agents/ directory."""
        try:
            from ..services.orchestration import get_orchestrator

            orchestrator = get_orchestrator()

            user_id = self.context.get("user_id")
            project_id = str(self.context.get("project_id", ""))
            project_slug = self.context.get("project_slug")
            container_name = self.context.get("container_name")

            if not project_id:
                return

            # List .tesslate/agents/ files
            try:
                result = await orchestrator.execute_command(
                    user_id=user_id,
                    project_id=project_id,
                    container_name=container_name,
                    command="ls .tesslate/agents/ 2>/dev/null || true",
                    project_slug=project_slug,
                )
                stdout = ""
                if isinstance(result, dict):
                    stdout = result.get("stdout", "") or result.get("output", "")
                elif isinstance(result, str):
                    stdout = result

                if not stdout.strip():
                    return

                md_files = [
                    f.strip() for f in stdout.strip().split("\n") if f.strip().endswith(".md")
                ]
            except Exception:
                return  # No .tesslate/agents/ directory — that's fine

            # Read and parse each file
            for md_file in md_files:
                try:
                    content = await orchestrator.read_file(
                        user_id=user_id,
                        project_id=project_id,
                        container_name=container_name,
                        file_path=f".tesslate/agents/{md_file}",
                        project_slug=project_slug,
                    )
                    if content:
                        config = self._parse_agent_file(content, md_file)
                        if config:
                            self._configs[config.name] = config
                            logger.info(f"[SubagentManager] Loaded custom subagent: {config.name}")
                except Exception as e:
                    logger.warning(f"[SubagentManager] Failed to load {md_file}: {e}")

        except Exception as e:
            logger.warning(f"[SubagentManager] Error loading custom subagents: {e}")

    async def load_user_subagents(self):
        """Load custom subagents from DB (MarketplaceAgent item_type='subagent')."""
        try:
            db = self.context.get("db")
            user_id = self.context.get("user_id")
            if not db or not user_id:
                return

            from sqlalchemy import select

            from ..models import MarketplaceAgent, UserPurchasedAgent

            result = await db.execute(
                select(MarketplaceAgent)
                .join(UserPurchasedAgent, UserPurchasedAgent.agent_id == MarketplaceAgent.id)
                .where(
                    UserPurchasedAgent.user_id == user_id,
                    UserPurchasedAgent.is_active == True,  # noqa: E712
                    MarketplaceAgent.item_type == "subagent",
                )
            )
            subagent_models = result.scalars().all()

            for agent_model in subagent_models:
                tools = agent_model.tools
                config = SubagentConfig(
                    name=agent_model.name,
                    description=agent_model.description or "",
                    tools=tools if tools else None,
                    system_prompt=agent_model.system_prompt or "",
                    max_turns=(agent_model.config or {}).get("max_turns", 10),
                )
                # DB subagents override file-based if name collision
                self._configs[config.name] = config
                logger.info(f"[SubagentManager] Loaded DB subagent: {config.name}")

        except Exception as e:
            logger.warning(f"[SubagentManager] Error loading user subagents: {e}")

    def _parse_agent_file(self, content: str, filename: str) -> SubagentConfig | None:
        """Parse a subagent markdown file with YAML-like frontmatter.

        Format (1:1 codex):
        ---
        name: my-agent
        description: Does things
        tools: read_file, write_file
        model: inherit
        ---
        System prompt body here...
        """
        if not content.startswith("---"):
            return None

        parts = content.split("---", 2)
        if len(parts) < 3:
            return None

        # Parse frontmatter as simple key: value pairs
        frontmatter = {}
        for line in parts[1].strip().split("\n"):
            if ":" in line:
                key, _, value = line.partition(":")
                frontmatter[key.strip()] = value.strip()

        system_prompt = parts[2].strip()
        if not system_prompt:
            return None

        # Parse tools
        tools_str = frontmatter.get("tools")
        tools = None
        if tools_str and tools_str.lower() not in ("null", "none", "all", ""):
            tools = [t.strip() for t in tools_str.split(",") if t.strip()]

        stem = filename.rsplit(".", 1)[0] if "." in filename else filename

        return SubagentConfig(
            name=frontmatter.get("name", stem),
            description=frontmatter.get("description", ""),
            tools=tools,
            system_prompt=system_prompt,
        )

    # -------------------------------------------------------------------------
    # Tool Registry
    # -------------------------------------------------------------------------

    def _create_scoped_registry(self, config: SubagentConfig) -> ToolRegistry:
        """Create a tool registry scoped for a subagent (no invoke_subagent)."""
        if config.tools is not None:
            tool_names = [t for t in config.tools if t != "invoke_subagent"]
        else:
            tool_names = [t for t in ALL_STANDARD_TOOLS if t != "invoke_subagent"]

        return create_scoped_tool_registry(tool_names)

    # -------------------------------------------------------------------------
    # Invocation
    # -------------------------------------------------------------------------

    async def invoke(
        self,
        name: str,
        task: str,
        max_turns: int | None = None,
        context_str: str | None = None,
        resume_id: str | None = None,
    ) -> tuple[str, str]:
        """
        Invoke a subagent to perform a task.

        Args:
            name: Subagent name
            task: Task description
            max_turns: Override max turns
            context_str: Optional context from parent agent
            resume_id: Optional agent_id to resume a previous session

        Returns:
            Tuple of (result_text, agent_id)

        Raises:
            ValueError: If subagent name not found
        """
        config = self._configs.get(name)
        if not config:
            available = ", ".join(self._configs.keys())
            raise ValueError(f"Unknown subagent '{name}'. Available: {available}")

        effective_max_turns = max_turns or config.max_turns

        async with self._semaphore:
            logger.info(
                f"[SubagentManager] Invoking '{name}' subagent "
                f"(max_turns={effective_max_turns}, resume_id={resume_id})"
            )

            scoped_registry = self._create_scoped_registry(config)

            # Build task message with optional context
            task_message = task
            if context_str:
                task_message = f"## Context from main agent\n{context_str}\n\n## Your task\n{task}"

            # Resolve session
            agent_id = resume_id or str(uuid.uuid4())[:8]
            async with self._sessions_lock:
                existing_session = self._sessions.get(agent_id) if resume_id else None

            result = await self._run_subagent_loop(
                config=config,
                registry=scoped_registry,
                task_message=task_message,
                max_turns=effective_max_turns,
                session=existing_session,
                agent_id=agent_id,
            )

            logger.info(
                f"[SubagentManager] Subagent '{name}' completed "
                f"(agent_id={agent_id}, {len(result)} chars)"
            )

            return result, agent_id

    # -------------------------------------------------------------------------
    # Agent Loop
    # -------------------------------------------------------------------------

    async def _run_subagent_loop(
        self,
        config: SubagentConfig,
        registry: ToolRegistry,
        task_message: str,
        max_turns: int,
        session: SubagentSession | None,
        agent_id: str,
    ) -> str:
        """Run a lightweight agent loop for a subagent."""
        from .tool_converter import registry_to_openai_tools

        # Initialize or resume messages
        if session and session.messages:
            messages = list(session.messages)
            messages.append({"role": "user", "content": f"[Continuation] {task_message}"})
        else:
            messages = [
                {"role": "system", "content": config.system_prompt},
                {"role": "user", "content": task_message},
            ]

        openai_tools = registry_to_openai_tools(registry)
        last_text = ""

        for turn in range(max_turns):
            logger.debug(f"[Subagent:{config.name}] Turn {turn + 1}/{max_turns}")

            content = ""
            tool_calls = []
            try:
                async for event in self.model_adapter.chat_with_tools(
                    messages=messages,
                    tools=openai_tools,
                    tool_choice="auto",
                ):
                    event_type = event.get("type", "")
                    if event_type == "text_delta":
                        content += event.get("content", "")
                    elif event_type == "tool_calls_complete":
                        tool_calls = event.get("tool_calls", [])
                    elif event_type == "done":
                        pass
            except Exception as e:
                logger.error(f"[Subagent:{config.name}] LLM error: {e}")
                await self._save_session(agent_id, config.name, messages)
                return last_text or f"Subagent error: {str(e)}"

            if content:
                last_text = content

            # No tool calls = subagent is done
            if not tool_calls:
                await self._save_session(agent_id, config.name, messages)
                return last_text

            # Serialize assistant message
            assistant_msg = self._serialize_assistant_message(content, tool_calls)
            messages.append(assistant_msg)

            # Execute tool calls
            for tc in tool_calls:
                tc_id = tc.get("id", "")
                fn = tc.get("function", {})
                tool_name = fn.get("name", "")
                arguments_str = fn.get("arguments", "{}")

                try:
                    parameters = json.loads(arguments_str)
                except json.JSONDecodeError:
                    parameters = {}

                result = await registry.execute(
                    tool_name=tool_name,
                    parameters=parameters,
                    context=self.context,
                )

                result_content = self._format_tool_result(result)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": result_content,
                    }
                )

        # Hit max turns
        logger.warning(f"[Subagent:{config.name}] Hit max turns ({max_turns})")
        await self._save_session(agent_id, config.name, messages)
        return last_text or "Subagent reached maximum turns without completion."

    # -------------------------------------------------------------------------
    # Session Management
    # -------------------------------------------------------------------------

    def get_session(self, agent_id: str) -> SubagentSession | None:
        """Get a subagent session by ID (for trajectory saving)."""
        return self._sessions.get(agent_id)

    async def _save_session(
        self,
        agent_id: str,
        name: str,
        messages: list[dict[str, Any]],
    ):
        """Save session for potential resumption."""
        async with self._sessions_lock:
            self._sessions[agent_id] = SubagentSession(
                agent_id=agent_id,
                name=name,
                messages=messages,
            )

    # -------------------------------------------------------------------------
    # Serialization Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _serialize_assistant_message(
        content: str | None,
        tool_calls: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Serialize assistant message following Codex's exact format."""
        if not tool_calls:
            return {"role": "assistant", "content": content or ""}

        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": tc.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": tc.get("function", {}).get("name", ""),
                        "arguments": tc.get("function", {}).get("arguments", "{}"),
                    },
                }
                for tc in tool_calls
            ],
        }

    @staticmethod
    def _format_tool_result(result: dict[str, Any]) -> str:
        """Format a tool execution result as a string for the LLM."""
        MAX_OUTPUT = 10000

        if result.get("success"):
            tool_result = result.get("result", {})
            if isinstance(tool_result, dict):
                parts = []
                if "message" in tool_result:
                    parts.append(tool_result["message"])
                for field_name in ("content", "stdout", "output"):
                    if field_name in tool_result:
                        output = tool_result[field_name]
                        if len(output) > MAX_OUTPUT:
                            half = MAX_OUTPUT // 2
                            output = (
                                output[:half]
                                + f"\n... ({len(output) - MAX_OUTPUT} chars truncated) ...\n"
                                + output[-half:]
                            )
                        parts.append(output)
                return "\n".join(parts) if parts else str(tool_result)
            return str(tool_result)
        else:
            error = result.get("error", "Unknown error")
            return f"Error: {error}"
