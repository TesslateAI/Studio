#!/usr/bin/env python3
"""
Comprehensive test of the container development system.
Tests container start/stop, preview functionality, and hot reload.

NOTE: This test now supports Kubernetes deployment mode.
Some Docker-specific tests (base image build) are skipped in K8s mode.
"""

import sys
import os
import time
import asyncio
import subprocess
import requests
from pathlib import Path
from uuid import uuid4

# Add the orchestrator to Python path
orchestrator_path = Path(__file__).parent.parent.parent
sys.path.insert(0, str(orchestrator_path))

from app.config import get_settings
from app.k8s_container_manager import KubernetesContainerManager as DevContainerManager

class ContainerSystemTest:
    def __init__(self):
        self.manager = DevContainerManager()
        self.test_project_path = str(Path(__file__).parent)
        self.test_project_id = "test-project"
        self.container_url = None
        
    def log(self, message):
        """Log with timestamp."""
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] {message}")
    
    def test_docker_availability(self):
        """Test 1: Check Docker is available."""
        self.log("=== TEST 1: Docker Availability ===")
        available = self.manager._check_docker_available()
        if available:
            self.log("[OK] Docker is available and running")
            return True
        else:
            self.log("[ERROR] Docker is not available - please start Docker Desktop")
            return False
    
    def test_base_image_build(self):
        """Test 2: Build base Docker image."""
        self.log("=== TEST 2: Base Image Build ===")
        start_time = time.time()
        
        # Force a fresh build for testing
        self.log("Removing any existing base image for clean test...")
        try:
            subprocess.run(
                ["docker", "rmi", "-f", self.manager.base_image_name],
                capture_output=True,
                timeout=30
            )
        except Exception:
            pass
        
        self.manager._base_image_ready = False
        
        # Build base image
        success = self.manager._ensure_base_image_exists()
        build_time = time.time() - start_time
        
        if success:
            self.log(f"[OK] Base image built successfully in {build_time:.1f} seconds")
            return True
        else:
            self.log("[ERROR] Base image build failed")
            return False
    
    async def test_container_start_stop(self):
        """Test 3: Start and stop container."""
        self.log("=== TEST 3: Container Start/Stop ===")
        
        try:
            # Start container
            self.log("Starting development container...")
            start_time = time.time()
            port = await self.manager.start_container(self.test_project_path, self.test_project_id)
            start_time = time.time() - start_time
            
            self.container_url = f"http://127.0.0.1:{port}"
            self.log(f"[OK] Container started in {start_time:.1f} seconds on port {port}")
            
            # Check container is running
            status = self.manager.get_container_status(self.test_project_id)
            if status.get('running'):
                self.log("[OK] Container is running")
            else:
                self.log("[ERROR] Container is not running")
                return False
            
            return True
            
        except Exception as e:
            self.log(f"[ERROR] Container start failed: {e}")
            return False
    
    def test_preview_accessibility(self):
        """Test 4: Test if preview is accessible."""
        self.log("=== TEST 4: Preview Accessibility ===")
        
        if not self.container_url:
            self.log("[ERROR] No container URL available")
            return False
        
        # Wait a bit for the dev server to fully start
        self.log("Waiting for dev server to be ready...")
        max_attempts = 30
        
        for attempt in range(max_attempts):
            try:
                response = requests.get(self.container_url, timeout=3)
                if response.status_code == 200:
                    self.log(f"[OK] Preview accessible at {self.container_url}")
                    self.log(f"[OK] Response status: {response.status_code}")
                    self.log(f"[OK] Response contains HTML: {'<!DOCTYPE html>' in response.text or '<html' in response.text}")
                    return True
            except requests.exceptions.RequestException:
                pass
            
            time.sleep(2)
            self.log(f"Attempt {attempt + 1}/{max_attempts}...")
        
        self.log("[ERROR] Preview not accessible after waiting")
        return False
    
    def test_hot_reload(self):
        """Test 5: Test hot reload by editing App.jsx."""
        self.log("=== TEST 5: Hot Reload Test ===")
        
        app_jsx_path = os.path.join(self.test_project_path, "src", "App.jsx")
        
        if not os.path.exists(app_jsx_path):
            self.log(f"[ERROR] App.jsx not found at {app_jsx_path}")
            return False
        
        # Read original content
        with open(app_jsx_path, 'r', encoding='utf-8') as f:
            original_content = f.read()
        
        # Modify the content
        test_marker = "HOT RELOAD TEST - " + str(int(time.time()))
        modified_content = original_content.replace(
            "Start building something amazing.",
            f"Start building something amazing. {test_marker}"
        )
        
        try:
            # Write modified content
            self.log("Modifying App.jsx for hot reload test...")
            with open(app_jsx_path, 'w', encoding='utf-8') as f:
                f.write(modified_content)
            
            # Wait a bit for hot reload to kick in
            self.log("Waiting for hot reload...")
            time.sleep(5)
            
            # Check if changes are reflected
            try:
                response = requests.get(self.container_url, timeout=5)
                if test_marker in response.text:
                    self.log("[OK] Hot reload working - changes detected in browser")
                    success = True
                else:
                    self.log("[ERROR] Hot reload not working - changes not detected")
                    success = False
            except requests.exceptions.RequestException as e:
                self.log(f"[ERROR] Failed to check hot reload: {e}")
                success = False
            
            # Restore original content
            self.log("Restoring original App.jsx...")
            with open(app_jsx_path, 'w', encoding='utf-8') as f:
                f.write(original_content)
            
            return success
            
        except Exception as e:
            self.log(f"[ERROR] Hot reload test failed: {e}")
            # Try to restore original content
            try:
                with open(app_jsx_path, 'w', encoding='utf-8') as f:
                    f.write(original_content)
            except Exception:
                pass
            return False
    
    async def test_container_cleanup(self):
        """Test 6: Clean up container."""
        self.log("=== TEST 6: Container Cleanup ===")
        
        try:
            await self.manager.stop_container(self.test_project_id)
            
            # Verify container is stopped
            status = self.manager.get_container_status(self.test_project_id)
            if not status.get('running'):
                self.log("[OK] Container stopped successfully")
                return True
            else:
                self.log("[ERROR] Container still running after stop")
                return False
                
        except Exception as e:
            self.log(f"[ERROR] Container cleanup failed: {e}")
            return False
    
    async def run_all_tests(self):
        """Run all tests in sequence."""
        self.log("Starting comprehensive container system tests...")
        self.log(f"Test project path: {self.test_project_path}")
        
        results = []
        
        # Test 1: Docker availability
        results.append(self.test_docker_availability())
        
        if not results[-1]:
            self.log("Stopping tests - Docker not available")
            return False
        
        # Test 2: Base image build
        results.append(self.test_base_image_build())
        
        if not results[-1]:
            self.log("Stopping tests - Base image build failed")
            return False
        
        # Test 3: Container start/stop
        results.append(await self.test_container_start_stop())
        
        if not results[-1]:
            self.log("Stopping tests - Container start failed")
            return False
        
        # Test 4: Preview accessibility
        results.append(self.test_preview_accessibility())
        
        # Test 5: Hot reload (continue even if preview fails)
        if results[-1]:
            results.append(self.test_hot_reload())
        else:
            self.log("Skipping hot reload test due to preview failure")
            results.append(False)
        
        # Test 6: Cleanup
        results.append(await self.test_container_cleanup())
        
        # Summary
        self.log("=== TEST SUMMARY ===")
        test_names = [
            "Docker Availability",
            "Base Image Build", 
            "Container Start/Stop",
            "Preview Accessibility",
            "Hot Reload",
            "Container Cleanup"
        ]
        
        passed = sum(results)
        total = len(results)
        
        for i, (name, result) in enumerate(zip(test_names, results)):
            status = "[OK] PASS" if result else "[ERROR] FAIL"
            self.log(f"{i+1}. {name}: {status}")
        
        self.log(f"Overall: {passed}/{total} tests passed")
        
        if passed == total:
            self.log("[SUCCESS] All tests passed! Container system is working perfectly.")
        else:
            self.log("[FAIL] Some tests failed. Check the logs above.")
        
        return passed == total

if __name__ == "__main__":
    async def main():
        test = ContainerSystemTest()
        success = await test.run_all_tests()
        sys.exit(0 if success else 1)
    
    asyncio.run(main())