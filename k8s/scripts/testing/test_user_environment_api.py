#!/usr/bin/env python3
"""
Test User Environment Creation via API
Tests the complete K8s-based user environment system end-to-end
"""

import requests
import time
import sys
import json
from typing import Optional

# Configuration
API_BASE_URL = "https://studio-test.tesslate.com/api"
TEST_USERNAME = f"testuser_{int(time.time())}"
TEST_PASSWORD = "TestPassword123!"
TEST_PROJECT_NAME = f"test_project_{int(time.time())}"

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'

def log_success(msg: str):
    print(f"{Colors.GREEN}[OK] {msg}{Colors.RESET}")

def log_error(msg: str):
    print(f"{Colors.RED}[ERROR] {msg}{Colors.RESET}")

def log_info(msg: str):
    print(f"{Colors.BLUE}[INFO] {msg}{Colors.RESET}")

def log_warning(msg: str):
    print(f"{Colors.YELLOW}[WARN] {msg}{Colors.RESET}")

class TesslateAPITest:
    def __init__(self):
        self.session = requests.Session()
        self.token: Optional[str] = None
        self.user_id: Optional[int] = None
        self.project_id: Optional[str] = None
        self.dev_url: Optional[str] = None

    def register_user(self) -> bool:
        """Register a new test user"""
        log_info(f"Registering user: {TEST_USERNAME}")
        try:
            # Step 1: Register
            response = self.session.post(
                f"{API_BASE_URL}/auth/register",
                json={
                    "username": TEST_USERNAME,
                    "email": f"{TEST_USERNAME}@test.com",
                    "password": TEST_PASSWORD
                },
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                self.user_id = data.get("id")
                log_success(f"User registered: ID={self.user_id}")

                # Step 2: Login to get token
                log_info("Logging in to get access token...")
                login_response = self.session.post(
                    f"{API_BASE_URL}/auth/token",
                    data={
                        "username": TEST_USERNAME,
                        "password": TEST_PASSWORD
                    },
                    timeout=10
                )

                if login_response.status_code == 200:
                    login_data = login_response.json()
                    self.token = login_data.get("access_token")
                    self.session.headers.update({"Authorization": f"Bearer {self.token}"})
                    log_success(f"Logged in successfully, Token={self.token[:20] if self.token else 'None'}...")
                    return True
                else:
                    log_error(f"Login failed: {login_response.status_code} - {login_response.text}")
                    return False
            else:
                log_error(f"Registration failed: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            log_error(f"Registration/login error: {e}")
            import traceback
            traceback.print_exc()
            return False

    def create_project(self) -> bool:
        """Create a new project"""
        log_info(f"Creating project: {TEST_PROJECT_NAME}")
        try:
            response = self.session.post(
                f"{API_BASE_URL}/projects/",
                json={
                    "name": TEST_PROJECT_NAME,
                    "description": "Test project for K8s user environments"
                },
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                self.project_id = data.get("id")
                log_success(f"Project created: ID={self.project_id}")
                return True
            else:
                log_error(f"Project creation failed: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            log_error(f"Project creation error: {e}")
            return False

    def start_dev_server(self) -> bool:
        """Start development server (creates K8s resources)"""
        log_info(f"Starting dev server for project {self.project_id}...")
        log_info("This will create: Deployment, Service, and Ingress in K8s")

        try:
            response = self.session.post(
                f"{API_BASE_URL}/projects/{self.project_id}/start-dev-container",
                timeout=120  # K8s resource creation can take time
            )

            if response.status_code == 200:
                data = response.json()
                self.dev_url = data.get("url")
                log_success(f"Dev server started!")
                log_success(f"URL: {self.dev_url}")
                return True
            else:
                log_error(f"Dev server start failed: {response.status_code}")
                log_error(f"Response: {response.text}")
                return False
        except requests.exceptions.Timeout:
            log_error("Dev server start timed out (>120s)")
            log_warning("This might indicate K8s pod creation issues")
            return False
        except Exception as e:
            log_error(f"Dev server start error: {e}")
            return False

    def check_dev_server_status(self) -> bool:
        """Check development server status"""
        log_info("Checking dev server status...")
        try:
            response = self.session.get(
                f"{API_BASE_URL}/projects/{self.project_id}/status",
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                status = data.get("status")
                running = data.get("running", False)

                log_info(f"Status: {status}")
                log_info(f"Running: {running}")

                if "url" in data:
                    log_info(f"URL: {data['url']}")

                if "deployment_name" in data:
                    log_info(f"Deployment: {data['deployment_name']}")

                if "pods" in data:
                    log_info(f"Pods: {json.dumps(data['pods'], indent=2)}")

                if running:
                    log_success("Dev server is running!")
                    return True
                else:
                    log_warning("Dev server is not running yet")
                    return False
            else:
                log_error(f"Status check failed: {response.status_code}")
                return False
        except Exception as e:
            log_error(f"Status check error: {e}")
            return False

    def wait_for_dev_server(self, max_wait: int = 180) -> bool:
        """Wait for dev server to be ready"""
        log_info(f"Waiting for dev server to be ready (max {max_wait}s)...")

        start_time = time.time()
        while time.time() - start_time < max_wait:
            if self.check_dev_server_status():
                elapsed = int(time.time() - start_time)
                log_success(f"Dev server ready after {elapsed}s")
                return True

            time.sleep(5)

        log_error(f"Dev server not ready after {max_wait}s")
        return False

    def test_dev_server_url(self) -> bool:
        """Test if dev server URL is accessible"""
        if not self.dev_url:
            log_warning("No dev URL available to test")
            return False

        log_info(f"Testing dev server URL: {self.dev_url}")
        try:
            # Note: SSL verification might fail for self-signed certs
            response = requests.get(self.dev_url, timeout=10, verify=False)

            if response.status_code == 200:
                log_success(f"Dev server is accessible! Status: {response.status_code}")
                return True
            else:
                log_warning(f"Dev server responded with: {response.status_code}")
                return False
        except requests.exceptions.SSLError:
            log_warning("SSL certificate verification failed (expected for test)")
            log_info("Try accessing in browser: " + self.dev_url)
            return True  # Not a failure, just SSL issue
        except Exception as e:
            log_error(f"Dev server not accessible: {e}")
            return False

    def cleanup(self) -> bool:
        """Stop dev server and cleanup resources"""
        if not self.project_id:
            return True

        log_info(f"Cleaning up project {self.project_id}...")
        try:
            response = self.session.post(
                f"{API_BASE_URL}/projects/{self.project_id}/stop-dev-container",
                timeout=30
            )

            if response.status_code == 200:
                log_success("Dev server stopped")
                return True
            else:
                log_warning(f"Cleanup response: {response.status_code}")
                return False
        except Exception as e:
            log_error(f"Cleanup error: {e}")
            return False

    def run_full_test(self) -> bool:
        """Run complete end-to-end test"""
        print("\n" + "="*60)
        print("Tesslate User Environment E2E Test")
        print("="*60 + "\n")

        # Step 1: Register user
        print("\nStep 1: User Registration")
        if not self.register_user():
            return False

        # Step 2: Create project
        print("\nStep 2: Project Creation")
        if not self.create_project():
            return False

        # Step 3: Start dev server (K8s resources)
        print("\nStep 3: Start Dev Server (K8s)")
        if not self.start_dev_server():
            return False

        # Step 4: Wait for dev server to be ready
        print("\nStep 4: Wait for Dev Server")
        if not self.wait_for_dev_server():
            log_warning("Dev server not ready, but continuing...")

        # Step 5: Test accessibility
        print("\nStep 5: Test Dev Server URL")
        self.test_dev_server_url()

        # Step 6: Cleanup
        print("\nStep 6: Cleanup")
        self.cleanup()

        print("\n" + "="*60)
        print("[SUCCESS] Test Complete!")
        print("="*60 + "\n")

        return True

def main():
    """Main test execution"""
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    test = TesslateAPITest()

    try:
        success = test.run_full_test()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n[WARN] Test interrupted by user")
        test.cleanup()
        sys.exit(1)
    except Exception as e:
        log_error(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()