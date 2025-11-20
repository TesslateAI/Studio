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

    def __init__(self, use_volumes: bool = True):
        self.compose_files_dir = os.path.abspath("docker-compose-projects")
        os.makedirs(self.compose_files_dir, exist_ok=True)
        self.host_users_base = self._detect_host_users_path()
        self.use_volumes = use_volumes  # Feature flag: True = volumes, False = bind mounts
        logger.info(f"[COMPOSE] Docker Compose orchestrator initialized")
        logger.info(f"[COMPOSE] Storage mode: {'VOLUMES' if use_volumes else 'BIND_MOUNTS'}")
        logger.info(f"[COMPOSE] Compose files directory: {self.compose_files_dir}")
        if not use_volumes:
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
                },
                # Regional Traefik network for routing (external - created by regional_traefik_manager)
                'tesslate-regional-traefik-network': {
                    'external': True
                }
            },
            'services': {},
            'volumes': {}  # Initialize volumes dict for service containers
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

            # Handle service containers differently from base containers
            if container.container_type == "service":
                # Service container (Postgres, Redis, etc.)
                from ..services.service_definitions import get_service

                service_def = get_service(container.service_slug)
                if not service_def:
                    logger.error(f"[COMPOSE] Service '{container.service_slug}' not found, skipping")
                    continue

                # Build service configuration from service definition
                sanitized_container_name = f"{project.slug}-{service_name}"

                # Create volume for service data persistence
                service_volume_name = f"{project.slug}-{container.service_slug}-data"

                # Build volume mounts from service definition
                volume_mounts = []
                for volume_path in service_def.volumes:
                    volume_mounts.append(f"{service_volume_name}:{volume_path}")

                # Build environment from service definition
                environment = service_def.environment_vars.copy()

                # Add Traefik labels only if service has HTTP port (databases usually don't)
                labels = {
                    'com.tesslate.project': project.slug,
                    'com.tesslate.container': container.name,
                    'com.tesslate.user': str(user_id),
                    'com.tesslate.service': container.service_slug,
                }

                # Only add Traefik routing for HTTP services (not databases)
                if service_def.category in ["proxy", "storage", "search"]:
                    labels.update({
                        'traefik.enable': 'true',
                        f'traefik.http.routers.{sanitized_container_name}.rule':
                            f'Host(`{sanitized_container_name}.localhost`)',
                        f'traefik.http.services.{sanitized_container_name}.loadbalancer.server.port':
                            str(service_def.internal_port),
                    })
                else:
                    labels['traefik.enable'] = 'false'

                # Build service definition for service container
                service_config = {
                    'image': service_def.docker_image,
                    'container_name': sanitized_container_name,
                    'networks': [network_name],  # Services only need project network
                    'volumes': volume_mounts,
                    'environment': environment,
                    'labels': labels,
                    'restart': 'unless-stopped',
                }

                # Add command if specified
                if service_def.command:
                    service_config['command'] = service_def.command

                # Add health check if specified
                if service_def.health_check:
                    service_config['healthcheck'] = service_def.health_check

                compose_config['services'][service_name] = service_config
                logger.info(f"[COMPOSE] Added service container: {container.service_slug}")

                # Declare service volume
                if service_volume_name not in compose_config['volumes']:
                    compose_config['volumes'][service_volume_name] = {
                        'name': service_volume_name,
                    }

                continue  # Skip the base container logic below

            # Base container logic (original code)
            # Use tesslate-devserver which has Node.js, Python, Go pre-installed
            # Working directory is set to /app below, not /template (where Vite template lives)
            base_image = "tesslate-devserver:latest"

            # Build volume mounts (use project-level volume shared by all containers)
            if self.use_volumes:
                # Use project-level volume (all containers share the same volume)
                volume_name = project.volume_name or container.volume_name or f"{project.slug}"

                if not project.volume_name:
                    logger.warning(f"[COMPOSE] Project {project.slug} missing volume_name, using: {volume_name}")

                volumes = [
                    f"{volume_name}:/app",
                ]
            else:
                # LEGACY: Use bind mounts (slow on WSL, kept for backward compatibility)
                project_dir = f"users/{user_id}/{project.id}"
                container_dir = container.directory
                container_path = f"/app/{project_dir}/{container_dir}"
                host_path = self._convert_to_host_path(container_path)

                volumes = [
                    f"{host_path}:/app",
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

            # Generate startup command and read port config (ROBUST & SECURE)
            # Priority:
            # 1. Try reading TESSLATE.md from volume (custom user repos)
            # 2. Try reading TESSLATE.md from cache (marketplace bases)
            # 3. Use safe generic fallback
            from ..services.base_config_parser import (
                get_base_config_from_volume,
                get_base_config_from_cache,
                generate_startup_command
            )

            base_config = None

            # Try volume first (supports custom user repos)
            if container.volume_name:
                try:
                    base_config = await get_base_config_from_volume(container.volume_name)
                except Exception as e:
                    logger.debug(f"[COMPOSE] Could not read config from volume: {e}")

            # Try cache if no volume config (marketplace bases)
            if not base_config and container.base:
                try:
                    base_slug = container.base.slug
                    base_config = await asyncio.to_thread(get_base_config_from_cache, base_slug)
                except Exception as e:
                    logger.debug(f"[COMPOSE] Could not read config from cache: {e}")

            # Determine port (priority: TESSLATE.md > container.internal_port > default 3000)
            container_port = 3000  # Generic default
            if base_config and base_config.port:
                container_port = base_config.port
                logger.info(f"[COMPOSE] Using port from TESSLATE.md: {container_port}")
            elif container.internal_port:
                container_port = container.internal_port
                logger.info(f"[COMPOSE] Using port from database: {container_port}")

            # Add Traefik labels for routing
            labels = {
                'traefik.enable': 'true',
                f'traefik.http.routers.{sanitized_container_name}.rule':
                    f'Host(`{sanitized_container_name}.localhost`)',
                f'traefik.http.services.{sanitized_container_name}.loadbalancer.server.port':
                    str(container_port),
                # Traefik will discover on project network (dynamically connected)
                'com.tesslate.project': project.slug,
                'com.tesslate.container': container.name,
                'com.tesslate.user': str(user_id),
            }

            # Determine working directory (for multi-directory projects like vite-react-fastapi)
            working_dir = '/app'  # Default for single-directory projects
            if base_config and base_config.structure_type == "multi":
                # Multi-directory project: detect subdirectory from container name
                container_name_lower = container.name.lower()
                if 'frontend' in container_name_lower or 'client' in container_name_lower:
                    working_dir = '/app/frontend'
                elif 'backend' in container_name_lower or 'server' in container_name_lower or 'api' in container_name_lower:
                    working_dir = '/app/backend'
                logger.info(f"[COMPOSE] Multi-directory project detected, working_dir: {working_dir}")

            # Generate command (uses validated custom or safe default)
            startup_command = generate_startup_command(base_config)
            logger.info(f"[COMPOSE] Generated startup command for {container.name}")

            # Build service definition
            service_config = {
                'image': base_image,
                'container_name': sanitized_container_name,
                'user': '1000:1000',  # SECURITY: Run as non-root user (permissions fixed on host)
                'working_dir': working_dir,  # Dynamic: /app for single-dir, /app/frontend or /app/backend for multi-dir
                # Connect to both project network AND regional Traefik network for routing
                'networks': [network_name, 'tesslate-regional-traefik-network'],
                'volumes': volumes,
                'environment': environment,
                'labels': labels,
                'restart': 'unless-stopped',
                'command': startup_command,  # DYNAMIC: Reads from TESSLATE.md with security validation
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

        # Add project-level volume if using Docker volumes
        if self.use_volumes:
            # Declare project-level volume (shared by all base containers)
            # Don't overwrite volumes dict - service volumes may already be added
            if project.volume_name:
                compose_config['volumes'][project.volume_name] = {
                    'name': project.volume_name,
                    # Use local driver (default)
                    # Future: could use NFS, Ceph, cloud storage drivers
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
        # Feature flag: USE_DOCKER_VOLUMES (default: True)
        # Set to False for backward compatibility with bind mounts
        use_volumes = os.getenv('USE_DOCKER_VOLUMES', 'true').lower() == 'true'
        _compose_orchestrator = DockerComposeOrchestrator(use_volumes=use_volumes)

    return _compose_orchestrator
