import asyncio
import os
import time
from typing import Dict, Optional, List, Any
from uuid import UUID
from .config import get_settings
from .deprecated_k8s_client import get_k8s_manager
import logging

logger = logging.getLogger(__name__)


class KubernetesContainerManager:
    """
    Kubernetes-native development environment manager for multi-user, multi-project environments.
    - Uses Kubernetes Deployments, Services, and Ingresses for isolation
    - Automatic HTTPS hostnames with authentication
    - Resource limits and security controls
    - Production-ready scaling and monitoring
    """
    
    def __init__(self):
        self.environments: Dict[str, Dict[str, Any]] = {}  # project_key -> {hostname, user_id, project_id, status}
        self.activity_tracker: Dict[str, float] = {}  # project_key -> last_activity_timestamp
        self.paused_at_tracker: Dict[str, float] = {}  # project_key -> paused_timestamp (for two-tier cleanup)

        logger.info("DevContainerManager initialized - Kubernetes-native architecture with NGINX Ingress")
        # K8s manager will be lazily initialized on first use
    
    def _get_project_key(self, user_id: UUID, project_id: str) -> str:
        """Generate a unique project key for environment management."""
        return f"user-{user_id}-project-{project_id}"
    
    def _get_container_access_url(self, hostname: str) -> str:
        """Get the access URL for a development environment."""
        # Always use HTTPS for production Kubernetes environments
        return f"https://{hostname}"
    
    
    
    
    
    
    
    
    
    
    
    
    async def start_container(self, project_path: str, project_id: str, user_id: UUID, project_slug: str = None, **kwargs) -> str:
        """
        Start a development environment using Kubernetes resources.

        Args:
            project_path: Path to project directory (for reference)
            project_id: Project ID (for internal naming)
            user_id: User ID
            project_slug: Project slug for URL generation (e.g., "my-app-k3x8n2")
            **kwargs: Additional arguments (for compatibility)

        In Kubernetes, the project directory is on the shared PVC, not on the backend pod's filesystem.
        The K8s init container will handle copying template files to the PVC if needed.
        """
        project_key = self._get_project_key(user_id, project_id)

        logger.info(f"[START] Starting development environment for user {user_id}, project {project_slug or project_id} (ID: {project_id})")
        logger.info(f"[START] Project key: {project_key}")
        logger.info(f"[START] Project path (for reference): {project_path}")

        try:
            # Stop existing environment for this user and project
            logger.info(f"[START] Checking for existing environment to stop...")
            await self.stop_container(project_id, user_id)

            # Create Kubernetes development environment
            # The K8s init container will copy template files to the shared PVC
            # The dev container will then mount that directory via subPath
            logger.info(f"[START] Creating Kubernetes resources (Deployment, Service, Ingress)...")
            environment_info = await get_k8s_manager().create_dev_environment(
                user_id=user_id,
                project_id=project_id,
                project_path=project_path,  # Used only for metadata, not file operations
                project_slug=project_slug
            )

            # Store environment info
            self.environments[project_key] = {
                "hostname": environment_info["hostname"],
                "url": environment_info["url"],
                "user_id": user_id,
                "project_id": project_id,
                "deployment_name": environment_info["deployment_name"],
                "service_name": environment_info["service_name"],
                "ingress_name": environment_info["ingress_name"],
                "status": environment_info["status"]
            }

            logger.info(f"[START] ✅ Development environment ready for user {user_id}, project {project_id}!")
            logger.info(f"[START] Access URL: {environment_info['url']}")
            logger.info(f"[START] Hot reload active - edit files and see changes instantly!")

            return environment_info["url"]

        except Exception as e:
            logger.error(f"[START] ❌ Failed to start development environment: {e}", exc_info=True)

            # Cleanup on failure
            try:
                await self.stop_container(project_id, user_id)
            except Exception as cleanup_error:
                logger.error(f"[START] Error during cleanup: {cleanup_error}", exc_info=True)

            raise RuntimeError(f"Failed to start development environment for user {user_id}, project {project_id}: {str(e)}")
    
    
    async def stop_container(self, project_id: str, user_id: UUID = None) -> None:
        """Stop and remove a development environment with multi-user support."""
        if user_id is None:
            logger.warning(f"Stop container called without user_id for project {project_id}")
            return

        project_key = self._get_project_key(user_id, project_id)

        logger.info(f"Stopping development environment for user {user_id}, project {project_id}")
        logger.debug(f"Looking for environment with key: {project_key}")

        try:
            # Delete Kubernetes resources
            await get_k8s_manager().delete_dev_environment(user_id, project_id)
            logger.info(f"Kubernetes resources deleted for user {user_id}, project {project_id}")

        except Exception as e:
            logger.warning(f"Error deleting Kubernetes resources: {e}")

        # Clean up local tracking
        if project_key in self.environments:
            environment_info = self.environments.pop(project_key)
            logger.info(f"Cleaned up environment tracking: {environment_info.get('hostname')}")
        else:
            logger.debug(f"No environment found with key: {project_key}")
            logger.debug(f"Available environments: {list(self.environments.keys())}")
    
    async def restart_container(self, project_path: str, project_id: str, user_id: UUID) -> str:
        """Restart a development environment with multi-user support."""
        logger.info(f"Restarting development environment for user {user_id}, project {project_id}")
        await self.stop_container(project_id, user_id)
        return await self.start_container(project_path, project_id, user_id)
    
    def get_container_url(self, project_id: str, user_id: UUID = None) -> Optional[str]:
        """Get the URL for a project's development environment with multi-user support."""
        if user_id is None:
            return None

        project_key = self._get_project_key(user_id, project_id)

        if project_key in self.environments:
            environment_info = self.environments[project_key]
            return environment_info.get("url")

        return None
    
    async def get_container_status(self, project_id: str, user_id: UUID = None) -> Dict[str, Any]:
        """Get detailed status of a development environment with multi-user support."""
        if user_id is None:
            return {"status": "not_found", "running": False}

        project_key = self._get_project_key(user_id, project_id)

        # Check local tracking first
        if project_key in self.environments:
            environment_info = self.environments[project_key]

            try:
                # Get live status from Kubernetes
                k8s_status = await get_k8s_manager().get_dev_environment_status(user_id, project_id)

                # Merge local info with K8s status
                return {
                    "status": k8s_status.get("status", "unknown"),
                    "running": k8s_status.get("deployment_ready", False),
                    "hostname": environment_info.get("hostname"),
                    "url": environment_info.get("url"),
                    "user_id": user_id,
                    "project_id": project_id,
                    "deployment_name": environment_info.get("deployment_name"),
                    "replicas": k8s_status.get("replicas", {}),
                    "pods": k8s_status.get("pods", [])
                }

            except Exception as e:
                logger.error(f"Error getting K8s status: {e}")
                return {
                    "status": "error",
                    "running": False,
                    "error": str(e),
                    "hostname": environment_info.get("hostname"),
                    "url": environment_info.get("url")
                }

        # Not in local tracking, check Kubernetes directly
        try:
            k8s_status = await get_k8s_manager().get_dev_environment_status(user_id, project_id)
            return k8s_status
        except Exception as e:
            logger.error(f"Error getting K8s status: {e}")
            return {"status": "not_found", "running": False}
    
    async def get_all_containers(self) -> List[Dict[str, Any]]:
        """Returns a list of all running development environments with their metadata."""
        all_environments = []

        # Get all environments from Kubernetes
        try:
            k8s_environments = await get_k8s_manager().list_dev_environments()

            for k8s_env in k8s_environments:
                project_key = self._get_project_key(k8s_env["user_id"], k8s_env["project_id"])

                env_data = {
                    "project_key": project_key,
                    "user_id": k8s_env["user_id"],
                    "project_id": k8s_env["project_id"],
                    "hostname": k8s_env.get("hostname"),
                    "url": k8s_env.get("url"),
                    "deployment_name": k8s_env.get("deployment_name"),
                    "status": k8s_env.get("status"),
                    "running": k8s_env.get("deployment_ready", False),
                    "replicas": k8s_env.get("replicas", {}),
                    "pods": k8s_env.get("pods", [])
                }

                all_environments.append(env_data)

        except Exception as e:
            logger.error(f"Error listing environments: {e}")

        return all_environments
    
    async def stop_all_containers(self) -> None:
        """Stop all development environments."""
        logger.info("Stopping all development environments...")

        # Get list of all environment info before iterating
        environments_to_stop = list(self.environments.items())
        for project_key, environment_info in environments_to_stop:
            project_id = environment_info.get("project_id")
            user_id = environment_info.get("user_id")
            if project_id and user_id is not None:
                await self.stop_container(project_id, user_id)

        logger.info("All development environments stopped")
    
    async def force_cleanup_orphaned_environments(self) -> List[str]:
        """Force cleanup of orphaned Kubernetes resources."""
        logger.info("Cleaning up orphaned development environments...")

        cleaned_environments = []

        try:
            # Get all environments from Kubernetes
            k8s_environments = await get_k8s_manager().list_dev_environments()

            for k8s_env in k8s_environments:
                user_id = k8s_env["user_id"]
                project_id = k8s_env["project_id"]
                project_key = self._get_project_key(user_id, project_id)

                # Check if environment is tracked locally
                if project_key not in self.environments:
                    logger.info(f"Found orphaned environment: {project_key}")
                    try:
                        await get_k8s_manager().delete_dev_environment(user_id, project_id)
                        cleaned_environments.append(project_key)
                        logger.info(f"Cleaned up orphaned environment: {project_key}")
                    except Exception as e:
                        logger.error(f"Failed to cleanup {project_key}: {e}")

        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

        logger.info(f"Cleanup completed. Removed {len(cleaned_environments)} orphaned environments")
        return cleaned_environments

    def track_activity(self, user_id: UUID, project_id: str) -> None:
        """Record activity for a project environment."""
        project_key = self._get_project_key(user_id, project_id)
        self.activity_tracker[project_key] = time.time()
        logger.debug(f"Activity tracked for {project_key}")

    async def ensure_container_running(self, project_id: str, user_id: UUID, project_slug: str = None) -> bool:
        """
        Ensure environment is running, auto-restart if stopped.

        For K8s, this checks if deployment exists and scales it up if needed.

        Returns:
            True if environment is running or successfully started
            False if environment could not be started
        """
        from ..k8s_client import get_k8s_manager

        try:
            k8s_manager = get_k8s_manager()
            health = await k8s_manager.check_dev_environment_health(user_id, project_id)

            if health["exists"] and health["ready"]:
                self.track_activity(user_id, project_id)
                # Clear paused timestamp since environment is now active
                project_key = self._get_project_key(user_id, project_id)
                self.paused_at_tracker.pop(project_key, None)
                return True

            if health["exists"] and not health["ready"]:
                logger.info(f"[AUTO-RESTART] Environment exists but not ready, waiting for it to start...")
                # Check if scaled to 0, if so scale back up
                if health.get("replicas") == 0:
                    logger.info(f"[AUTO-RESTART] Scaling up from 0 replicas...")
                    try:
                        await k8s_manager.scale_deployment(user_id, project_id, replicas=1)
                        project_key = self._get_project_key(user_id, project_id)
                        self.paused_at_tracker.pop(project_key, None)
                    except Exception as e:
                        logger.error(f"[AUTO-RESTART] Failed to scale up: {e}")
                return True

            logger.info(f"[AUTO-RESTART] Environment does not exist, needs creation")
            return False

        except Exception as e:
            logger.error(f"[AUTO-RESTART] Error checking environment status: {e}")
            return False

    async def cleanup_idle_environments(self, idle_timeout_minutes: int = 30) -> List[str]:
        """
        Cleanup idle K8s environments based on storage mode:

        S3 Storage Mode (hibernation):
        - Delete idle environments after configured minutes (triggers S3 upload via preStop hook)
        - No scaling to 0 (environments are fully hibernated to S3)

        Persistent PVC Mode (two-tier):
        - Tier 1 (5 minutes idle): Scale to 0 replicas (pause)
        - Tier 2 (24 hours paused): Fully delete deployment/service/ingress

        Args:
            idle_timeout_minutes: Minutes of inactivity before action (default: 30 for S3 mode, 5 for persistent mode)

        Returns:
            List of project keys that were scaled down or removed
        """
        settings = get_settings()

        # S3 Storage Mode: Simple hibernation (delete after idle timeout)
        if settings.k8s_use_s3_storage:
            return await self._cleanup_s3_mode(idle_timeout_minutes)

        # Persistent PVC Mode: Two-tier cleanup (scale to 0, then delete)
        return await self._cleanup_persistent_mode(idle_timeout_minutes)

    async def _cleanup_s3_mode(self, idle_timeout_minutes: int) -> List[str]:
        """
        S3 storage mode cleanup: Delete idle environments (triggers hibernation to S3).

        Args:
            idle_timeout_minutes: Minutes of inactivity before hibernation

        Returns:
            List of project keys that were hibernated
        """
        logger.info("[CLEANUP:S3] S3 Mode cleanup starting...")
        logger.info(f"[CLEANUP:S3] Hibernate after {idle_timeout_minutes} minutes idle")

        hibernated = []
        current_time = time.time()
        idle_timeout_seconds = idle_timeout_minutes * 60

        try:
            # Get all running environments from Kubernetes
            k8s_environments = await get_k8s_manager().list_dev_environments()

            for k8s_env in k8s_environments:
                user_id = k8s_env["user_id"]
                project_id = k8s_env["project_id"]
                project_key = self._get_project_key(user_id, project_id)

                # Check last activity time
                last_activity = self.activity_tracker.get(project_key, 0)
                idle_time = current_time - last_activity if last_activity > 0 else float('inf')
                idle_minutes = idle_time / 60

                # If no activity tracked yet, use a conservative estimate
                if last_activity == 0:
                    creation_time = k8s_env.get("creation_time")
                    if creation_time:
                        idle_time = current_time - creation_time
                        idle_minutes = idle_time / 60

                # Check if environment should be hibernated
                if idle_time > idle_timeout_seconds:
                    logger.info(
                        f"[CLEANUP:S3] Hibernating {project_key} "
                        f"(idle for {idle_minutes:.1f} minutes)"
                    )

                    try:
                        # Delete environment (triggers preStop hook → S3 upload)
                        await self.stop_container(project_id, user_id)

                        # Remove from active environments
                        self.environments.pop(project_key, None)
                        self.activity_tracker.pop(project_key, None)

                        hibernated.append(project_key)

                        # TODO: Update DB status to 'hibernated' (requires database migration)
                        # await db.execute(
                        #     update(Project)
                        #     .where(Project.id == project_id)
                        #     .values(status="hibernated", hibernated_at=datetime.utcnow())
                        # )

                        logger.info(f"[CLEANUP:S3] ✅ Hibernated {project_key}")

                    except Exception as e:
                        logger.error(f"[CLEANUP:S3] ❌ Failed to hibernate {project_key}: {e}")
                else:
                    logger.debug(f"[CLEANUP:S3] {project_key} is active (idle for {idle_minutes:.1f} minutes)")

        except Exception as e:
            logger.error(f"[CLEANUP:S3] ❌ Unexpected error during cleanup: {e}")

        logger.info(f"[CLEANUP:S3] ✅ Cleanup completed: Hibernated {len(hibernated)} environments")
        return hibernated

    async def _cleanup_persistent_mode(self, idle_timeout_minutes: int) -> List[str]:
        """
        Persistent PVC mode cleanup: Two-tier system (scale to 0, then delete).

        Args:
            idle_timeout_minutes: Minutes of inactivity before scaling to 0

        Returns:
            List of project keys that were scaled down or removed
        """
        logger.info("[CLEANUP:PERSISTENT] Persistent mode cleanup starting...")
        logger.info(f"[CLEANUP:PERSISTENT] Tier 1: Scale to 0 replicas after {idle_timeout_minutes} minutes idle")
        logger.info("[CLEANUP:PERSISTENT] Tier 2: Delete resources after 24 hours at 0 replicas")

        scaled_down = []
        removed = []
        current_time = time.time()

        # Tier 1 timeout: scale to 0 after idle_timeout_minutes (default 5 minutes)
        tier1_timeout_seconds = idle_timeout_minutes * 60

        # Tier 2 timeout: fully remove after 24 hours scaled to 0
        tier2_timeout_seconds = 24 * 60 * 60

        try:
            # ========== TIER 2: Delete long-paused environments (24+ hours) ==========
            paused_keys_to_check = list(self.paused_at_tracker.keys())

            for project_key in paused_keys_to_check:
                paused_at = self.paused_at_tracker[project_key]
                paused_duration = current_time - paused_at
                paused_hours = paused_duration / 3600

                if paused_duration > tier2_timeout_seconds:
                    # Environment has been paused for 24+ hours, fully delete it
                    env_info = self.environments.get(project_key)

                    if env_info:
                        user_id = env_info.get("user_id")
                        project_id = env_info.get("project_id")

                        logger.info(f"[CLEANUP:TIER2] Deleting long-paused environment {project_key} (paused for {paused_hours:.1f} hours)")

                        try:
                            # Fully delete the K8s resources
                            await self.stop_container(project_id, user_id)
                            removed.append(project_key)

                            # Clean up all tracking data
                            self.paused_at_tracker.pop(project_key, None)
                            self.activity_tracker.pop(project_key, None)

                            logger.info(f"[CLEANUP:TIER2] ✅ Deleted resources for {project_key}")

                        except Exception as e:
                            logger.error(f"[CLEANUP:TIER2] ❌ Failed to delete {project_key}: {e}")
                    else:
                        # Environment info not found, clean up tracking
                        self.paused_at_tracker.pop(project_key, None)

            # ========== TIER 1: Scale down idle environments (5+ minutes) ==========
            k8s_environments = await get_k8s_manager().list_dev_environments()

            for k8s_env in k8s_environments:
                user_id = k8s_env["user_id"]
                project_id = k8s_env["project_id"]
                project_key = self._get_project_key(user_id, project_id)
                replicas = k8s_env.get("replicas", 0)

                # Skip if already scaled to 0 (will be handled by Tier 2)
                if replicas == 0:
                    # If not tracked in paused_at_tracker, add it now
                    if project_key not in self.paused_at_tracker:
                        self.paused_at_tracker[project_key] = current_time
                        logger.info(f"[CLEANUP:TIER1] Tracking already-paused environment {project_key}")
                    continue

                # Check last activity time
                last_activity = self.activity_tracker.get(project_key, 0)
                idle_time = current_time - last_activity if last_activity > 0 else float('inf')
                idle_minutes = idle_time / 60

                # If no activity tracked yet, use pod creation time as baseline
                if last_activity == 0:
                    creation_time = k8s_env.get("creation_time")
                    if creation_time:
                        idle_time = current_time - creation_time
                        idle_minutes = idle_time / 60

                # Check if environment should be scaled down
                if idle_time > tier1_timeout_seconds:
                    logger.info(f"[CLEANUP:TIER1] Scaling down idle environment {project_key} (idle for {idle_minutes:.1f} minutes)")
                    try:
                        # Scale deployment to 0 replicas (pause)
                        k8s_manager = get_k8s_manager()
                        await k8s_manager.scale_deployment(user_id, project_id, replicas=0)
                        scaled_down.append(project_key)

                        # Record pause timestamp
                        self.paused_at_tracker[project_key] = current_time

                        logger.info(f"[CLEANUP:TIER1] ✅ Scaled down {project_key}")

                    except Exception as e:
                        logger.error(f"[CLEANUP:TIER1] ❌ Failed to scale down {project_key}: {e}")
                else:
                    logger.debug(f"[CLEANUP:TIER1] {project_key} is active (idle for {idle_minutes:.1f} minutes)")

        except Exception as e:
            logger.error(f"[CLEANUP] ❌ Unexpected error during cleanup: {e}")

        # Summary
        total_cleaned = len(scaled_down) + len(removed)
        logger.info("[CLEANUP] ✅ Cleanup completed:")
        logger.info(f"[CLEANUP]    - Scaled down: {len(scaled_down)} environments")
        logger.info(f"[CLEANUP]    - Deleted: {len(removed)} environments")
        logger.info(f"[CLEANUP]    - Total: {total_cleaned} environments cleaned")

        return scaled_down + removed