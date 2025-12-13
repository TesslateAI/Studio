"""
S3 Manager for Project Hibernation/Hydration

This service manages project storage in S3-compatible object storage (AWS S3 or DigitalOcean Spaces).
It handles the hibernation/hydration cycle for ephemeral Kubernetes pods.

Architecture:
- Projects are stored as compressed archives in S3
- Path structure: s3://bucket/projects/{user_id}/{project_id}/latest.zip
- Compression: ZIP format with gzip compression
- Large files (node_modules) are optionally excluded for faster uploads

Operations:
- Hydration: Download and extract project from S3 to pod filesystem
- Dehydration: Compress and upload project from pod filesystem to S3
- Verification: Check if project exists in S3
- Cleanup: Delete project archives

Supported Providers:
- AWS S3: Leave S3_ENDPOINT_URL empty, set S3_REGION to your bucket's region
- DigitalOcean Spaces: Set S3_ENDPOINT_URL (e.g., https://nyc3.digitaloceanspaces.com)
"""

import logging
import boto3
import os
import asyncio
import tempfile
import zipfile
import shutil
from typing import Optional, Tuple
from uuid import UUID
from botocore.exceptions import ClientError, BotoCoreError
from botocore.config import Config
from ..config import get_settings

logger = logging.getLogger(__name__)

# Retry configuration for S3 operations
S3_RETRY_CONFIG = Config(
    retries={
        'max_attempts': 3,
        'mode': 'adaptive'  # Adaptive retry mode for better resilience
    },
    connect_timeout=10,
    read_timeout=120,  # 2 minutes for large files
)


