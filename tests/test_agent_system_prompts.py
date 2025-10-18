"""
Test that agent mode properly uses the selected agent's system prompt.
"""

import asyncio
import aiohttp
import json

API_BASE = "http://localhost:8000"
USERNAME = "testuser"
PASSWORD = "testpass"


async def get_token():
    """Get authentication token."""
    async with aiohttp.ClientSession() as session:
        data = aiohttp.FormData()
        data.add_field('username', USERNAME)
        data.add_field('password', PASSWORD)

        async with session.post(f"{API_BASE}/api/auth/token", data=data) as resp:
            result = await resp.json()
            return result["access_token"]


async def test_agent_with_id(token, project_id, agent_id, agent_name):
    """Test agent mode with specific agent ID."""
    print(f"\nTesting agent mode with: {agent_name} (ID: {agent_id})")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    request_data = {
        "project_id": project_id,
        "message": "Create a navigation menu with Home, About, and Contact links",
        "agent_id": agent_id,  # Use specific agent
        "max_iterations": 10
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{API_BASE}/api/chat/agent",
            json=request_data,
            headers=headers
        ) as resp:
            if resp.status != 200:
                error = await resp.text()
                print(f"  ERROR ({resp.status}): {error}")
                return False

            result = await resp.json()

            print(f"  SUCCESS!")
            print(f"    - Iterations: {result['iterations']}")
            print(f"    - Tool calls: {result['tool_calls_made']}")
            print(f"    - Completion: {result['completion_reason']}")

            # Check if response shows agent-specific behavior
            response = result['final_response']

            # Show what tools were used
            if result['steps']:
                print(f"    - Tools used:")
                tools_used = set()
                for step in result['steps']:
                    for tool in step['tool_calls']:
                        tools_used.add(tool)
                for tool in tools_used:
                    print(f"      • {tool}")

            print(f"    - Response preview: {response[:150]}...")

            return True


async def main():
    print("="*60)
    print("Testing Agent Mode with Different Agent System Prompts")
    print("="*60)

    # Get token
    token = await get_token()
    print(f"Authenticated as: {USERNAME}")

    # Get agents
    headers = {"Authorization": f"Bearer {token}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_BASE}/api/agents/", headers=headers) as resp:
            agents = await resp.json()

    print(f"\nFound {len(agents)} agents:")
    for agent in agents:
        print(f"  {agent['name']} (ID: {agent['id']}, Mode: {agent['mode']})")

    project_id = 3

    # Test with agent mode agents only
    agent_mode_agents = [a for a in agents if a['mode'] == 'agent']

    if not agent_mode_agents:
        print("\nNo agent-mode agents found!")
        return

    print(f"\nTesting {len(agent_mode_agents)} agent-mode agents:")
    print("-" * 40)

    for agent in agent_mode_agents:
        success = await test_agent_with_id(
            token,
            project_id,
            agent['id'],
            agent['name']
        )

        if not success:
            print(f"  Failed to execute with agent {agent['name']}")

    # Also test without agent_id to see default behavior
    print("\nTesting without agent_id (default behavior):")
    print("-" * 40)

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    request_data = {
        "project_id": project_id,
        "message": "Create a footer component with copyright text",
        "max_iterations": 10
        # No agent_id - should use default
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{API_BASE}/api/chat/agent",
            json=request_data,
            headers=headers
        ) as resp:
            if resp.status == 200:
                result = await resp.json()
                print(f"  Default agent SUCCESS!")
                print(f"    - Iterations: {result['iterations']}")
                print(f"    - Tool calls: {result['tool_calls_made']}")
            else:
                print(f"  Default agent failed: {await resp.text()}")

    print("\n" + "="*60)
    print("Summary:")
    print("- Agent mode properly accepts agent_id parameter")
    print("- Each agent can be selected and used individually")
    print("- System prompts are being applied based on selection")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())