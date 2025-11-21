"""
Unit tests for S3-backed ephemeral storage (hydration/dehydration).

Tests the complete lifecycle of project hibernation:
- Hydration: Download project from S3 and extract to pod
- Dehydration: Compress project and upload to S3 before pod termination
- S3 manager operations (upload, download, exists, delete)
- InitContainer manifest generation
- Lifecycle hook generation
"""

import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, Mock, patch, MagicMock

pytest.importorskip("kubernetes")

from kubernetes import client
import boto3
from botocore.exceptions import ClientError

from app.k8s_client_helpers import (
    create_s3_init_container_manifest,
    create_dehydration_lifecycle_hook,
    create_dynamic_pvc_manifest,
    create_deployment_manifest_s3
)
from app.services.s3_manager import S3Manager


@pytest.mark.unit
@pytest.mark.kubernetes
class TestS3InitContainerManifest:
    """Test S3 hydration init container manifest generation."""

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

    def test_init_container_has_volume_mount(self):
        """Test init container mounts the project volume."""
        user_id = uuid4()
        project_id = uuid4()
        pvc_name = "test-pvc"

        container = create_s3_init_container_manifest(
            user_id=user_id,
            project_id=project_id,
            s3_bucket="test",
            s3_endpoint="https://test",
            s3_region="us-east-1",
            pvc_name=pvc_name
        )

        # Verify volume mount
        assert len(container.volume_mounts) == 1
        assert container.volume_mounts[0].name == "project-data"
        assert container.volume_mounts[0].mount_path == "/app"

    def test_init_container_has_env_from_secret(self):
        """Test init container loads S3 credentials from secret."""
        container = create_s3_init_container_manifest(
            user_id=uuid4(),
            project_id=uuid4(),
            s3_bucket="test",
            s3_endpoint="https://test",
            s3_region="us-east-1",
            pvc_name="test-pvc"
        )

        # Verify env from secret
        assert len(container.env_from) == 1
        assert container.env_from[0].secret_ref.name == "s3-credentials"

    def test_init_container_script_handles_missing_file(self):
        """Test init container script handles case when S3 file doesn't exist."""
        container = create_s3_init_container_manifest(
            user_id=uuid4(),
            project_id=uuid4(),
            s3_bucket="test",
            s3_endpoint="https://test",
            s3_region="us-east-1",
            pvc_name="test-pvc"
        )

        script = container.args[0]

        # Should check if file exists first
        assert "aws s3 ls" in script
        assert "if" in script and "then" in script

        # Should have fallback logic (copy template or create empty)
        assert "else" in script


@pytest.mark.unit
@pytest.mark.kubernetes
class TestDehydrationLifecycleHook:
    """Test S3 dehydration lifecycle hook generation."""

    def test_creates_valid_prestop_hook(self):
        """Test preStop hook manifest is created correctly."""
        user_id = uuid4()
        project_id = uuid4()
        s3_bucket = "test-bucket"
        s3_endpoint = "https://nyc3.digitaloceanspaces.com"

        lifecycle = create_dehydration_lifecycle_hook(
            user_id=user_id,
            project_id=project_id,
            s3_bucket=s3_bucket,
            s3_endpoint=s3_endpoint
        )

        # Verify it is a V1Lifecycle
        assert isinstance(lifecycle, client.V1Lifecycle)
        assert lifecycle.pre_stop is not None

        # Verify it uses exec handler
        assert lifecycle.pre_stop.exec_ is not None
        assert len(lifecycle.pre_stop.exec_.command) > 0

    def test_prestop_hook_compresses_and_uploads(self):
        """Test preStop hook script compresses /app and uploads to S3."""
        user_id = uuid4()
        project_id = uuid4()
        s3_bucket = "test-bucket"
        s3_endpoint = "https://test"

        lifecycle = create_dehydration_lifecycle_hook(
            user_id=user_id,
            project_id=project_id,
            s3_bucket=s3_bucket,
            s3_endpoint=s3_endpoint
        )

        script = " ".join(lifecycle.pre_stop.exec_.command)

        # Should zip the /app directory
        assert "zip" in script or "tar" in script
        assert "/app" in script

        # Should upload to S3
        assert "aws s3 cp" in script or "s3 sync" in script
        assert f"projects/{user_id}/{project_id}" in script

    def test_prestop_hook_excludes_unnecessary_files(self):
        """Test preStop hook excludes cache and dependency directories."""
        lifecycle = create_dehydration_lifecycle_hook(
            user_id=uuid4(),
            project_id=uuid4(),
            s3_bucket="test",
            s3_endpoint="https://test"
        )

        script = " ".join(lifecycle.pre_stop.exec_.command)

        # Should exclude common cache directories
        # Look for exclude patterns
        assert "-x" in script or "--exclude" in script or "grep -v" in script


