#!/usr/bin/env python3
"""
Quick test script to verify the token refresh and container health check implementation.

Usage:
    python test_implementation.py
"""

import requests
import time
import json
from typing import Dict, Optional

# Configuration
BASE_URL = "http://localhost:8000"  # Change to your backend URL
TEST_USERNAME = "testuser123"
TEST_PASSWORD = "password"


def print_section(title: str):
    """Print a formatted section header."""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


def test_login() -> Dict[str, str]:
    """Test login and verify refresh token is returned."""
    print_section("TEST 1: Login and Refresh Token")

    # Login
    response = requests.post(
        f"{BASE_URL}/api/auth/token",
        data={
            "username": TEST_USERNAME,
            "password": TEST_PASSWORD
        }
    )

    if response.status_code != 200:
        print(f"❌ Login failed: {response.status_code} - {response.text}")
        return {}

    data = response.json()

    # Verify tokens are present
    if "access_token" not in data:
        print("❌ Access token not returned")
        return {}

    if "refresh_token" not in data:
        print("❌ Refresh token not returned")
        return {}

    print("✅ Login successful")
    print(f"   Access token (first 20 chars): {data['access_token'][:20]}...")
    print(f"   Refresh token (first 20 chars): {data['refresh_token'][:20]}...")
    print(f"   Token type: {data.get('token_type', 'N/A')}")

    return {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"]
    }


def test_token_refresh(tokens: Dict[str, str]) -> bool:
    """Test token refresh endpoint."""
    print_section("TEST 2: Token Refresh")

    if not tokens.get("refresh_token"):
        print("❌ No refresh token available")
        return False

    # Use refresh token to get new access token
    response = requests.post(
        f"{BASE_URL}/api/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]}
    )

    if response.status_code != 200:
        print(f"❌ Token refresh failed: {response.status_code} - {response.text}")
        return False

    data = response.json()

    # Verify new tokens are returned
    if "access_token" not in data or "refresh_token" not in data:
        print("❌ New tokens not returned")
        return False

    print("✅ Token refresh successful")
    print(f"   New access token (first 20 chars): {data['access_token'][:20]}...")
    print(f"   New refresh token (first 20 chars): {data['refresh_token'][:20]}...")
    print("   ℹ️  Note: Old refresh token should now be revoked (token rotation)")

    # Update tokens
    tokens["access_token"] = data["access_token"]
    tokens["refresh_token"] = data["refresh_token"]

    return True


def test_api_with_invalid_token(tokens: Dict[str, str]) -> bool:
    """Test that API returns 401 with invalid token."""
    print_section("TEST 3: API with Invalid Token")

    # Try to get projects with invalid token
    response = requests.get(
        f"{BASE_URL}/api/projects/",
        headers={"Authorization": "Bearer invalid_token_here"}
    )

    if response.status_code == 401:
        print("✅ API correctly returns 401 for invalid token")
        return True
    else:
        print(f"❌ Expected 401, got {response.status_code}")
        return False


def test_api_with_valid_token(tokens: Dict[str, str]) -> bool:
    """Test that API works with valid token."""
    print_section("TEST 4: API with Valid Token")

    if not tokens.get("access_token"):
        print("❌ No access token available")
        return False

    # Try to get projects with valid token
    response = requests.get(
        f"{BASE_URL}/api/projects/",
        headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )

    if response.status_code == 200:
        projects = response.json()
        print(f"✅ API request successful")
        print(f"   Projects count: {len(projects)}")
        return True
    else:
        print(f"❌ API request failed: {response.status_code} - {response.text}")
        return False


def test_container_health_check(tokens: Dict[str, str], project_id: int) -> bool:
    """Test container health check functionality."""
    print_section("TEST 5: Container Health Check")

    if not tokens.get("access_token"):
        print("❌ No access token available")
        return False

    # Get dev server URL (should trigger health check)
    response = requests.get(
        f"{BASE_URL}/api/projects/{project_id}/dev-server-url",
        headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )

    if response.status_code != 200:
        print(f"❌ Dev server URL request failed: {response.status_code}")
        print(f"   Response: {response.text[:200]}")
        return False

    data = response.json()

    print("✅ Dev server URL request successful")
    print(f"   Status: {data.get('status', 'N/A')}")
    print(f"   URL: {data.get('url', 'Not ready yet')}")
    print(f"   Message: {data.get('message', 'N/A')}")

    if data.get("status") == "starting":
        print("\n   ℹ️  Container is starting up. In production:")
        print("      - Frontend will show loading state")
        print("      - Frontend will retry automatically")
        print("      - User sees progress updates")

    return True


def test_container_status(tokens: Dict[str, str], project_id: int) -> bool:
    """Test container status endpoint."""
    print_section("TEST 6: Container Status")

    if not tokens.get("access_token"):
        print("❌ No access token available")
        return False

    # Get container status
    response = requests.get(
        f"{BASE_URL}/api/projects/{project_id}/container-status",
        headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )

    if response.status_code != 200:
        print(f"❌ Container status request failed: {response.status_code}")
        return False

    data = response.json()

    print("✅ Container status request successful")
    print(f"   Status: {data.get('status', 'N/A')}")
    print(f"   Running: {data.get('running', False)}")
    print(f"   URL: {data.get('url', 'N/A')}")

    if "replicas" in data:
        replicas = data["replicas"]
        print(f"   Replicas: {replicas.get('ready', 0)}/{replicas.get('desired', 0)}")

    return True


def main():
    """Run all tests."""
    print_section("🧪 Testing Token Refresh & Container Health Implementation")

    # Test 1: Login
    tokens = test_login()
    if not tokens:
        print("\n❌ Login test failed. Cannot proceed with other tests.")
        print("   Make sure the backend is running and test user exists.")
        return

    time.sleep(1)

    # Test 2: Token Refresh
    if not test_token_refresh(tokens):
        print("\n⚠️  Token refresh test failed.")
        print("   This is a CRITICAL issue - users will be logged out after 30 minutes.")
    time.sleep(1)

    # Test 3: Invalid Token
    test_api_with_invalid_token(tokens)
    time.sleep(1)

    # Test 4: Valid Token
    test_api_with_valid_token(tokens)
    time.sleep(1)

    # Test 5 & 6: Container Health Checks (if project exists)
    print("\n" + "="*60)
    project_id = input("Enter a project ID to test container health checks (or press Enter to skip): ").strip()

    if project_id:
        try:
            project_id = int(project_id)
            test_container_health_check(tokens, project_id)
            time.sleep(1)
            test_container_status(tokens, project_id)
        except ValueError:
            print("❌ Invalid project ID")

    # Summary
    print_section("📊 Test Summary")
    print("✅ Implementation tests completed!")
    print("\nNext steps:")
    print("1. Run the backend and frontend locally to test the full flow")
    print("2. Test in browser DevTools:")
    print("   - Verify refresh token is stored in localStorage")
    print("   - Verify token refresh happens on 401 errors")
    print("   - Verify containers auto-create when accessing projects")
    print("3. Deploy to production and run E2E Playwright tests")
    print("\nSee IMPLEMENTATION_COMPLETE.md for full testing instructions.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user.")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
