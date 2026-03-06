"""
Verification Script for Agent Abstraction System

This script verifies that:
1. The agent factory can create instances from database models
2. Each agent type can be instantiated correctly
3. Agent tools are properly scoped
4. The unified system works end-to-end

Run with: python scripts/utilities/verify_agent_abstraction.py
"""

import asyncio
import sys
import os

# Add parent directories to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from orchestrator.app.models import MarketplaceAgent
from orchestrator.app.agent.factory import create_agent_from_db_model, get_available_agent_types
from orchestrator.app.agent import StreamAgent, IterativeAgent, AbstractAgent
from orchestrator.app.config import get_settings


class Colors:
    """ANSI color codes for terminal output"""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


def print_header(text):
    """Print a formatted header"""
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'=' * 80}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{text:^80}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'=' * 80}{Colors.RESET}\n")


def print_success(text):
    """Print success message"""
    print(f"{Colors.GREEN}✓ {text}{Colors.RESET}")


def print_error(text):
    """Print error message"""
    print(f"{Colors.RED}✗ {text}{Colors.RESET}")


def print_warning(text):
    """Print warning message"""
    print(f"{Colors.YELLOW}⚠ {text}{Colors.RESET}")


def print_info(text):
    """Print info message"""
    print(f"{Colors.BLUE}ℹ {text}{Colors.RESET}")


async def test_factory_registration():
    """Test 1: Verify factory has registered agent types"""
    print_header("Test 1: Factory Agent Type Registration")

    available_types = get_available_agent_types()
    print_info(f"Available agent types: {', '.join(available_types)}")

    expected_types = ['StreamAgent', 'IterativeAgent']
    all_registered = all(t in available_types for t in expected_types)

    if all_registered:
        print_success(f"All expected agent types are registered")
        return True
    else:
        missing = [t for t in expected_types if t not in available_types]
        print_error(f"Missing agent types: {', '.join(missing)}")
        return False


async def test_database_agents(db: AsyncSession):
    """Test 2: Verify database agents can be loaded"""
    print_header("Test 2: Database Agent Loading")

    result = await db.execute(select(MarketplaceAgent).where(MarketplaceAgent.is_active == True))
    agents = result.scalars().all()

    if not agents:
        print_warning("No active agents found in database")
        print_info("This is expected if you haven't run the migration yet")
        print_info("Run: python scripts/migrations/add_agent_type_and_tools.py")
        return False

    print_info(f"Found {len(agents)} active agents in database\n")

    success_count = 0
    for agent_model in agents:
        print(f"Testing agent: {Colors.BOLD}{agent_model.name}{Colors.RESET}")
        print(f"  Slug: {agent_model.slug}")
        print(f"  Type: {agent_model.agent_type}")
        print(f"  Mode: {agent_model.mode} (deprecated)")
        print(f"  Tools: {agent_model.tools if agent_model.tools else 'None (uses all tools)'}")

        try:
            # Create instance (without model adapter for now)
            instance = await create_agent_from_db_model(agent_model, model_adapter=None)

            # Verify instance
            if not isinstance(instance, AbstractAgent):
                print_error(f"  Instance is not an AbstractAgent!")
                continue

            print_success(f"  Created {instance.__class__.__name__} instance")

            # Verify tools
            if instance.tools:
                tool_count = len(instance.tools._tools)
                print_info(f"  Has access to {tool_count} tools")

                # Show tool names
                tool_names = list(instance.tools._tools.keys())
                if tool_names:
                    print(f"    Tools: {', '.join(tool_names[:5])}")
                    if len(tool_names) > 5:
                        print(f"    ... and {len(tool_names) - 5} more")
            else:
                print_info(f"  No tool registry (expected for StreamAgent)")

            success_count += 1
            print()

        except Exception as e:
            print_error(f"  Failed to create instance: {e}")
            import traceback
            traceback.print_exc()
            print()

    if success_count == len(agents):
        print_success(f"All {len(agents)} agents created successfully")
        return True
    else:
        print_error(f"Only {success_count}/{len(agents)} agents created successfully")
        return False


async def test_scoped_tools():
    """Test 3: Verify scoped tool registries work"""
    print_header("Test 3: Scoped Tool Registries")

    from orchestrator.app.agent.tools.registry import create_scoped_tool_registry, get_tool_registry

    # Get global registry
    global_registry = get_tool_registry()
    global_tool_count = len(global_registry._tools)
    print_info(f"Global registry has {global_tool_count} tools")

    # Create scoped registry
    scoped_tools = ["read_file", "write_file", "list_files"]
    print_info(f"Creating scoped registry with: {', '.join(scoped_tools)}")

    try:
        scoped_registry = create_scoped_tool_registry(scoped_tools)
        scoped_tool_count = len(scoped_registry._tools)

        if scoped_tool_count == len(scoped_tools):
            print_success(f"Scoped registry created with {scoped_tool_count} tools")
            return True
        else:
            print_error(f"Expected {len(scoped_tools)} tools, got {scoped_tool_count}")
            return False

    except Exception as e:
        print_error(f"Failed to create scoped registry: {e}")
        return False


async def test_agent_instantiation():
    """Test 4: Test direct agent instantiation"""
    print_header("Test 4: Direct Agent Instantiation")

    from orchestrator.app.agent.tools.registry import create_scoped_tool_registry

    test_prompt = "You are a test agent"
    tools = create_scoped_tool_registry(["read_file", "write_file"])

    try:
        # Test StreamAgent
        print_info("Testing StreamAgent...")
        stream_agent = StreamAgent(system_prompt=test_prompt, tools=None)
        if isinstance(stream_agent, AbstractAgent):
            print_success("StreamAgent instantiated correctly")
        else:
            print_error("StreamAgent is not an AbstractAgent!")
            return False

        # Test IterativeAgent
        print_info("Testing IterativeAgent...")
        iterative_agent = IterativeAgent(system_prompt=test_prompt, tools=tools)
        if isinstance(iterative_agent, AbstractAgent):
            print_success("IterativeAgent instantiated correctly")
        else:
            print_error("IterativeAgent is not an AbstractAgent!")
            return False

        print_success("All agent types can be instantiated")
        return True

    except Exception as e:
        print_error(f"Failed to instantiate agents: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all verification tests"""
    print_header("Agent Abstraction System Verification")
    print(f"This script verifies the modular agent system is working correctly.\n")

    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    results = []

    # Test 1: Factory registration
    results.append(await test_factory_registration())

    # Test 2: Database agents (requires DB connection)
    async with AsyncSessionLocal() as db:
        results.append(await test_database_agents(db))

    # Test 3: Scoped tools
    results.append(await test_scoped_tools())

    # Test 4: Agent instantiation
    results.append(await test_agent_instantiation())

    # Summary
    print_header("Verification Summary")

    passed = sum(results)
    total = len(results)

    if passed == total:
        print_success(f"All {total} tests passed! ✨")
        print()
        print(f"{Colors.GREEN}The agent abstraction system is working correctly.{Colors.RESET}")
        print(f"{Colors.GREEN}You can now:{Colors.RESET}")
        print(f"  1. Run the migration: python scripts/migrations/add_agent_type_and_tools.py")
        print(f"  2. Start the application and test agent switching")
        print(f"  3. Create new agent types by extending AbstractAgent")
        print()
        return 0
    else:
        failed = total - passed
        print_error(f"{failed}/{total} tests failed")
        print()
        print(f"{Colors.RED}Please fix the issues above before proceeding.{Colors.RESET}")
        print()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
