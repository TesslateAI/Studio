"""
Docker Compose Orchestrator for Multi-Container Projects

This service manages multi-container monorepo projects using Docker Compose.
It generates docker-compose.yml files dynamically from the Container database model.

Architecture:
- Each project gets its own isolated network: tesslate-{project_slug}
- Containers ONLY on their project network for complete isolation
- Traefik is dynamically connected to project networks when containers start
- Traefik disconnected from project networks when containers stop
- This ensures: Projects cannot see each other, Traefik can route to all
- Security: extra_hosts blocks access to internal services (orchestrator, postgres, redis)
- Dependencies are managed via depends_on relationships from ContainerConnections
- Backward compatible: single-container projects still use DevContainerManager
"""

import os
import yaml
import asyncio
import logging
import json
import socket
import subprocess
from typing import Dict, List, Any, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from .regional_traefik_manager import get_regional_traefik_manager

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
        self.host_users_base = self._detect_host_users_path()
        logger.info(f"[COMPOSE] Docker Compose orchestrator initialized")
        logger.info(f"[COMPOSE] Compose files directory: {self.compose_files_dir}")
        logger.info(f"[COMPOSE] Host users base path: {self.host_users_base}")

    def _detect_host_users_path(self) -> str:
        """
        Detect the host path for /app/users by inspecting the orchestrator container.
        This is needed for Docker-in-Docker volume mounts.
        """
        # Check if we're running in a container
        if os.path.exists('/.dockerenv'):
            try:
                # Get all mounts for this container
                result = subprocess.run(
                    ["docker", "inspect", "-f", "{{ json .Mounts }}", socket.gethostname()],
                    capture_output=True,
                    text=True,
                    timeout=3
                )

                if result.returncode == 0 and result.stdout.strip():
                    mounts = json.loads(result.stdout.strip())

                    # Find the /app/users mount
                    for mount in mounts:
                        if mount.get('Destination') == '/app/users':
                            users_mount = mount.get('Source')
                            logger.info(f"[COMPOSE] Detected /app/users mount: {users_mount}")
                            return users_mount

                    # Fallback if /app/users mount not found
                    fallback = "/root/Tesslate-Studio/orchestrator/users"
                    logger.warning(f"[COMPOSE] Could not detect /app/users mount, using fallback: {fallback}")
                    return fallback
                else:
                    fallback = "/root/Tesslate-Studio/orchestrator/users"
                    logger.warning(f"[COMPOSE] Docker inspect failed, using fallback: {fallback}")
                    return fallback

            except Exception as e:
                fallback = "/root/Tesslate-Studio/orchestrator/users"
                logger.warning(f"[COMPOSE] Error detecting host paths: {e}, using fallback: {fallback}")
                return fallback
        else:
            # Not in a container - paths are already host paths
            host_path = os.path.abspath("users")
            logger.info(f"[COMPOSE] Running on host, users base: {host_path}")
            return host_path

    def _convert_to_host_path(self, container_path: str) -> str:
        """
        Convert a container path to the corresponding host path for Docker-in-Docker.
        Converts /app/users/... to the actual host path.
        """
        if container_path.startswith('/app/users/'):
            # Extract the relative path after /app/users/
            relative_path = container_path[11:]  # Remove '/app/users/'
            host_path = os.path.join(self.host_users_base, relative_path)
            logger.debug(f"[COMPOSE] Converted path: {container_path} -> {host_path}")
            return host_path
        else:
            # Path doesn't start with /app/users, return as-is
            return container_path

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
        # Create project-specific network for complete isolation
        network_name = f"tesslate-{project.slug}"

        # Base compose config with ONLY project-specific network
        compose_config = {
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

            # Sanitize service name (docker-compose doesn't allow spaces or special chars)
            service_name = container.name.lower().replace(' ', '-').replace('_', '-').replace('.', '-')
            # Remove any remaining invalid characters
            service_name = ''.join(c for c in service_name if c.isalnum() or c == '-')

            # Use tesslate-devserver which has Node.js, Python, Go pre-installed
            # Working directory is set to /app below, not /template (where Vite template lives)
            base_image = "tesslate-devserver:latest"

            # Build volume mounts
            project_dir = f"users/{user_id}/{project.id}"
            container_dir = container.directory

            # Convert container path to host path for Docker-in-Docker
            container_path = f"/app/{project_dir}/{container_dir}"
            host_path = self._convert_to_host_path(container_path)

            volumes = [
                f"{host_path}:/app",
                # No separate node_modules volume - let it live in the mounted directory
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
                # Get container names for dependencies (sanitized)
                for dep_id in dependencies_map[container_id]:
                    dep_container = next(
                        (c for c in containers if str(c.id) == dep_id),
                        None
                    )
                    if dep_container:
                        # Sanitize dependency service name
                        dep_service_name = dep_container.name.lower().replace(' ', '-').replace('_', '-').replace('.', '-')
                        dep_service_name = ''.join(c for c in dep_service_name if c.isalnum() or c == '-')
                        depends_on.append(dep_service_name)

            # Create sanitized container name (Docker doesn't allow spaces)
            sanitized_container_name = f"{project.slug}-{service_name}"

            # Add Traefik labels for routing
            labels = {
                'traefik.enable': 'true',
                f'traefik.http.routers.{sanitized_container_name}.rule':
                    f'Host(`{sanitized_container_name}.localhost`)',
                f'traefik.http.services.{sanitized_container_name}.loadbalancer.server.port':
                    str(container.internal_port or 5173),
                # Traefik will discover on project network (dynamically connected)
                'com.tesslate.project': project.slug,
                'com.tesslate.container': container.name,
                'com.tesslate.user': str(user_id),
            }

            # Build service definition
            service_config = {
                'image': base_image,
                'container_name': sanitized_container_name,
                'user': '1000:1000',  # SECURITY: Run as non-root user (permissions fixed on host)
                'working_dir': '/app',  # CRITICAL: Run in /app where user code is mounted, not /template
                'networks': [network_name],  # ONLY project network - Traefik connects dynamically
                'volumes': volumes,
                'environment': environment,
                'labels': labels,
                'restart': 'unless-stopped',
                # Install dependencies then run dev server (runs as user 1000)
                'command': ['sh', '-c', 'npm install && npm run dev'],
                # Security: Block access to internal Tesslate services
                'extra_hosts': [
                    'tesslate-orchestrator:127.0.0.1',  # Redirect to container's own localhost
                    'tesslate-postgres:127.0.0.1',
                    'tesslate-redis:127.0.0.1',
                    'postgres:127.0.0.1',  # Block shortname too
                    'redis:127.0.0.1'
                ]
            }

            if ports:
                service_config['ports'] = ports

            if depends_on:
                service_config['depends_on'] = depends_on

            # Add to services (use sanitized service name)
            compose_config['services'][service_name] = service_config

        # No named volumes needed - node_modules lives in mounted directory
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
        # Use width=1000000 to prevent line wrapping in long strings (volume paths)
        with open(compose_file_path, 'w') as f:
            yaml.dump(compose_config, f, default_flow_style=False, sort_keys=False, width=1000000)

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
                'docker', 'compose',  # Use docker compose v2
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

            # Connect REGIONAL Traefik to project network for routing
            network_name = f"tesslate-{project.slug}"
            regional_manager = get_regional_traefik_manager()

            # Ensure appropriate regional Traefik is running
            regional_index = await regional_manager.ensure_regional_for_project(project.slug)
            regional_traefik_name = regional_manager.get_regional_traefik_name(regional_index)

            logger.info(f"[COMPOSE] Connecting {regional_traefik_name} to network {network_name}...")

            try:
                connect_process = await asyncio.create_subprocess_exec(
                    'docker', 'network', 'connect', network_name, regional_traefik_name,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await connect_process.communicate()

                if connect_process.returncode == 0:
                    logger.info(f"[COMPOSE] ✅ {regional_traefik_name} connected to {network_name}")
                    logger.info(f"[COMPOSE] Project assigned to regional Traefik #{regional_index}")
                else:
                    # Already connected is not an error
                    logger.debug(f"[COMPOSE] {regional_traefik_name} already connected to {network_name}")
            except Exception as e:
                logger.warning(f"[COMPOSE] Failed to connect regional Traefik to network: {e}")

            # Build container URLs (use sanitized names)
            container_urls = {}
            for container in containers:
                # Sanitize container name for URL (same logic as in compose config)
                service_name = container.name.lower().replace(' ', '-').replace('_', '-').replace('.', '-')
                service_name = ''.join(c for c in service_name if c.isalnum() or c == '-')
                sanitized_container_name = f"{project.slug}-{service_name}"
                url = f"http://{sanitized_container_name}.localhost"
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
                'docker', 'compose',  # Use docker compose v2
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

            # Disconnect Traefik from project network
            network_name = f"tesslate-{project_slug}"
            logger.info(f"[COMPOSE] Disconnecting Traefik from network {network_name}...")

            try:
                disconnect_process = await asyncio.create_subprocess_exec(
                    'docker', 'network', 'disconnect', network_name, 'tesslate-traefik',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await disconnect_process.communicate()

                if disconnect_process.returncode == 0:
                    logger.info(f"[COMPOSE] ✅ Traefik disconnected from {network_name}")
                else:
                    # Not connected is not an error
                    logger.debug(f"[COMPOSE] Traefik was not connected to {network_name}")
            except Exception as e:
                logger.warning(f"[COMPOSE] Failed to disconnect Traefik from network: {e}")

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
            # Run docker compose ps
            process = await asyncio.create_subprocess_exec(
                'docker', 'compose',  # Use docker compose v2
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
            container_name: Container/service name (will be sanitized)
        """
        compose_file_path = self._get_compose_file_path(project_slug)

        if not os.path.exists(compose_file_path):
            raise FileNotFoundError(f"Compose file not found for {project_slug}")

        # Sanitize service name (same logic as in generate_compose_config)
        service_name = container_name.lower().replace(' ', '-').replace('_', '-').replace('.', '-')
        service_name = ''.join(c for c in service_name if c.isalnum() or c == '-')

        logger.info(f"[COMPOSE] Starting container {container_name} (service: {service_name}) in {project_slug}...")

        process = await asyncio.create_subprocess_exec(
            'docker', 'compose',  # Use docker compose v2
            '-f', compose_file_path,
            '-p', project_slug,
            'up', '-d', service_name,  # Use 'up -d' to create and start
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise RuntimeError(f"Failed to start container: {error_msg}")

        logger.info(f"[COMPOSE] ✅ Container {container_name} started")

        # Connect REGIONAL Traefik to project network for routing (if not already connected)
        network_name = f"tesslate-{project_slug}"
        regional_manager = get_regional_traefik_manager()

        # Ensure appropriate regional Traefik is running
        regional_index = await regional_manager.ensure_regional_for_project(project_slug)
        regional_traefik_name = regional_manager.get_regional_traefik_name(regional_index)

        logger.info(f"[COMPOSE] Connecting {regional_traefik_name} to network {network_name}...")

        try:
            connect_process = await asyncio.create_subprocess_exec(
                'docker', 'network', 'connect', network_name, regional_traefik_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await connect_process.communicate()

            if connect_process.returncode == 0:
                logger.info(f"[COMPOSE] ✅ {regional_traefik_name} connected to {network_name}")
            else:
                # Already connected is not an error
                logger.debug(f"[COMPOSE] {regional_traefik_name} already connected to {network_name}")
        except Exception as e:
            logger.warning(f"[COMPOSE] Failed to connect regional Traefik to network: {e}")

    async def stop_container(
        self,
        project_slug: str,
        container_name: str
    ) -> None:
        """
        Stop a specific container in a project.

        Args:
            project_slug: Project slug
            container_name: Container/service name (will be sanitized)
        """
        compose_file_path = self._get_compose_file_path(project_slug)

        if not os.path.exists(compose_file_path):
            raise FileNotFoundError(f"Compose file not found for {project_slug}")

        # Sanitize service name (same logic as in generate_compose_config)
        service_name = container_name.lower().replace(' ', '-').replace('_', '-').replace('.', '-')
        service_name = ''.join(c for c in service_name if c.isalnum() or c == '-')

        logger.info(f"[COMPOSE] Stopping container {container_name} (service: {service_name}) in {project_slug}...")

        process = await asyncio.create_subprocess_exec(
            'docker', 'compose',  # Use docker compose v2
            '-f', compose_file_path,
            '-p', project_slug,
            'stop', service_name,  # Use sanitized service name
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