class S3Manager:
    """
    Manages project storage in S3-compatible object storage (AWS S3 or DigitalOcean Spaces).

    Handles compression, upload, download, and cleanup of project files for
    the Kubernetes S3-backed ephemeral architecture.
    """

    def __init__(self):
        """Initialize S3 client for AWS S3 or S3-compatible storage."""
        settings = get_settings()

        # Build client kwargs
        client_kwargs = {
            'region_name': settings.s3_region,
            'config': S3_RETRY_CONFIG
        }

        # Use explicit credentials if provided, otherwise rely on IRSA/IAM role
        if settings.s3_access_key_id and settings.s3_secret_access_key:
            client_kwargs['aws_access_key_id'] = settings.s3_access_key_id
            client_kwargs['aws_secret_access_key'] = settings.s3_secret_access_key
            auth_method = "explicit credentials"
        else:
            # On EKS, IRSA (IAM Roles for Service Accounts) provides credentials
            # via AWS_WEB_IDENTITY_TOKEN_FILE and AWS_ROLE_ARN env vars
            # boto3 automatically uses these when no explicit credentials are provided
            auth_method = "IRSA/IAM role"

        # Only add endpoint_url if configured (for DigitalOcean Spaces, MinIO, etc.)
        if settings.s3_endpoint_url:
            client_kwargs['endpoint_url'] = settings.s3_endpoint_url
            provider = "S3-compatible"
        else:
            provider = "AWS S3"

        # Initialize boto3 S3 client
        self.s3_client = boto3.client('s3', **client_kwargs)

        self.bucket_name = settings.s3_bucket_name
        self.projects_prefix = settings.s3_projects_prefix
        self.region = settings.s3_region

        logger.info(f"[S3] Initialized S3Manager for bucket: {self.bucket_name}")
        logger.info(f"[S3] Provider: {provider}, Auth: {auth_method}")
        logger.info(f"[S3] Endpoint: {settings.s3_endpoint_url or '(AWS default)'}")
        logger.info(f"[S3] Region: {settings.s3_region}")

        # Verify bucket exists
        self._verify_bucket()

    def _verify_bucket(self) -> None:
        """Verify that the S3 bucket exists and is accessible."""
        try:
            self.s3_client.head_bucket(Bucket=self.bucket_name)
            logger.info(f"[S3] ✅ Bucket '{self.bucket_name}' is accessible")
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            if error_code == '404':
                logger.error(f"[S3] ❌ Bucket '{self.bucket_name}' does not exist")
                raise ValueError(f"S3 bucket '{self.bucket_name}' does not exist. Create it first.")
            elif error_code == '403':
                logger.error(f"[S3] ❌ Access denied to bucket '{self.bucket_name}'")
                raise ValueError(f"Access denied to S3 bucket '{self.bucket_name}'. Check credentials.")
            else:
                logger.error(f"[S3] ❌ Error accessing bucket: {e}")
                raise

    def _get_project_key(self, user_id: UUID, project_id: UUID) -> str:
        """
        Generate S3 object key for a project.

        Format: projects/{user_id}/{project_id}/latest.zip

        Args:
            user_id: User UUID
            project_id: Project UUID

        Returns:
            S3 object key
        """
        return f"{self.projects_prefix}/{user_id}/{project_id}/latest.zip"

    async def project_exists(self, user_id: UUID, project_id: UUID) -> bool:
        """
        Check if a project archive exists in S3.

        Args:
            user_id: User UUID
            project_id: Project UUID

        Returns:
            True if project exists, False otherwise
        """
        key = self._get_project_key(user_id, project_id)

        try:
            # Use head_object to check existence without downloading
            await asyncio.to_thread(
                self.s3_client.head_object,
                Bucket=self.bucket_name,
                Key=key
            )
            logger.info(f"[S3] ✅ Project exists: {key}")
            return True
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            if error_code == '404':
                logger.info(f"[S3] Project not found: {key}")
                return False
            else:
                logger.error(f"[S3] Error checking project existence: {e}")
                raise

    async def upload_project(
        self,
        user_id: UUID,
        project_id: UUID,
        source_path: str,
        exclude_node_modules: bool = False
    ) -> Tuple[bool, Optional[str]]:
        """
        Upload a project directory to S3 as a compressed archive (dehydration).

        Steps:
        1. Create temporary zip file
        2. Compress source directory
        3. Upload to S3
        4. Cleanup temporary file

        Args:
            user_id: User UUID
            project_id: Project UUID
            source_path: Local path to project directory
            exclude_node_modules: If True, exclude node_modules to reduce size

        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        key = self._get_project_key(user_id, project_id)

        logger.info(f"[S3] Starting project upload: {key}")
        logger.info(f"[S3] Source path: {source_path}")
        logger.info(f"[S3] Exclude node_modules: {exclude_node_modules}")

        if not os.path.exists(source_path):
            error_msg = f"Source path does not exist: {source_path}"
            logger.error(f"[S3] ❌ {error_msg}")
            return False, error_msg

        # Create temporary zip file
        temp_zip = None
        try:
            # Create temp file in system temp directory
            temp_fd, temp_zip = tempfile.mkstemp(suffix='.zip', prefix='tesslate-project-')
            os.close(temp_fd)  # Close file descriptor, we'll use the path

            # Compress directory to zip file
            logger.info(f"[S3] Compressing directory to: {temp_zip}")
            await asyncio.to_thread(
                self._compress_directory,
                source_path,
                temp_zip,
                exclude_node_modules
            )

            # Get file size for logging
            file_size_mb = os.path.getsize(temp_zip) / (1024 * 1024)
            logger.info(f"[S3] Compressed archive size: {file_size_mb:.2f} MB")

            # Upload to S3
            logger.info(f"[S3] Uploading to S3: {key}")
            await asyncio.to_thread(
                self.s3_client.upload_file,
                temp_zip,
                self.bucket_name,
                key,
                ExtraArgs={
                    'ContentType': 'application/zip',
                    'Metadata': {
                        'user_id': str(user_id),
                        'project_id': str(project_id),
                    }
                }
            )

            logger.info(f"[S3] ✅ Project uploaded successfully: {key} ({file_size_mb:.2f} MB)")
            return True, None

        except Exception as e:
            error_msg = f"Failed to upload project: {str(e)}"
            logger.error(f"[S3] ❌ {error_msg}", exc_info=True)
            return False, error_msg

        finally:
            # Cleanup temporary file
            if temp_zip and os.path.exists(temp_zip):
                try:
                    os.remove(temp_zip)
                    logger.debug(f"[S3] Cleaned up temp file: {temp_zip}")
                except Exception as e:
                    logger.warning(f"[S3] Failed to cleanup temp file: {e}")

    def _compress_directory(
        self,
        source_dir: str,
        output_zip: str,
        exclude_node_modules: bool = False
    ) -> None:
        """
        Compress a directory to a zip file.

        Args:
            source_dir: Source directory to compress
            output_zip: Output zip file path
            exclude_node_modules: If True, exclude node_modules directories
        """
        exclude_patterns = ['.git', '__pycache__', '*.pyc', '.DS_Store']
        if exclude_node_modules:
            exclude_patterns.append('node_modules')

        with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(source_dir):
                # Filter out excluded directories
                if exclude_node_modules and 'node_modules' in dirs:
                    dirs.remove('node_modules')
                if '.git' in dirs:
                    dirs.remove('.git')
                if '__pycache__' in dirs:
                    dirs.remove('__pycache__')

                for file in files:
                    # Skip excluded files
                    if any(file.endswith(pattern.replace('*', '')) for pattern in exclude_patterns if '*' in pattern):
                        continue

                    file_path = os.path.join(root, file)
                    # Calculate relative path from source_dir
                    arcname = os.path.relpath(file_path, source_dir)
                    zipf.write(file_path, arcname)

        logger.debug(f"[S3] Compressed {source_dir} to {output_zip}")

    async def download_project(
        self,
        user_id: UUID,
        project_id: UUID,
        dest_path: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Download a project from S3 and extract to destination (hydration).

        Steps:
        1. Download zip from S3 to temp file
        2. Extract to destination directory
        3. Cleanup temporary file

        Args:
            user_id: User UUID
            project_id: Project UUID
            dest_path: Local destination directory

        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        key = self._get_project_key(user_id, project_id)

        logger.info(f"[S3] Starting project download: {key}")
        logger.info(f"[S3] Destination path: {dest_path}")

        # Create destination directory if it doesn't exist
        os.makedirs(dest_path, exist_ok=True)

        temp_zip = None
        try:
            # Create temporary file for download
            temp_fd, temp_zip = tempfile.mkstemp(suffix='.zip', prefix='tesslate-project-')
            os.close(temp_fd)

            # Download from S3
            logger.info(f"[S3] Downloading from S3: {key}")
            await asyncio.to_thread(
                self.s3_client.download_file,
                self.bucket_name,
                key,
                temp_zip
            )

            # Get file size for logging
            file_size_mb = os.path.getsize(temp_zip) / (1024 * 1024)
            logger.info(f"[S3] Downloaded archive size: {file_size_mb:.2f} MB")

            # Extract zip to destination
            logger.info(f"[S3] Extracting to: {dest_path}")
            await asyncio.to_thread(
                self._extract_zip,
                temp_zip,
                dest_path
            )

            logger.info(f"[S3] ✅ Project downloaded and extracted successfully: {key}")
            return True, None

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            if error_code == 'NoSuchKey':
                error_msg = f"Project not found in S3: {key}"
            else:
                error_msg = f"S3 error downloading project: {str(e)}"
            logger.error(f"[S3] ❌ {error_msg}")
            return False, error_msg

        except Exception as e:
            error_msg = f"Failed to download project: {str(e)}"
            logger.error(f"[S3] ❌ {error_msg}", exc_info=True)
            return False, error_msg

        finally:
            # Cleanup temporary file
            if temp_zip and os.path.exists(temp_zip):
                try:
                    os.remove(temp_zip)
                    logger.debug(f"[S3] Cleaned up temp file: {temp_zip}")
                except Exception as e:
                    logger.warning(f"[S3] Failed to cleanup temp file: {e}")

    def _extract_zip(self, zip_path: str, dest_dir: str) -> None:
        """
        Extract a zip file to destination directory.

        Args:
            zip_path: Path to zip file
            dest_dir: Destination directory
        """
        with zipfile.ZipFile(zip_path, 'r') as zipf:
            zipf.extractall(dest_dir)
        logger.debug(f"[S3] Extracted {zip_path} to {dest_dir}")

    async def delete_project(
        self,
        user_id: UUID,
        project_id: UUID
    ) -> Tuple[bool, Optional[str]]:
        """
        Delete a project archive from S3.

        Args:
            user_id: User UUID
            project_id: Project UUID

        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        key = self._get_project_key(user_id, project_id)

        logger.info(f"[S3] Deleting project: {key}")

        try:
            await asyncio.to_thread(
                self.s3_client.delete_object,
                Bucket=self.bucket_name,
                Key=key
            )

            logger.info(f"[S3] ✅ Project deleted: {key}")
            return True, None

        except Exception as e:
            error_msg = f"Failed to delete project: {str(e)}"
            logger.error(f"[S3] ❌ {error_msg}", exc_info=True)
            return False, error_msg

    async def get_presigned_url(
        self,
        user_id: UUID,
        project_id: UUID,
        expiration: int = 3600
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Generate a presigned URL for direct download access.

        Useful for allowing users to download their project archives directly
        without going through the backend.

        Args:
            user_id: User UUID
            project_id: Project UUID
            expiration: URL expiration time in seconds (default: 1 hour)

        Returns:
            Tuple of (url: Optional[str], error_message: Optional[str])
        """
        key = self._get_project_key(user_id, project_id)

        logger.info(f"[S3] Generating presigned URL for: {key}")

        try:
            url = await asyncio.to_thread(
                self.s3_client.generate_presigned_url,
                'get_object',
                Params={
                    'Bucket': self.bucket_name,
                    'Key': key
                },
                ExpiresIn=expiration
            )

            logger.info(f"[S3] ✅ Presigned URL generated (expires in {expiration}s)")
            return url, None

        except Exception as e:
            error_msg = f"Failed to generate presigned URL: {str(e)}"
            logger.error(f"[S3] ❌ {error_msg}", exc_info=True)
            return None, error_msg

    async def copy_to_deleted(
        self,
        user_id: UUID,
        project_id: UUID
    ) -> Tuple[bool, Optional[str]]:
        """
        Copy a project archive to the 'deleted/' prefix for backup retention.

        Used when a project is deleted to preserve a backup copy before
        removing the active archive. This allows separate retention policies
        for deleted vs active projects.

        S3 path: deleted/{user_id}/{project_id}/latest.zip

        Args:
            user_id: User UUID
            project_id: Project UUID

        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        source_key = self._get_project_key(user_id, project_id)
        dest_key = f"deleted/{user_id}/{project_id}/latest.zip"

        logger.info(f"[S3] Copying project to deleted archive: {source_key} -> {dest_key}")

        try:
            # Check if source exists first
            if not await self.project_exists(user_id, project_id):
                logger.info(f"[S3] No existing archive to copy: {source_key}")
                return True, None  # Nothing to copy, but not an error

            # Use S3 copy_object (server-side copy, no download needed)
            await asyncio.to_thread(
                self.s3_client.copy_object,
                Bucket=self.bucket_name,
                CopySource={'Bucket': self.bucket_name, 'Key': source_key},
                Key=dest_key,
                MetadataDirective='COPY'  # Preserve original metadata
            )

            logger.info(f"[S3] ✅ Project copied to deleted archive: {dest_key}")
            return True, None

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            if error_code == 'NoSuchKey':
                # Source doesn't exist - not an error for deletion flow
                logger.info(f"[S3] Source archive not found (already deleted?): {source_key}")
                return True, None
            else:
                error_msg = f"Failed to copy to deleted archive: {str(e)}"
                logger.error(f"[S3] ❌ {error_msg}")
                return False, error_msg

        except Exception as e:
            error_msg = f"Failed to copy to deleted archive: {str(e)}"
            logger.error(f"[S3] ❌ {error_msg}", exc_info=True)
            return False, error_msg

    async def get_project_size(
        self,
        user_id: UUID,
        project_id: UUID
    ) -> Tuple[Optional[int], Optional[str]]:
        """
        Get the size of a project archive in S3.

        Args:
            user_id: User UUID
            project_id: Project UUID

        Returns:
            Tuple of (size_bytes: Optional[int], error_message: Optional[str])
        """
        key = self._get_project_key(user_id, project_id)

        try:
            response = await asyncio.to_thread(
                self.s3_client.head_object,
                Bucket=self.bucket_name,
                Key=key
            )

            size_bytes = response.get('ContentLength', 0)
            logger.info(f"[S3] Project size: {size_bytes / (1024*1024):.2f} MB")
            return size_bytes, None

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            if error_code == '404':
                return None, "Project not found in S3"
            else:
                error_msg = f"Failed to get project size: {str(e)}"
                logger.error(f"[S3] ❌ {error_msg}")
                return None, error_msg


# Singleton instance
_s3_manager: Optional[S3Manager] = None


def get_s3_manager() -> S3Manager:
    """Get the singleton S3Manager instance."""
    global _s3_manager

    if _s3_manager is None:
        settings = get_settings()

        # Only initialize if S3 storage is enabled
        if not settings.k8s_use_s3_storage:
            raise RuntimeError(
                "S3 storage is not enabled. Set K8S_USE_S3_STORAGE=true to enable."
            )

        _s3_manager = S3Manager()

    return _s3_manager
