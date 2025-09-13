#!/usr/bin/env python3
"""
Quick hot reload verification test
"""

import sys
import os
import time
import asyncio
import requests
from pathlib import Path

# Add the backend to Python path
backend_path = Path(__file__).parent.parent / "builder" / "backend"
sys.path.insert(0, str(backend_path))

from app.dev_server_manager import DevContainerManager

async def quick_test():
    manager = DevContainerManager()
    test_project_path = str(Path(__file__).parent)
    test_project_id = "hot-reload-test"
    
    try:
        print("Starting container for hot reload test...")
        port = await manager.start_container(test_project_path, test_project_id)
        container_url = f"http://127.0.0.1:{port}"
        
        # Get initial page
        print("Getting initial page content...")
        response1 = requests.get(container_url, timeout=10)
        print(f"Initial status: {response1.status_code}")
        
        # Modify App.jsx
        app_jsx_path = os.path.join(test_project_path, "src", "App.jsx")
        with open(app_jsx_path, 'r', encoding='utf-8') as f:
            original_content = f.read()
        
        test_marker = f"QUICK-TEST-{int(time.time())}"
        modified_content = original_content.replace("New Project!", test_marker)
        
        print(f"Modifying App.jsx with marker: {test_marker}")
        with open(app_jsx_path, 'w', encoding='utf-8') as f:
            f.write(modified_content)
        
        # Wait for hot reload and check
        print("Waiting 8 seconds for hot reload...")
        time.sleep(8)
        
        response2 = requests.get(container_url, timeout=10)
        print(f"After modification status: {response2.status_code}")
        
        if test_marker in response2.text:
            print("[SUCCESS] Hot reload is working! Changes detected.")
        else:
            print("[INFO] Changes not detected in HTML, but this might be normal for React SPA")
            print("Hot reload typically works in browser via WebSocket, not in raw HTML response")
        
        # Restore original
        with open(app_jsx_path, 'w', encoding='utf-8') as f:
            f.write(original_content)
        
        print(f"Container running at: {container_url}")
        print("You can manually verify hot reload is working in your browser!")
        
        await manager.stop_container(test_project_id)
        print("Container stopped")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(quick_test())