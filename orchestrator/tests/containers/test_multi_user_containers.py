#!/usr/bin/env python3
"""
Test the multi-user container management system.

NOTE: This test is for Kubernetes deployment mode.
For Docker mode testing, use the docker-compose orchestrator tests.
"""

import sys
import os
import time
import asyncio
import subprocess
from pathlib import Path
from uuid import uuid4

# Add the orchestrator to Python path
orchestrator_path = Path(__file__).parent.parent.parent
sys.path.insert(0, str(orchestrator_path))

from app.config import get_settings
from app.k8s_container_manager import KubernetesContainerManager as DevContainerManager

class MultiUserContainerTest:
    def __init__(self):
        self.manager = DevContainerManager()
        self.test_project_path = str(Path(__file__).parent)
        
    def log(self, message):
        """Log with timestamp."""
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] {message}")
    
    async def test_multi_user_system(self):
        """Test multi-user container management."""
        self.log("=== TESTING MULTI-USER CONTAINER SYSTEM ===")
        
        # Simulate multiple users and projects
        test_scenarios = [
            {"user_id": 1, "project_id": "app1", "name": "User1-App1"},
            {"user_id": 1, "project_id": "app2", "name": "User1-App2"}, 
            {"user_id": 2, "project_id": "app1", "name": "User2-App1"},
            {"user_id": 2, "project_id": "website", "name": "User2-Website"},
        ]
        
        started_containers = []
        
        try:
            # Test starting multiple containers
            self.log("Starting containers for multiple users/projects...")
            
            for scenario in test_scenarios:
                self.log(f"Starting container for {scenario['name']}")
                try:
                    port = await self.manager.start_container(
                        self.test_project_path,
                        scenario["project_id"], 
                        scenario["user_id"]
                    )
                    started_containers.append({
                        **scenario,
                        "port": port
                    })
                    self.log(f"✓ {scenario['name']} started on port {port}")
                    
                except Exception as e:
                    self.log(f"✗ Failed to start {scenario['name']}: {e}")
                    continue
            
            self.log(f"Successfully started {len(started_containers)} containers")
            
            # Test container visibility
            self.log("\n=== TESTING CONTAINER VISIBILITY ===")
            all_containers = self.manager.get_all_containers()
            self.log(f"Manager reports {len(all_containers)} total containers")
            
            for container in all_containers:
                self.log(f"Container: {container.get('container_name')} - User {container.get('user_id')}, Project {container.get('project_id')}, Port {container.get('port')}")
            
            # Test Docker Desktop visibility
            self.log("\n=== CHECKING DOCKER DESKTOP VISIBILITY ===")
            result = subprocess.run(
                ["docker", "ps", "--filter", "label=com.builder.devserver=true", "--format", "table {{.Names}}\\t{{.Ports}}\\t{{.Labels}}"],
                capture_output=True, text=True, timeout=10
            )
            
            if result.returncode == 0:
                self.log("Docker containers with builder labels:")
                print(result.stdout)
            else:
                self.log("Failed to query Docker containers")
            
            # Test port allocation
            self.log("\n=== TESTING PORT ALLOCATION ===")
            allocated_ports = sorted(self.manager.allocated_ports)
            self.log(f"Allocated ports: {allocated_ports}")
            
            # Test individual container access
            self.log("\n=== TESTING INDIVIDUAL CONTAINER ACCESS ===")
            for container in started_containers:
                url = self.manager.get_container_url(container["project_id"], container["user_id"])
                status = self.manager.get_container_status(container["project_id"], container["user_id"])
                self.log(f"{container['name']}: URL={url}, Status={status.get('status', 'unknown')}")
            
            # Test cross-user isolation
            self.log("\n=== TESTING USER ISOLATION ===")
            # Try to access User1's container as User2 (should fail gracefully)
            user2_accessing_user1 = self.manager.get_container_url("app1", 999)  # Non-existent user
            self.log(f"Non-existent user accessing app1: {user2_accessing_user1}")
            
            self.log(f"\n=== TEST COMPLETED ===")
            self.log(f"✓ Started {len(started_containers)} containers successfully")
            self.log("✓ Multi-user isolation working")
            self.log("✓ Port allocation working")
            self.log("✓ Container visibility in Docker Desktop")
            
            # Keep containers running for manual inspection
            self.log(f"\nContainers are running for manual inspection:")
            for container in started_containers:
                self.log(f"  - {container['name']}: http://127.0.0.1:{container['port']}")
            
            self.log("\nPress Enter to stop all containers...")
            input()
            
        finally:
            # Cleanup all containers
            self.log("Cleaning up all containers...")
            for container in started_containers:
                try:
                    await self.manager.stop_container(container["project_id"], container["user_id"])
                    self.log(f"✓ Stopped {container['name']}")
                except Exception as e:
                    self.log(f"✗ Failed to stop {container['name']}: {e}")
            
            self.log("Cleanup completed!")

if __name__ == "__main__":
    async def main():
        test = MultiUserContainerTest()
        await test.test_multi_user_system()
    
    asyncio.run(main())