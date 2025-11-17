"""
Docker Compose Orchestrator for Multi-Container Projects

This service manages multi-container monorepo projects using Docker Compose.
It generates docker-compose.yml files dynamically from the Container database model.

Architecture:
- Each project gets its own Docker network (tesslate-{project_slug})
- Each base/container runs in isolation with its own service
- Containers can communicate via the shared network
- Dependencies are managed via depends_on relationships from ContainerConnections
- Backward compatible: single-container projects still use DevContainerManager
"""

import os
import yaml
import asyncio
import logging
from typing import Dict, List, Any, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

logger = logging.getLogger(__name__)


class DockerComposeOrchestrator:
    """
    Orchestrates multi-container projects using Docker Compose.

    Generates docker-compose.yml from Container database models and manages
    the lifecycle of all containers in a project as a single unit.
    """

    def __init__(self):
        self.compose_files_dir = os.path.abspath("docker-compose-projects")
        os.makedirs(self.compose_files_dir, exist_ok=True)
        logger.info(f"[COMPOSE] Docker Compose orchestrator initialized")
        logger.info(f"[COMPOSE] Compose files directory: {self.compose_files_dir}")

    def _get_compose_file_path(self, project_slug: str) -> str:
        """Get the path to the docker-compose.yml file for a project."""
        return os.path.join(self.compose_files_dir, f"{project_slug}.yml")

    async def generate_compose_config(
        self,
        project,
        containers: List,
        connections: List,
        user_id: UUID
    ) -> Dict[str, Any]:
        """
        Generate docker-compose.yml configuration from Container models.

        Args:
            project: Project database model
            containers: List of Container models for this project
            connections: List of ContainerConnection models
            user_id: User ID (for volume paths)

        Returns:
            Docker Compose configuration dictionary
        """
        # Create project-specific network
        network_name = f"tesslate-{project.slug}"

        # Base compose config
        compose_config = {
            'version': '3.8',
            'networks': {
                network_name: {
                    'driver': 'bridge',
                    'name': network_name
                }
            },
            'services': {}
        }

        # Build dependency map from connections
        dependencies_map = {}  # container_id -> [dependent_container_ids]
        for connection in connections:
            if connection.connection_type == "depends_on":
                target_id = str(connection.target_container_id)
                source_id = str(connection.source_container_id)

                if source_id not in dependencies_map:
                    dependencies_map[source_id] = []
                dependencies_map[source_id].append(target_id)

        # Generate service definitions for each container
        for container in containers:
            container_id = str(container.id)

            # Determine base image
            # TODO: Get actual image from MarketplaceBase
            base_image = "tesslate-devserver:latest"  # Default fallback

            # Build volume mounts
            project_dir = f"users/{user_id}/{project.id}"
            container_dir = container.directory
            volumes = [
                f"./{project_dir}/{container_dir}:/app",
                # Mount node_modules as named volume to avoid conflicts
                f"{project.slug}-{container.name}-node_modules:/app/node_modules"
            ]

            # Build environment variables
            environment = container.environment_vars or {}
            environment.update({
                'PROJECT_ID': str(project.id),
                'CONTAINER_ID': str(container.id),
                'CONTAINER_NAME': container.name,
            })

            # Add port if specified
            ports = []
            if container.port and container.internal_port:
                ports.append(f"{container.port}:{container.internal_port}")

            # Build depends_on from connections
            depends_on = []
            if container_id in dependencies_map:
                # Get container names for dependencies
                for dep_id in dependencies_map[container_id]:
                    dep_container = next(
                        (c for c in containers if str(c.id) == dep_id),
                        None
                    )
                    if dep_container:
                        depends_on.append(dep_container.name)

            # Add Traefik labels for routing
            labels = {
                'traefik.enable': 'true',
                f'traefik.http.routers.{container.container_name}.rule':
                    f'Host(`{container.container_name}.localhost`)',
                f'traefik.http.services.{container.container_name}.loadbalancer.server.port':
                    str(container.internal_port or 5173),
                'com.tesslate.project': project.slug,
                'com.tesslate.container': container.name,
                'com.tesslate.user': str(user_id),
            }

            # Build service definition
            service_config = {
                'image': base_image,
                'container_name': container.container_name,
                'networks': [network_name],
                'volumes': volumes,
                'environment': environment,
                'labels': labels,
                'restart': 'unless-stopped',
                'command': 'npm run dev'  # Default command, should be configurable
            }

            if ports:
                service_config['ports'] = ports

            if depends_on:
                service_config['depends_on'] = depends_on

            # Add to services
            compose_config['services'][container.name] = service_config

        # Add named volumes for node_modules
        compose_config['volumes'] = {}
        for container in containers:
            volume_name = f"{project.slug}-{container.name}-node_modules"
            compose_config['volumes'][volume_name] = {
                'driver': 'local'
            }

        return compose_config

    async def write_compose_file(
        self,
        project,
        containers: List,
        connections: List,
        user_id: UUID
    ) -> str:
        """
        Generate and write docker-compose.yml file for a project.

        Returns:
            Path to the generated docker-compose.yml file
        """
        compose_config = await self.generate_compose_config(
            project, containers, connections, user_id
        )

        compose_file_path = self._get_compose_file_path(project.slug)

        # Write to file with proper YAML formatting
        with open(compose_file_path, 'w') as f:
            yaml.dump(compose_config, f, default_flow_style=False, sort_keys=False)

        logger.info(f"[COMPOSE] Generated docker-compose.yml for project {project.slug}")
        logger.info(f"[COMPOSE] File path: {compose_file_path}")
        logger.info(f"[COMPOSE] Services: {', '.join(compose_config['services'].keys())}")

        return compose_file_path

    async def start_project(
        self,
        project,
        containers: List,
        connections: List,
        user_id: UUID
    ) -> Dict[str, Any]:
        """
        Start all containers for a project using Docker Compose.

        Args:
            project: Project model
            containers: List of Container models
            connections: List of ContainerConnection models
            user_id: User ID

        Returns:
            Dictionary with status and container URLs
        """
        # Generate compose file
        compose_file_path = await self.write_compose_file(
            project, containers, connections, user_id
        )

        # Run docker-compose up
        logger.info(f"[COMPOSE] Starting project {project.slug}...")

        try:
            process = await asyncio.create_subprocess_exec(
                'docker-compose',
                '-f', compose_file_path,
                '-p', project.slug,  # Project name for isolation
                'up', '-d',  # Detached mode
                '--remove-orphans',  # Clean up old containers
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                logger.error(f"[COMPOSE] Failed to start project: {error_msg}")
                raise RuntimeError(f"Docker Compose failed: {error_msg}")

            logger.info(f"[COMPOSE] ✅ Project {project.slug} started successfully")

            # Build container URLs
            container_urls = {}
            for container in containers:
                url = f"http://{container.container_name}.localhost"
                container_urls[container.name] = url

            return {
                'status': 'running',
                'project_slug': project.slug,
                'network': f"tesslate-{project.slug}",
                'containers': container_urls,
                'compose_file': compose_file_path
            }

        except Exception as e:
            logger.error(f"[COMPOSE] Error starting project: {e}", exc_info=True)
            raise

    async def stop_project(self, project_slug: str) -> None:
        """
        Stop all containers for a project using Docker Compose.

        Args:
            project_slug: Project slug
        """
        compose_file_path = self._get_compose_file_path(project_slug)

        if not os.path.exists(compose_file_path):
            logger.warning(f"[COMPOSE] Compose file not found for {project_slug}")
            return

        logger.info(f"[COMPOSE] Stopping project {project_slug}...")

        try:
            process = await asyncio.create_subprocess_exec(
                'docker-compose',
                '-f', compose_file_path,
                '-p', project_slug,
                'down',
                '--remove-orphans',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                logger.error(f"[COMPOSE] Failed to stop project: {error_msg}")
                raise RuntimeError(f"Docker Compose failed: {error_msg}")

            logger.info(f"[COMPOSE] ✅ Project {project_slug} stopped successfully")

        except Exception as e:
            logger.error(f"[COMPOSE] Error stopping project: {e}", exc_info=True)
            raise

    async def restart_project(
        self,
        project,
        containers: List,
        connections: List,
        user_id: UUID
    ) -> Dict[str, Any]:
        """
        Restart all containers for a project.
        """
        await self.stop_project(project.slug)
        return await self.start_project(project, containers, connections, user_id)

    async def get_project_status(self, project_slug: str) -> Dict[str, Any]:
        """
        Get status of all containers in a project.

        Returns:
            Dictionary with container statuses
        """
        compose_file_path = self._get_compose_file_path(project_slug)

        if not os.path.exists(compose_file_path):
            return {
                'status': 'not_found',
                'containers': {}
            }

        try:
            # Run docker-compose ps
            process = await asyncio.create_subprocess_exec(
                'docker-compose',
                '-f', compose_file_path,
                '-p', project_slug,
                'ps', '--format', 'json',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                return {
                    'status': 'error',
                    'error': stderr.decode() if stderr else "Unknown error"
                }

            # Parse JSON output
            import json
            containers_status = {}

            if stdout:
                # docker-compose ps --format json outputs one JSON object per line
                for line in stdout.decode().strip().split('\n'):
                    if line:
                        container_info = json.loads(line)
                        containers_status[container_info['Service']] = {
                            'name': container_info['Name'],
                            'state': container_info['State'],
                            'status': container_info['Status'],
                            'running': container_info['State'] == 'running'
                        }

            all_running = all(
                info['running'] for info in containers_status.values()
            ) if containers_status else False

            return {
                'status': 'running' if all_running else 'partial',
                'containers': containers_status,
                'project_slug': project_slug
            }

        except Exception as e:
            logger.error(f"[COMPOSE] Error getting status: {e}", exc_info=True)
            return {
                'status': 'error',
                'error': str(e)
            }

    async def start_container(
        self,
        project_slug: str,
        container_name: str
    ) -> None:
        """
        Start a specific container in a project.

        Args:
            project_slug: Project slug
            container_name: Container/service name
        """
        compose_file_path = self._get_compose_file_path(project_slug)

        if not os.path.exists(compose_file_path):
            raise FileNotFoundError(f"Compose file not found for {project_slug}")

        logger.info(f"[COMPOSE] Starting container {container_name} in {project_slug}...")

        process = await asyncio.create_subprocess_exec(
            'docker-compose',
            '-f', compose_file_path,
            '-p', project_slug,
            'start', container_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise RuntimeError(f"Failed to start container: {error_msg}")

        logger.info(f"[COMPOSE] ✅ Container {container_name} started")

    async def stop_container(
        self,
        project_slug: str,
        container_name: str
    ) -> None:
        """
        Stop a specific container in a project.

        Args:
            project_slug: Project slug
            container_name: Container/service name
        """
        compose_file_path = self._get_compose_file_path(project_slug)

        if not os.path.exists(compose_file_path):
            raise FileNotFoundError(f"Compose file not found for {project_slug}")

        logger.info(f"[COMPOSE] Stopping container {container_name} in {project_slug}...")

        process = await asyncio.create_subprocess_exec(
            'docker-compose',
            '-f', compose_file_path,
            '-p', project_slug,
            'stop', container_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise RuntimeError(f"Failed to stop container: {error_msg}")

        logger.info(f"[COMPOSE] ✅ Container {container_name} stopped")


# Singleton instance
_compose_orchestrator: Optional[DockerComposeOrchestrator] = None


def get_compose_orchestrator() -> DockerComposeOrchestrator:
    """Get the singleton Docker Compose orchestrator instance."""
    global _compose_orchestrator

    if _compose_orchestrator is None:
        _compose_orchestrator = DockerComposeOrchestrator()

    return _compose_orchestrator