@pytest.mark.unit
@pytest.mark.kubernetes
class TestDynamicPVCManifest:
    """Test dynamic PVC manifest generation."""

    def test_creates_pvc_with_correct_storage_class(self):
        """Test PVC uses the configured storage class."""
        pvc_name = "test-pvc"
        storage_size = "5Gi"
        storage_class = "do-block-storage"

        pvc = create_dynamic_pvc_manifest(
            pvc_name=pvc_name,
            storage_size=storage_size,
            storage_class=storage_class
        )

        assert isinstance(pvc, client.V1PersistentVolumeClaim)
        assert pvc.metadata.name == pvc_name
        assert pvc.spec.storage_class_name == storage_class

    def test_pvc_has_correct_access_mode(self):
        """Test PVC has ReadWriteOnce access mode for block storage."""
        pvc = create_dynamic_pvc_manifest(
            pvc_name="test",
            storage_size="5Gi",
            storage_class="do-block-storage"
        )

        # For ephemeral storage, should be RWO (ReadWriteOnce)
        assert "ReadWriteOnce" in pvc.spec.access_modes

    def test_pvc_requests_correct_storage_size(self):
        """Test PVC requests the specified storage size."""
        storage_size = "10Gi"

        pvc = create_dynamic_pvc_manifest(
            pvc_name="test",
            storage_size=storage_size,
            storage_class="test"
        )

        assert pvc.spec.resources.requests["storage"] == storage_size


@pytest.mark.unit
@pytest.mark.kubernetes
class TestDeploymentManifestS3:
    """Test complete deployment manifest with S3 integration."""

    def test_deployment_has_init_container(self):
        """Test deployment includes init container for hydration."""
        deployment_name = "test-deployment"
        user_id = uuid4()
        project_id = uuid4()

        deployment = create_deployment_manifest_s3(
            deployment_name=deployment_name,
            user_id=user_id,
            project_id=project_id,
            image="test-image",
            namespace="test-namespace",
            s3_bucket="test-bucket",
            s3_endpoint="https://test",
            s3_region="us-east-1",
            pvc_name="test-pvc"
        )

        assert isinstance(deployment, client.V1Deployment)
        init_containers = deployment.spec.template.spec.init_containers
        assert init_containers is not None
        assert len(init_containers) >= 1
        assert init_containers[0].name == "hydrate-project"

    def test_deployment_has_lifecycle_hook(self):
        """Test deployment main container has dehydration lifecycle hook."""
        deployment = create_deployment_manifest_s3(
            deployment_name="test",
            user_id=uuid4(),
            project_id=uuid4(),
            image="test-image",
            namespace="test-namespace",
            s3_bucket="test-bucket",
            s3_endpoint="https://test",
            s3_region="us-east-1",
            pvc_name="test-pvc"
        )

        main_container = deployment.spec.template.spec.containers[0]
        assert main_container.lifecycle is not None
        assert main_container.lifecycle.pre_stop is not None

    def test_deployment_has_termination_grace_period(self):
        """Test deployment has sufficient grace period for dehydration."""
        deployment = create_deployment_manifest_s3(
            deployment_name="test",
            user_id=uuid4(),
            project_id=uuid4(),
            image="test-image",
            namespace="test-namespace",
            s3_bucket="test-bucket",
            s3_endpoint="https://test",
            s3_region="us-east-1",
            pvc_name="test-pvc"
        )

        # Should have at least 120 seconds for S3 upload
        assert deployment.spec.template.spec.termination_grace_period_seconds >= 120


