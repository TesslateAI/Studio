#!/usr/bin/env python3
"""
Debug container startup to see what's going wrong with the preview.
"""

import sys
import os
import time
import asyncio
import subprocess
import requests
from pathlib import Path

# Add the backend to Python path so we can import the dev container manager
backend_path = Path(__file__).parent.parent / "builder" / "backend"
sys.path.insert(0, str(backend_path))

from app.dev_server_manager import DevContainerManager

async def debug_container():
    manager = DevContainerManager()
    test_project_path = str(Path(__file__).parent)
    test_project_id = "debug-test"
    
    print("=== DEBUGGING CONTAINER STARTUP ===")
    
    try:
        # Start container
        print("Starting container...")
        port = await manager.start_container(test_project_path, test_project_id)
        container_url = f"http://127.0.0.1:{port}"
        print(f"Container started on: {container_url}")
        
        # Get container logs
        container_name = f"devserver-{test_project_id}"
        print("\n=== Container Logs ===")
        result = subprocess.run(
            ["docker", "logs", container_name],
            capture_output=True,
            text=True,
            timeout=30
        )
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)
        
        # Check container processes
        print("\n=== Container Processes ===")
        result = subprocess.run(
            ["docker", "exec", container_name, "ps", "aux"],
            capture_output=True,
            text=True,
            timeout=10
        )
        print(result.stdout)
        
        # Check if npm dev server is actually running
        print("\n=== Port Status Inside Container ===")
        result = subprocess.run(
            ["docker", "exec", container_name, "netstat", "-tlnp"],
            capture_output=True,
            text=True,
            timeout=10
        )
        print(result.stdout)
        
        # Try to access preview
        print("\n=== Testing Preview Access ===")
        for attempt in range(10):
            try:
                response = requests.get(container_url, timeout=5)
                print(f"Attempt {attempt + 1}: Status {response.status_code}")
                if response.status_code == 200:
                    print("SUCCESS! Preview is accessible")
                    print("Response preview:", response.text[:200] + "..." if len(response.text) > 200 else response.text)
                    break
            except Exception as e:
                print(f"Attempt {attempt + 1}: Failed - {e}")
            
            time.sleep(3)
        
        # Keep container running for manual inspection
        print(f"\nContainer is running at: {container_url}")
        print("Press Enter to stop container and exit...")
        input()
        
        # Stop container
        await manager.stop_container(test_project_id)
        print("Container stopped")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(debug_container())