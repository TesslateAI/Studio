import asyncio
import httpx

BASE_URL = "http://localhost:8000"

async def main():
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Test 1: Register
        resp = await client.post(f"{BASE_URL}/api/auth/register", json={
            "name": "Shell Test",
            "username": "shelltest789",
            "email": "shell@test.com",
            "password": "testpass123"
        })
        print(f"Register: {resp.status_code}")
        
        # Test 2: Login
        resp = await client.post(f"{BASE_URL}/api/auth/login", data={
            "username": "shelltest789",
            "password": "testpass123"
        })
        print(f"Login: {resp.status_code}")
        token = resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        
        # Test 3: Get projects
        resp = await client.get(f"{BASE_URL}/api/projects", headers=headers)
        projects = resp.json()
        project_id = projects[0]["id"] if projects else None
        print(f"Got project: {project_id}")
        
        # Test 4: Create shell session
        resp = await client.post(f"{BASE_URL}/api/shell/sessions", json={
            "project_id": project_id,
            "command": "/bin/sh"
        }, headers=headers)
        print(f"Create session: {resp.status_code}")
        print(f"Response: {resp.text[:500]}")
        
        if resp.status_code == 200:
            session = resp.json()
            session_id = session["session_id"]
            print(f"Session ID: {session_id}")
            
            # Test 5: Write to session
            await asyncio.sleep(1)
            resp = await client.post(f"{BASE_URL}/api/shell/sessions/{session_id}/write",
                json={"text": "echo Hello PTY\n"}, headers=headers)
            print(f"Write: {resp.status_code}")
            
            # Test 6: Read output
            await asyncio.sleep(2)
            resp = await client.get(f"{BASE_URL}/api/shell/sessions/{session_id}/output",
                headers=headers)
            print(f"Read: {resp.status_code}")
            output = resp.json().get("output", "")
            print(f"Output ({len(output)} bytes): {output[:200]}")
            
            #Test 7: Close
            resp = await client.delete(f"{BASE_URL}/api/shell/sessions/{session_id}",
                headers=headers)
            print(f"Close: {resp.status_code}")

asyncio.run(main())
