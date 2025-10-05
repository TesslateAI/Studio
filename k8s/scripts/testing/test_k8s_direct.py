#!/usr/bin/env python3
"""
Direct test of Kubernetes client to debug pod creation issues.
Run this inside the cluster or with proper kubeconfig.
"""

import sys
import os

# Add orchestrator to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'orchestrator'))

from app.k8s_client import get_k8s_manager
import traceback

async def test_k8s_creation():
    """Test creating a dev environment."""
    try:
        print("Initializing Kubernetes manager...")
        k8s_manager = get_k8s_manager()
        print(f"✓ K8s manager initialized")
        print(f"  Namespace: {k8s_manager.namespace}")
        print(f"  User namespace: {k8s_manager.user_namespace}")

        print("\nAttempting to create dev environment for user 999, project test...")
        result = await k8s_manager.create_dev_environment(
            user_id=999,
            project_id="test",
            project_path="/tmp/test"
        )

        print("✓ Dev environment created successfully!")
        print(f"  Result: {result}")

    except Exception as e:
        print(f"\n✗ Error creating dev environment:")
        print(f"  Error: {e}")
        print(f"\n  Full traceback:")
        traceback.print_exc()
        return False

    return True

if __name__ == "__main__":
    import asyncio
    success = asyncio.run(test_k8s_creation())
    sys.exit(0 if success else 1)