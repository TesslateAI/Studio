#!/usr/bin/env python3
"""
Manual hot reload test - starts container and lets you manually test hot reload
"""

import sys
import os
import time
import asyncio
import subprocess
import requests
from pathlib import Path

# Add the backend to Python path
backend_path = Path(__file__).parent.parent / "builder" / "backend"
sys.path.insert(0, str(backend_path))

from app.dev_server_manager import DevContainerManager

async def manual_test():
    manager = DevContainerManager()
    test_project_path = str(Path(__file__).parent)
    test_project_id = "manual-test"
    
    print("=== MANUAL HOT RELOAD TEST ===")
    
    try:
        # Start container
        print("Starting container...")
        port = await manager.start_container(test_project_path, test_project_id)
        container_url = f"http://127.0.0.1:{port}"
        print(f"Container started: {container_url}")
        
        # Wait for it to be ready
        print("Waiting for server to be ready...")
        time.sleep(10)
        
        # Test initial access
        try:
            response = requests.get(container_url, timeout=10)
            print(f"Initial access: {response.status_code}")
        except Exception as e:
            print(f"Initial access failed: {e}")
            
        print(f"\n=== HOT RELOAD TEST ===")
        print(f"1. Open your browser and go to: {container_url}")
        print("2. You should see a React app with 'New Project!' header")
        print("3. This script will modify App.jsx in 10 seconds...")
        print("4. Watch for changes in your browser!")
        
        time.sleep(10)
        
        # Modify App.jsx
        app_jsx_path = os.path.join(test_project_path, "src", "App.jsx")
        print(f"Modifying {app_jsx_path}...")
        
        with open(app_jsx_path, 'r', encoding='utf-8') as f:
            original_content = f.read()
        
        test_marker = f"HOT RELOAD TEST SUCCESSFUL - {int(time.time())}"
        modified_content = original_content.replace(
            "New Project!",
            test_marker
        )
        
        with open(app_jsx_path, 'w', encoding='utf-8') as f:
            f.write(modified_content)
        
        print(f"Modified App.jsx - header should now show: {test_marker}")
        print("Check your browser - the changes should appear within 2-3 seconds!")
        
        print("\nPress Enter when you've verified hot reload works (or doesn't work)...")
        input()
        
        # Restore original content
        print("Restoring original App.jsx...")
        with open(app_jsx_path, 'w', encoding='utf-8') as f:
            f.write(original_content)
        
        print("Original content restored!")
        print("Press Enter to stop the container...")
        input()
        
        # Stop container
        await manager.stop_container(test_project_id)
        print("Container stopped")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(manual_test())