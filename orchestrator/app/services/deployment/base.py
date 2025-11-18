"""
Base deployment provider interface and data models.

This module defines the abstract base class that all deployment providers must implement,
along with Pydantic models for deployment configuration and results.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from pydantic import BaseModel, Field
import asyncio
import os
from pathlib import Path


class DeploymentFile(BaseModel):
    """Represents a file to be deployed."""
    path: str = Field(..., description="Relative path of the file")
    content: bytes = Field(..., description="File content as bytes")
    encoding: str = Field(default="utf-8", description="File encoding")

    class Config:
        arbitrary_types_allowed = True


class DeploymentConfig(BaseModel):
    """Configuration for a deployment."""
    project_id: str = Field(..., description="Unique project identifier")
    project_name: str = Field(..., description="Human-readable project name")
    framework: str = Field(..., description="Framework type (vite, nextjs, react, etc.)")
    deployment_mode: str = Field(default="pre-built", description="Deployment mode: 'source' or 'pre-built'")
    build_command: Optional[str] = Field(None, description="Custom build command override")
    start_command: Optional[str] = Field(None, description="Custom start command for server frameworks")
    env_vars: Dict[str, str] = Field(default_factory=dict, description="Environment variables")
    custom_domain: Optional[str] = Field(None, description="Custom domain for deployment")


class DeploymentResult(BaseModel):
    """Result of a deployment operation."""
    success: bool = Field(..., description="Whether deployment succeeded")
    deployment_id: Optional[str] = Field(None, description="Provider's deployment identifier")
    deployment_url: Optional[str] = Field(None, description="URL where the deployment is accessible")
    logs: List[str] = Field(default_factory=list, description="Deployment logs")
    error: Optional[str] = Field(None, description="Error message if deployment failed")
    metadata: Dict = Field(default_factory=dict, description="Provider-specific metadata")


class BaseDeploymentProvider(ABC):
    """
    Abstract base class for deployment providers.

    All deployment providers (Cloudflare, Vercel, Netlify, etc.) must inherit from this class
    and implement the required abstract methods.
    """

    def __init__(self, credentials: Dict[str, str]):
        """
        Initialize the provider with credentials.

        Args:
            credentials: Provider-specific credentials (API tokens, account IDs, etc.)
        """
        self.credentials = credentials
        self.validate_credentials()

    @abstractmethod
    def validate_credentials(self) -> None:
        """
        Validate that all required credentials are present.

        Raises:
            ValueError: If required credentials are missing or invalid
        """
        pass

    @abstractmethod
    async def test_credentials(self) -> Dict:
        """
        Test if credentials are valid by making a real API call to the provider.

        This method should make an actual API request to verify the credentials work.

        Returns:
            Dictionary with validation result and provider info

        Raises:
            ValueError: If credentials are invalid or API call fails
        """
        pass

    @abstractmethod
    async def deploy(
        self,
        files: List[DeploymentFile],
        config: DeploymentConfig
    ) -> DeploymentResult:
        """
        Deploy application files to the provider.

        Args:
            files: List of files to deploy
            config: Deployment configuration

        Returns:
            DeploymentResult containing deployment information
        """
        pass

    @abstractmethod
    async def get_deployment_status(self, deployment_id: str) -> Dict:
        """
        Get the current status of a deployment.

        Args:
            deployment_id: Provider's deployment identifier

        Returns:
            Dictionary containing deployment status information
        """
        pass

    @abstractmethod
    async def delete_deployment(self, deployment_id: str) -> bool:
        """
        Delete a deployment.

        Args:
            deployment_id: Provider's deployment identifier

        Returns:
            True if deletion was successful, False otherwise
        """
        pass

    @abstractmethod
    async def get_deployment_logs(self, deployment_id: str) -> List[str]:
        """
        Fetch deployment logs from the provider.

        Args:
            deployment_id: Provider's deployment identifier

        Returns:
            List of log messages
        """
        pass

    async def collect_files_from_container(
        self,
        project_path: str,
        build_output_dir: str = "dist"
    ) -> List[DeploymentFile]:
        """
        Collect built files from project directory.

        This is a helper method that providers can use to gather files from
        the container's filesystem after a build.

        Args:
            project_path: Path to the project directory
            build_output_dir: Name of the build output directory

        Returns:
            List of DeploymentFile objects

        Raises:
            FileNotFoundError: If build output directory doesn't exist
        """
        files = []
        build_path = os.path.join(project_path, build_output_dir)

        if not os.path.exists(build_path):
            raise FileNotFoundError(f"Build output not found: {build_path}")

        for root, dirs, filenames in os.walk(build_path):
            # Skip common directories that shouldn't be deployed
            dirs[:] = [d for d in dirs if d not in {'.git', 'node_modules', '__pycache__', '.DS_Store'}]

            for filename in filenames:
                file_path = os.path.join(root, filename)
                relative_path = os.path.relpath(file_path, build_path)

                # Read file content
                with open(file_path, 'rb') as f:
                    content = f.read()

                files.append(DeploymentFile(
                    path=relative_path,
                    content=content
                ))

        return files

    def get_framework_config(self, framework: str) -> Dict:
        """
        Get framework-specific deployment configuration.

        Args:
            framework: Framework identifier

        Returns:
            Dictionary containing framework-specific build and deployment settings
        """
        configs = {
            "vite": {
                "build_command": "npm run build",
                "output_dir": "dist",
                "install_command": "npm install",
                "dev_command": "npm run dev"
            },
            "nextjs": {
                "build_command": "npm run build",
                "output_dir": ".next",
                "install_command": "npm install",
                "dev_command": "npm run dev",
                "requires_server": True
            },
            "react": {
                "build_command": "npm run build",
                "output_dir": "build",
                "install_command": "npm install",
                "dev_command": "npm start"
            },
            "vue": {
                "build_command": "npm run build",
                "output_dir": "dist",
                "install_command": "npm install",
                "dev_command": "npm run serve"
            },
            "svelte": {
                "build_command": "npm run build",
                "output_dir": "dist",
                "install_command": "npm install",
                "dev_command": "npm run dev"
            },
            "go": {
                "build_command": "go build -o main",
                "output_dir": ".",
                "install_command": "go mod download",
                "requires_server": True
            },
            "python": {
                "build_command": None,  # No build needed for Python apps
                "output_dir": ".",
                "install_command": "pip install -r requirements.txt",
                "requires_server": True
            }
        }

        return configs.get(framework.lower(), {
            "build_command": "npm run build",
            "output_dir": "dist",
            "install_command": "npm install",
            "dev_command": "npm run dev"
        })

    def _sanitize_name(self, name: str) -> str:
        """
        Sanitize a project name for use in deployment URLs.

        Args:
            name: Original project name

        Returns:
            Sanitized name (lowercase, alphanumeric + hyphens, max 63 chars)
        """
        import re
        # Convert to lowercase and replace spaces/underscores with hyphens
        name = name.lower().replace('_', '-').replace(' ', '-')
        # Remove invalid characters
        name = re.sub(r'[^a-z0-9-]', '', name)
        # Remove leading/trailing hyphens
        name = name.strip('-')
        # Limit length (DNS label limit)
        return name[:63]
