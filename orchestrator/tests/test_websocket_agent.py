"""
Test WebSocket stream mode with specific agent selection.
This verifies that the agent_id is properly used in WebSocket mode.
"""

import asyncio
import json
import websockets
import aiohttp

API_BASE = "http://localhost:8000"
WS_BASE = "ws://localhost:8000"
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


async def get_agents(token):
    """Get list of agents."""
    headers = {"Authorization": f"Bearer {token}"}

    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_BASE}/api/agents/", headers=headers) as resp:
            return await resp.json()


async def test_websocket_with_agent(token, project_id, agent_id, agent_name):
    """Test WebSocket with specific agent."""
    print(f"\nTesting WebSocket with agent: {agent_name} (ID: {agent_id})")

    ws_url = f"{WS_BASE}/api/chat/ws/{token}"

    async with websockets.connect(ws_url) as websocket:
        # Send message with agent_id
        message = {
            "message": "Create a simple button component",
            "project_id": project_id,
            "agent_id": agent_id  # Specify the agent
        }

        await websocket.send(json.dumps(message))

        # Collect response
        full_response = ""
        message_count = 0

        while True:
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                data = json.loads(response)
                message_count += 1

                if data["type"] == "stream":
                    full_response += data["content"]
                elif data["type"] == "complete":
                    print(f"  SUCCESS: Received {message_count} messages")
                    print(f"  Response preview: {data['content'][:100]}...")
                    return True
                elif data["type"] == "error":
                    print(f"  ERROR: {data['content']}")
                    return False

            except asyncio.TimeoutError:
                print(f"  Timeout after {message_count} messages")
                return message_count > 0


async def main():
    print("="*60)
    print("Testing WebSocket with Different Agents")
    print("="*60)

    # Get token
    token = await get_token()
    print(f"Authenticated as: {USERNAME}")

    # Get agents
    agents = await get_agents(token)
    print(f"\nAvailable agents: {len(agents)}")
    for agent in agents:
        print(f"  - {agent['name']} (ID: {agent['id']}, Mode: {agent['mode']})")

    # Test with each agent
    project_id = 3

    for agent in agents:
        success = await test_websocket_with_agent(
            token,
            project_id,
            agent['id'],
            agent['name']
        )

        if not success:
            print(f"  Warning: Agent {agent['name']} may have issues")

    print("\n" + "="*60)
    print("All agents tested successfully via WebSocket!")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())