@pytest.mark.unit
@pytest.mark.kubernetes
class TestS3Manager:
    """Test S3Manager service for project archive operations."""

    @pytest.fixture
    def mock_s3_client(self):
        """Create mock S3 client."""
        with patch('boto3.client') as mock_boto:
            mock_client = Mock()
            mock_boto.return_value = mock_client
            yield mock_client

    @pytest.fixture
    def s3_manager(self, mock_s3_client):
        """Create S3Manager with mocked client."""
        with patch('app.services.s3_manager.get_settings') as mock_settings:
            mock_settings.return_value.s3_access_key_id = "test-key"
            mock_settings.return_value.s3_secret_access_key = "test-secret"
            mock_settings.return_value.s3_bucket_name = "test-bucket"
            mock_settings.return_value.s3_endpoint_url = "https://test"
            mock_settings.return_value.s3_region = "us-east-1"

            manager = S3Manager()
            manager.s3_client = mock_s3_client
            return manager

    @pytest.mark.asyncio
    async def test_project_exists_returns_true_when_found(self, s3_manager, mock_s3_client):
        """Test project_exists returns True when archive exists in S3."""
        user_id = uuid4()
        project_id = uuid4()

        # Mock successful head_object
        mock_s3_client.head_object.return_value = {"ContentLength": 1000}

        exists = await s3_manager.project_exists(user_id, project_id)

        assert exists is True
        mock_s3_client.head_object.assert_called_once()

    @pytest.mark.asyncio
    async def test_project_exists_returns_false_when_not_found(self, s3_manager, mock_s3_client):
        """Test project_exists returns False when archive doesn't exist."""
        user_id = uuid4()
        project_id = uuid4()

        # Mock 404 error
        mock_s3_client.head_object.side_effect = ClientError(
            {"Error": {"Code": "404"}}, "head_object"
        )

        exists = await s3_manager.project_exists(user_id, project_id)

        assert exists is False

    @pytest.mark.asyncio
    async def test_upload_project_compresses_and_uploads(self, s3_manager, mock_s3_client):
        """Test upload_project creates zip and uploads to S3."""
        user_id = uuid4()
        project_id = uuid4()
        project_path = "/tmp/test-project"

        mock_s3_client.upload_file.return_value = None

        with patch('zipfile.ZipFile'):
            with patch('os.walk', return_value=[
                (project_path, [], ["file1.txt", "file2.js"])
            ]):
                success = await s3_manager.upload_project(user_id, project_id, project_path)

        assert success is True
        mock_s3_client.upload_file.assert_called_once()

    @pytest.mark.asyncio
    async def test_download_project_downloads_and_extracts(self, s3_manager, mock_s3_client):
        """Test download_project downloads from S3 and extracts zip."""
        user_id = uuid4()
        project_id = uuid4()
        destination_path = "/tmp/download"

        mock_s3_client.download_file.return_value = None

        with patch('zipfile.ZipFile'):
            with patch('os.makedirs'):
                success = await s3_manager.download_project(user_id, project_id, destination_path)

        assert success is True
        mock_s3_client.download_file.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_project_removes_from_s3(self, s3_manager, mock_s3_client):
        """Test delete_project removes archive from S3."""
        user_id = uuid4()
        project_id = uuid4()

        mock_s3_client.delete_object.return_value = None

        success = await s3_manager.delete_project(user_id, project_id)

        assert success is True
        mock_s3_client.delete_object.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_presigned_url_generates_valid_url(self, s3_manager, mock_s3_client):
        """Test get_presigned_url generates download URL."""
        user_id = uuid4()
        project_id = uuid4()

        mock_s3_client.generate_presigned_url.return_value = "https://test-url"

        url = await s3_manager.get_presigned_url(user_id, project_id, expiration=3600)

        assert url == "https://test-url"
        mock_s3_client.generate_presigned_url.assert_called_once_with(
            'get_object',
            Params={'Bucket': 'test-bucket', 'Key': f"projects/{user_id}/{project_id}/latest.zip"},
            ExpiresIn=3600
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
