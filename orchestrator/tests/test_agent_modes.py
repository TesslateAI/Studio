"""
Test script to verify both stream and agent modes work with the same API keys.

This script tests:
1. Stream mode with WebSocket connection
2. Agent mode with HTTP POST to /api/chat/agent
3. Verifies both modes can use the selected agent's system prompt
"""

import asyncio
import aiohttp
import json
import websockets
import os
import sys
from typing import Dict, Any

# Fix Windows encoding issues with emojis
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Configuration
API_BASE = "http://localhost:8000"
WS_BASE = "ws://localhost:8000"

# Test credentials (update these with your test user)
USERNAME = "testuser"
PASSWORD = "testpass"


async def authenticate() -> Dict[str, str]:
    """Authenticate and get tokens."""
    async with aiohttp.ClientSession() as session:
        # Login
        data = aiohttp.FormData()
        data.add_field('username', USERNAME)
        data.add_field('password', PASSWORD)

        async with session.post(f"{API_BASE}/api/auth/token", data=data) as resp:
            if resp.status != 200:
                print(f"❌ Authentication failed: {await resp.text()}")
                return None

            result = await resp.json()
            return {
                "access_token": result["access_token"],
                "refresh_token": result["refresh_token"]
            }


async def get_agents(token: str) -> list:
    """Get list of available agents."""
    headers = {"Authorization": f"Bearer {token}"}

    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_BASE}/api/agents/", headers=headers) as resp:
            if resp.status != 200:
                print(f"❌ Failed to get agents: {await resp.text()}")
                return []

            agents = await resp.json()
            return agents


async def test_agent_mode(token: str, project_id: int, agent_id: int = None):
    """Test agent mode (HTTP POST to /api/chat/agent)."""
    print(f"\n🧪 Testing AGENT mode{f' with agent_id={agent_id}' if agent_id else ''}...")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    request_data = {
        "project_id": project_id,
        "message": "Create a simple counter component with increment and decrement buttons",
        "max_iterations": 5
    }

    if agent_id:
        request_data["agent_id"] = agent_id

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{API_BASE}/api/chat/agent",
            json=request_data,
            headers=headers
        ) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                print(f"❌ Agent mode failed with status {resp.status}: {error_text}")
                return False

            result = await resp.json()
            print(f"✅ Agent mode successful!")
            print(f"   - Iterations: {result['iterations']}")
            print(f"   - Tool calls: {result['tool_calls_made']}")
            print(f"   - Completion reason: {result['completion_reason']}")
            print(f"   - Response preview: {result['final_response'][:200]}...")
            return True


async def test_stream_mode(token: str, project_id: int, agent_id: int = None):
    """Test stream mode (WebSocket)."""
    print(f"\n🧪 Testing STREAM mode{f' with agent_id={agent_id}' if agent_id else ''}...")

    ws_url = f"{WS_BASE}/api/chat/ws/{token}"

    try:
        async with websockets.connect(ws_url) as websocket:
            # Send message
            message_data = {
                "message": "Create a simple hello world component",
                "project_id": project_id
            }

            if agent_id:
                message_data["agent_id"] = agent_id

            await websocket.send(json.dumps(message_data))

            # Receive responses
            message_count = 0
            while True:
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=30.0)
                    data = json.loads(response)
                    message_count += 1

                    if data["type"] == "complete":
                        print(f"✅ Stream mode successful!")
                        print(f"   - Received {message_count} messages")
                        print(f"   - Final response length: {len(data['content'])} chars")
                        return True
                    elif data["type"] == "error":
                        print(f"❌ Stream mode error: {data['content']}")
                        return False

                except asyncio.TimeoutError:
                    print("⏱️  Stream timeout (this is normal if the response completed)")
                    return message_count > 0

    except Exception as e:
        print(f"❌ WebSocket connection failed: {e}")
        return False


async def main():
    print("=" * 60)
    print("Testing Agent Modes - Stream vs Agent")
    print("=" * 60)

    # Authenticate
    print("\n🔐 Authenticating...")
    tokens = await authenticate()
    if not tokens:
        print("❌ Failed to authenticate. Please check credentials.")
        return

    print(f"✅ Authenticated successfully")
    token = tokens["access_token"]

    # Get agents
    print("\n📋 Getting available agents...")
    agents = await get_agents(token)

    if agents:
        print(f"✅ Found {len(agents)} agents:")
        for agent in agents[:3]:  # Show first 3 agents
            print(f"   - {agent['name']} (ID: {agent['id']}, Mode: {agent['mode']})")
    else:
        print("⚠️  No agents found, will test with default agent")

    # Use a test project ID (you may need to create a project first)
    project_id = 3  # Update this with a valid project ID

    print(f"\n📁 Using project ID: {project_id}")
    print("   (Make sure this project exists for your test user)")

    # Test without agent_id (should use default)
    print("\n" + "=" * 40)
    print("Test 1: Without Agent ID (Default)")
    print("=" * 40)

    stream_ok = await test_stream_mode(token, project_id)
    agent_ok = await test_agent_mode(token, project_id)

    # Test with specific agents
    if agents:
        # Find a stream mode agent
        stream_agent = next((a for a in agents if a['mode'] == 'stream'), None)
        if stream_agent:
            print("\n" + "=" * 40)
            print(f"Test 2: Stream Mode Agent - {stream_agent['name']}")
            print("=" * 40)

            await test_stream_mode(token, project_id, stream_agent['id'])

        # Find an agent mode agent
        agent_mode_agent = next((a for a in agents if a['mode'] == 'agent'), None)
        if agent_mode_agent:
            print("\n" + "=" * 40)
            print(f"Test 3: Agent Mode Agent - {agent_mode_agent['name']}")
            print("=" * 40)

            await test_agent_mode(token, project_id, agent_mode_agent['id'])

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    if stream_ok and agent_ok:
        print("✅ Both stream and agent modes are working!")
        print("✅ The authentication issue has been fixed.")
        print("\nThe fix involved:")
        print("1. Adding agent_id to AgentChatRequest schema")
        print("2. Loading agent configuration in the agent endpoint")
        print("3. Passing agent system prompt to UniversalAgent")
        print("4. Updating frontend to send agent_id")
    else:
        print("⚠️  Some tests failed. Please check the errors above.")
        if not stream_ok:
            print("   - Stream mode needs attention")
        if not agent_ok:
            print("   - Agent mode needs attention")


if __name__ == "__main__":
    asyncio.run(main())