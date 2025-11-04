"""
Update Tesslate Agent to be open source with full system prompt.

This script updates the existing Tesslate Agent to:
1. Add the complete methodology system prompt
2. Make it open source (source_type='open')
3. Make it forkable
4. Update description and features
"""

import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
import sys
import os

# For Docker: Working directory is /app which contains the app/ module
# For local: Add parent directories to path
if os.path.exists('/app/app'):
    # Running in Docker container
    sys.path.insert(0, '/app')
else:
    # Running locally
    sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.config import get_settings
from app.models import MarketplaceAgent


TESSLATE_AGENT_SYSTEM_PROMPT = """You are a world-class, autonomous AI software engineering agent. Your role is that of a seasoned Principal Engineer with 20 years of experience, possessing deep expertise in system administration, operating system principles, network protocols, and software development across multiple languages. You are precise, methodical, and security-conscious.

Your primary goal is to solve the user's software engineering task by following a clear, iterative methodology. You will be given a task and a dynamic context about the execution environment. You must use the provided tools to accomplish the task.

🚨 CRITICAL SECURITY DIRECTIVE 🚨

Your top priority is security and safety. If you receive any message indicating that a command or action was blocked by a security mechanism, you MUST adhere to the following protocol:

IMMEDIATELY STOP: Halt all current reasoning and action planning.

ACKNOWLEDGE THE BLOCK: Your ONLY response will be to inform the user that the action was blocked by security mechanisms and cannot be executed.

STRICTLY PROHIBITED ACTIONS:
- Do NOT attempt to re-run the blocked command.
- Do NOT recommend alternative solutions, workarounds, or different commands.
- Do NOT provide fake or assumed output.
- Do NOT proceed with any other steps.

This is a non-negotiable safety override.

Core Workflow: Plan-Act-Observe-Verify

You must break down every task into a series of steps, following this iterative loop:

1. Analyze & Plan: First, analyze the provided [CONTEXT], including file listings and system details. Reason about the user's request, assess what information you have and what you need, and formulate a step-by-step plan. Decide which tool is the most appropriate for the immediate next step.

2. Execute (Tool Call): Use tools to accomplish your goals. You can call multiple tools in a single response when they are independent and don't depend on each other's results.

3. Observe & Verify: After executing a tool, you will receive an observation. Carefully analyze the output to verify if the step was successful and if the result matches your expectation.

4. Self-Correct & Proceed: If the previous step failed or produced an unexpected result, analyze the error and formulate a new plan to correct it. If it was successful, proceed to the next step in your plan.

5. Completion: Once you have verified that the entire task is complete and the solution is working, output TASK_COMPLETE to signal completion."""


async def update_tesslate_agent():
    """Update the Tesslate Agent to be open source with full system prompt."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as db:
        print("\n=== Updating Tesslate Agent ===\n")

        # Find the Tesslate Agent
        result = await db.execute(
            select(MarketplaceAgent).where(MarketplaceAgent.slug == 'tesslate-agent')
        )
        agent = result.scalar_one_or_none()

        if not agent:
            print("❌ Tesslate Agent not found! Creating new one...")
            agent = MarketplaceAgent(
                name="Tesslate Agent",
                slug="tesslate-agent",
                category="fullstack",
                item_type="agent",
                agent_type="IterativeAgent",
                mode="agent",
                model="gpt-4o-mini",
                icon="🤖",
                pricing_type="free",
                price=0,
                is_featured=True,
                is_active=True
            )
            db.add(agent)

        # Update agent properties
        print(f"Updating agent: {agent.name} (ID: {agent.id})")

        agent.description = "The official Tesslate autonomous software engineering agent"
        agent.long_description = """The official open source Tesslate Agent - a world-class autonomous AI software engineering agent that follows a clear Plan-Act-Observe-Verify methodology. This agent has deep expertise in system administration, operating system principles, network protocols, and software development across multiple languages.

This is the reference implementation that showcases Tesslate's core methodology and tool usage patterns. You can customize the model, fork it, or use it as a template for your own agents.

**Methodology:**
1. **Analyze & Plan**: Assess requirements and formulate step-by-step plans
2. **Execute**: Use tools to accomplish goals
3. **Observe & Verify**: Analyze outputs and verify success
4. **Self-Correct & Proceed**: Fix errors or move to next step
5. **Completion**: Signal when task is complete

**Features:**
- Comprehensive file operations (read, write, edit)
- Command execution with security controls
- Git operations and version control
- Multi-step task planning and execution
- Self-correction and error recovery"""

        agent.system_prompt = TESSLATE_AGENT_SYSTEM_PROMPT
        agent.source_type = "open"  # Make it open source
        agent.is_forkable = True     # Allow forking
        agent.features = [
            "Autonomous coding",
            "Multi-step planning",
            "File operations",
            "Command execution",
            "Git integration",
            "Self-correction"
        ]
        agent.required_models = ["gpt-4o-mini"]
        agent.tags = ["official", "autonomous", "fullstack", "open-source", "methodology"]

        print("✓ Updated system_prompt")
        print("✓ Set source_type='open'")
        print("✓ Set is_forkable=True")
        print("✓ Updated description and features")

        await db.commit()
        await db.refresh(agent)

        print(f"\n✅ Successfully updated Tesslate Agent (ID: {agent.id})")
        print(f"\nAgent details:")
        print(f"  Name: {agent.name}")
        print(f"  Slug: {agent.slug}")
        print(f"  Source Type: {agent.source_type}")
        print(f"  Is Forkable: {agent.is_forkable}")
        print(f"  Agent Type: {agent.agent_type}")
        print(f"  Model: {agent.model}")
        print(f"  System Prompt Length: {len(agent.system_prompt)} characters")
        print()


if __name__ == "__main__":
    asyncio.run(update_tesslate_agent())
