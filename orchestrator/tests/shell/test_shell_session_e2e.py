"""
End-to-end test for shell session API with Docker.
Tests the complete PTY broker implementation.
"""

import asyncio
import httpx
import time

BASE_URL = "http://localhost:8000"
TEST_USER = "shelltest456"
TEST_PASS = "testpass123"

async def test_shell_session():
    """Test complete shell session workflow."""

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Step 1: Register user
        print("\n1. Registering test user...")
        register_response = await client.post(
            f"{BASE_URL}/api/auth/register",
            json={
                "name": "Test User",
                "username": TEST_USER,
                "email": "test@example.com",
                "password": TEST_PASS
            }
        )
        if register_response.status_code == 200:
            print(f"  ✅ User registered")
        elif register_response.status_code == 400 and "already exists" in register_response.text:
            print(f"  ⚠️  User already exists, continuing...")
        else:
            print(f"  ❌ Registration failed: {register_response.status_code} - {register_response.text}")
            return

        # Step 2: Login
        print("\n2. Logging in...")
        login_response = await client.post(
            f"{BASE_URL}/api/auth/login",
            data={"username": TEST_USER, "password": TEST_PASS}
        )
        if login_response.status_code != 200:
            print(f"  ❌ Login failed: {login_response.status_code} - {login_response.text}")
            return

        tokens = login_response.json()
        access_token = tokens["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}
        print(f"  ✅ Logged in successfully")

        # Step 3: Create a project (or find existing)
        print("\n3. Getting/creating project...")
        projects_response = await client.get(
            f"{BASE_URL}/api/projects",
            headers=headers
        )

        if projects_response.status_code != 200:
            print(f"  ❌ Failed to get projects: {projects_response.status_code}")
            return

        projects = projects_response.json()
        if projects:
            project_id = projects[0]["id"]
            print(f"  ✅ Using existing project ID: {project_id}")
        else:
            create_response = await client.post(
                f"{BASE_URL}/api/projects",
                json={"name": "Test Project"},
                headers=headers
            )
            if create_response.status_code != 200:
                print(f"  ❌ Failed to create project: {create_response.status_code}")
                return
            project_id = create_response.json()["id"]
            print(f"  ✅ Created project ID: {project_id}")

        # Wait for container to be ready
        print("\n4. Waiting for container to be ready...")
        await asyncio.sleep(3)

        # Step 4: Create shell session
        print("\n5. Creating shell session...")
        session_response = await client.post(
            f"{BASE_URL}/api/shell/sessions",
            json={
                "project_id": project_id,
                "command": "/bin/sh",
                "cwd": "/app/project"
            },
            headers=headers
        )

        if session_response.status_code != 200:
            print(f"  ❌ Failed to create session: {session_response.status_code} - {session_response.text}")
            return

        session = session_response.json()
        session_id = session["session_id"]
        print(f"  ✅ Shell session created: {session_id}")
        print(f"     Status: {session['status']}")

        # Step 5: Write command to shell
        print("\n6. Executing command: echo 'Hello from PTY!'...")
        write_response = await client.post(
            f"{BASE_URL}/api/shell/sessions/{session_id}/write",
            json={"text": "echo 'Hello from PTY!'\n"},
            headers=headers
        )

        if write_response.status_code != 200:
            print(f"  ❌ Failed to write: {write_response.status_code} - {write_response.text}")
        else:
            print(f"  ✅ Command sent")

        # Step 6: Wait and read output
        print("\n7. Reading output...")
        await asyncio.sleep(2)  # Give command time to execute

        read_response = await client.get(
            f"{BASE_URL}/api/shell/sessions/{session_id}/output",
            headers=headers
        )

        if read_response.status_code != 200:
            print(f"  ❌ Failed to read: {read_response.status_code} - {read_response.text}")
        else:
            output_data = read_response.json()
            output = output_data.get("output", "")
            print(f"  ✅ Output received ({len(output)} bytes):")
            print(f"     {repr(output[:200])}")  # Show first 200 chars

            if "Hello from PTY!" in output:
                print(f"  🎉 SUCCESS: Found expected output!")

        # Step 7: List all sessions
        print("\n8. Listing all sessions...")
        list_response = await client.get(
            f"{BASE_URL}/api/shell/sessions",
            headers=headers
        )

        if list_response.status_code != 200:
            print(f"  ❌ Failed to list: {list_response.status_code}")
        else:
            sessions = list_response.json()
            print(f"  ✅ Found {len(sessions)} session(s)")
            for s in sessions:
                print(f"     - {s['session_id']}: {s['status']}")

        # Step 8: Get session details
        print("\n9. Getting session details...")
        details_response = await client.get(
            f"{BASE_URL}/api/shell/sessions/{session_id}",
            headers=headers
        )

        if details_response.status_code != 200:
            print(f"  ❌ Failed to get details: {details_response.status_code}")
        else:
            details = details_response.json()
            print(f"  ✅ Session details:")
            print(f"     Status: {details['status']}")
            print(f"     Created: {details['created_at']}")
            print(f"     Last activity: {details['last_activity_at']}")

        # Step 9: Close session
        print("\n10. Closing session...")
        close_response = await client.delete(
            f"{BASE_URL}/api/shell/sessions/{session_id}",
            headers=headers
        )

        if close_response.status_code != 200:
            print(f"  ❌ Failed to close: {close_response.status_code} - {close_response.text}")
        else:
            print(f"  ✅ Session closed successfully")

        print("\n" + "="*60)
        print("🎊 END-TO-END TEST COMPLETE!")
        print("="*60)


if __name__ == "__main__":
    asyncio.run(test_shell_session())
