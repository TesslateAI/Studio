"""
Unit tests for k8s_client_helpers.py

Tests the helper functions for creating Kubernetes manifests for S3-backed
ephemeral architecture (init containers, lifecycle hooks, PVCs, deployments).
"""

import pytest
from uuid import UUID, uuid4

pytest.importorskip("kubernetes")

from kubernetes import client
from orchestrator.app.k8s_client_helpers import (
    create_s3_init_container_manifest,
    create_dehydration_lifecycle_hook,
    create_dynamic_pvc_manifest,
    create_deployment_manifest_s3
)


class TestS3InitContainerManifest:
    """Test create_s3_init_container_manifest function."""

    def test_creates_valid_init_container(self):
        """Test that init container manifest is created with correct structure."""
        user_id = uuid4()
        project_id = uuid4()
        s3_bucket = "test-bucket"
        s3_endpoint = "https://nyc3.digitaloceanspaces.com"
        s3_region = "us-east-1"
        pvc_name = "test-pvc"

        container = create_s3_init_container_manifest(
            user_id=user_id,
            project_id=project_id,
            s3_bucket=s3_bucket,
            s3_endpoint=s3_endpoint,
            s3_region=s3_region,
            pvc_name=pvc_name
        )

        # Verify it is a V1Container
        assert isinstance(container, client.V1Container)
        
        # Verify basic properties
        assert container.name == "hydrate-project"
        assert container.image == "amazon/aws-cli:latest"
        assert container.command == ["/bin/sh", "-c"]
        
        # Verify args contain S3 key path
        assert len(container.args) == 1
        script = container.args[0]
        assert f"projects/{user_id}/{project_id}/latest.zip" in script
        assert s3_bucket in script
        assert s3_endpoint in script


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
