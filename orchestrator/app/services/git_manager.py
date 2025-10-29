from uuid import UUID
"""
Git Manager for executing Git operations in user development environments.
Works with both Docker and Kubernetes deployments.
"""
import shlex
import json
import re
from typing import Dict, List, Optional, Any
from datetime import datetime
import logging

from ..config import get_settings
from ..dev_server_manager import get_container_manager
from ..utils.resource_naming import get_project_path

logger = logging.getLogger(__name__)


class GitManager:
    """Manages Git operations in user development environments."""

    def __init__(self, user_id: UUID, project_id: str):
        """
        Initialize Git Manager for a specific user project.

        Args:
            user_id: User ID
            project_id: Project ID
        """
        self.user_id = user_id
        self.project_id = project_id
        self.settings = get_settings()
        self.container_manager = get_container_manager()

    async def _execute_git_command(
        self,
        git_args: List[str],
        timeout: int = 120
    ) -> str:
        """
        Execute a Git command in the user's development environment.

        Args:
            git_args: Git command arguments (e.g., ["status", "--porcelain"])
            timeout: Command timeout in seconds

        Returns:
            Command output (stdout + stderr)

        Raises:
            RuntimeError: If command execution fails
        """
        # Both Docker and Kubernetes now mount to /app
        project_path = "/app"

        # Build the full command
        command = ["/bin/sh", "-c", f"cd {project_path} && git {' '.join(shlex.quote(arg) for arg in git_args)}"]

        try:
            # Use the container manager to execute the command
            if self.settings.deployment_mode == "kubernetes":
                from ..k8s_client import get_k8s_manager
                k8s_manager = get_k8s_manager()
                output = await k8s_manager.execute_command_in_pod(
                    user_id=self.user_id,
                    project_id=self.project_id,
                    command=command,
                    timeout=timeout
                )
            else:
                # Docker mode
                from ..docker_container_manager import DockerContainerManager
                docker_manager: DockerContainerManager = self.container_manager
                output = await docker_manager.execute_command_in_container(
                    user_id=self.user_id,
                    project_id=self.project_id,
                    command=command,
                    timeout=timeout
                )

            return output.strip()

        except Exception as e:
            logger.error(f"[GIT] Failed to execute git command: {git_args[0]}", exc_info=True)
            raise RuntimeError(f"Git command failed: {str(e)}") from e

    async def initialize_repository(
        self,
        remote_url: Optional[str] = None,
        default_branch: str = "main"
    ) -> bool:
        """
        Initialize a Git repository in the project directory.

        Args:
            remote_url: Optional remote repository URL
            default_branch: Default branch name (default: "main")

        Returns:
            True if successful

        Raises:
            RuntimeError: If initialization fails
        """
        try:
            logger.info(f"[GIT] Initializing repository for user {self.user_id}, project {self.project_id}")

            # Initialize Git repository
            await self._execute_git_command(["init", "-b", default_branch])
            logger.info(f"[GIT] Repository initialized with branch: {default_branch}")

            # Configure user (use a default for now, can be customized per user)
            await self._execute_git_command(["config", "user.name", "Tesslate User"])
            await self._execute_git_command(["config", "user.email", "user@tesslate.com"])
            logger.info(f"[GIT] Git config set")

            # Add remote if provided
            if remote_url:
                await self._execute_git_command(["remote", "add", "origin", remote_url])
                logger.info(f"[GIT] Added remote: {remote_url}")

            return True

        except Exception as e:
            logger.error(f"[GIT] Failed to initialize repository: {e}", exc_info=True)
            raise RuntimeError(f"Failed to initialize Git repository: {str(e)}") from e

    async def clone_repository(
        self,
        repo_url: str,
        branch: Optional[str] = None,
        auth_token: Optional[str] = None,
        direct_to_filesystem: bool = False
    ) -> bool:
        """
        Clone a repository into the project directory.

        Note: This will replace existing files in the project directory.

        Args:
            repo_url: Repository URL to clone
            branch: Specific branch to clone (optional)
            auth_token: GitHub access token for authentication
            direct_to_filesystem: Clone directly to filesystem (for Docker mode GitHub imports without container)

        Returns:
            True if successful

        Raises:
            RuntimeError: If clone fails
        """
        try:
            logger.info(f"[GIT] Cloning repository {repo_url} for user {self.user_id}, project {self.project_id}")

            # Inject auth token into URL if provided
            if auth_token and "github.com" in repo_url:
                # Convert to HTTPS URL with token
                if repo_url.startswith("git@github.com:"):
                    # Convert SSH to HTTPS
                    repo_url = repo_url.replace("git@github.com:", "https://github.com/")

                # Inject token
                repo_url = repo_url.replace("https://github.com/", f"https://{auth_token}@github.com/")

            # Direct filesystem clone (for Docker mode without container)
            if direct_to_filesystem and self.settings.deployment_mode == "docker":
                import asyncio
                import os

                # Build project path on host filesystem
                project_path = os.path.abspath(get_project_path(self.user_id, self.project_id))
                os.makedirs(project_path, exist_ok=True)

                # Build git clone command
                git_cmd = ["git", "clone"]
                if branch:
                    git_cmd.extend(["--branch", branch])
                git_cmd.extend([repo_url, project_path])

                # Execute git clone directly on host
                logger.info(f"[GIT] Executing direct filesystem clone: {' '.join(git_cmd[:3])} [URL] {project_path}")
                process = await asyncio.create_subprocess_exec(
                    *git_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )

                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300)

                if process.returncode != 0:
                    error_msg = stderr.decode() if stderr else "Unknown error"
                    raise RuntimeError(f"Git clone failed with exit code {process.returncode}: {error_msg}")

                logger.info(f"[GIT] Repository cloned successfully to {project_path}")
                return True

            # Container-based clone (for running containers or Kubernetes)
            # Build clone command
            clone_args = ["clone"]
            if branch:
                clone_args.extend(["--branch", branch])
            clone_args.extend([repo_url, "/tmp/git-clone"])

            # Clone to temp directory first
            await self._execute_git_command(clone_args, timeout=300)  # 5 minutes timeout for large repos
            logger.info(f"[GIT] Repository cloned successfully")

            # Move files from clone to project directory
            # Both Docker and Kubernetes now mount to /app
            project_path = "/app"

            # Use shell command to move contents
            move_command = [
                "/bin/sh", "-c",
                f"rm -rf {project_path}/.* {project_path}/* 2>/dev/null || true && "
                f"mv /tmp/git-clone/.git {project_path}/ && "
                f"mv /tmp/git-clone/* /tmp/git-clone/.* {project_path}/ 2>/dev/null || true && "
                "rm -rf /tmp/git-clone"
            ]

            if self.settings.deployment_mode == "kubernetes":
                from ..k8s_client import get_k8s_manager
                k8s_manager = get_k8s_manager()
                await k8s_manager.execute_command_in_pod(
                    user_id=self.user_id,
                    project_id=self.project_id,
                    command=move_command,
                    timeout=60
                )
            else:
                from ..docker_container_manager import DockerContainerManager
                docker_manager: DockerContainerManager = self.container_manager
                await docker_manager.execute_command_in_container(
                    user_id=self.user_id,
                    project_id=self.project_id,
                    command=move_command,
                    timeout=60
                )

            logger.info(f"[GIT] Repository files moved to project directory")
            return True

        except Exception as e:
            logger.error(f"[GIT] Failed to clone repository: {e}", exc_info=True)
            raise RuntimeError(f"Failed to clone repository: {str(e)}") from e

    async def get_status(self) -> Dict[str, Any]:
        """
        Get Git repository status.

        Returns:
            Dictionary with status information:
            - branch: Current branch name
            - status: Status string (clean, modified, etc.)
            - changes: List of changed files
            - changes_count: Number of changed files
            - ahead: Number of commits ahead of remote
            - behind: Number of commits behind remote

        Raises:
            RuntimeError: If status check fails
        """
        try:
            # Get current branch
            branch_output = await self._execute_git_command(["branch", "--show-current"])
            branch = branch_output.strip() or "main"

            # Get status in porcelain format
            status_output = await self._execute_git_command(["status", "--porcelain"])

            # Parse changed files
            changes = []
            for line in status_output.split('\n'):
                if not line.strip():
                    continue

                # Parse status code and file path
                status_code = line[:2]
                file_path = line[3:].strip()

                change_type = "modified"
                if status_code.strip() == "??":
                    change_type = "untracked"
                elif status_code[0] == "A" or status_code[1] == "A":
                    change_type = "added"
                elif status_code[0] == "D" or status_code[1] == "D":
                    change_type = "deleted"
                elif status_code[0] == "M" or status_code[1] == "M":
                    change_type = "modified"

                changes.append({
                    "path": file_path,
                    "type": change_type,
                    "staged": status_code[0] != " " and status_code[0] != "?"
                })

            # Get ahead/behind count if tracking remote
            ahead, behind = 0, 0
            try:
                rev_list_output = await self._execute_git_command(
                    ["rev-list", "--left-right", "--count", f"origin/{branch}...HEAD"],
                    timeout=30
                )
                parts = rev_list_output.strip().split()
                if len(parts) == 2:
                    behind = int(parts[0])
                    ahead = int(parts[1])
            except:
                # No remote tracking or fetch hasn't been done
                pass

            # Determine overall status
            if not changes:
                if ahead == 0 and behind == 0:
                    status = "clean"
                elif ahead > 0 and behind == 0:
                    status = "ahead"
                elif ahead == 0 and behind > 0:
                    status = "behind"
                else:
                    status = "diverged"
            else:
                status = "modified"

            # Get last commit info
            last_commit = None
            try:
                commit_output = await self._execute_git_command(
                    ["log", "-1", "--pretty=format:%H|%an|%ae|%s|%ct"],
                    timeout=30
                )
                if commit_output:
                    parts = commit_output.split('|')
                    if len(parts) >= 5:
                        last_commit = {
                            "sha": parts[0],
                            "author_name": parts[1],
                            "author_email": parts[2],
                            "message": parts[3],
                            "timestamp": int(parts[4])
                        }
            except:
                # No commits yet
                pass

            return {
                "branch": branch,
                "status": status,
                "changes": changes,
                "changes_count": len(changes),
                "ahead": ahead,
                "behind": behind,
                "last_commit": last_commit
            }

        except Exception as e:
            logger.error(f"[GIT] Failed to get status: {e}", exc_info=True)
            raise RuntimeError(f"Failed to get Git status: {str(e)}") from e

    async def commit(
        self,
        message: str,
        files: Optional[List[str]] = None
    ) -> str:
        """
        Create a Git commit.

        Args:
            message: Commit message
            files: Specific files to commit (None = all changes)

        Returns:
            Commit SHA

        Raises:
            RuntimeError: If commit fails
        """
        try:
            logger.info(f"[GIT] Creating commit: {message[:50]}...")

            # Stage files
            if files:
                for file_path in files:
                    await self._execute_git_command(["add", file_path])
            else:
                # Stage all changes
                await self._execute_git_command(["add", "."])

            # Create commit
            await self._execute_git_command(["commit", "-m", message])

            # Get commit SHA
            sha_output = await self._execute_git_command(["rev-parse", "HEAD"])
            commit_sha = sha_output.strip()

            logger.info(f"[GIT] Commit created: {commit_sha[:8]}")
            return commit_sha

        except Exception as e:
            logger.error(f"[GIT] Failed to create commit: {e}", exc_info=True)
            raise RuntimeError(f"Failed to create commit: {str(e)}") from e

    async def push(
        self,
        branch: Optional[str] = None,
        remote: str = "origin",
        force: bool = False
    ) -> bool:
        """
        Push commits to remote repository.

        Args:
            branch: Branch to push (None = current branch)
            remote: Remote name (default: "origin")
            force: Force push (use with caution)

        Returns:
            True if successful

        Raises:
            RuntimeError: If push fails
        """
        try:
            # Get current branch if not specified
            if not branch:
                branch_output = await self._execute_git_command(["branch", "--show-current"])
                branch = branch_output.strip()

            logger.info(f"[GIT] Pushing {branch} to {remote}...")

            # Build push command
            push_args = ["push", remote, branch]
            if force:
                push_args.insert(1, "--force")

            await self._execute_git_command(push_args, timeout=300)  # 5 minutes for large pushes
            logger.info(f"[GIT] Push completed successfully")
            return True

        except Exception as e:
            logger.error(f"[GIT] Failed to push: {e}", exc_info=True)
            raise RuntimeError(f"Failed to push to remote: {str(e)}") from e

    async def pull(
        self,
        branch: Optional[str] = None,
        remote: str = "origin"
    ) -> Dict[str, Any]:
        """
        Pull changes from remote repository.

        Args:
            branch: Branch to pull (None = current branch)
            remote: Remote name (default: "origin")

        Returns:
            Dictionary with pull result:
            - success: bool
            - conflicts: List of conflicted files (if any)
            - message: Result message

        Raises:
            RuntimeError: If pull fails (not including conflicts)
        """
        try:
            # Get current branch if not specified
            if not branch:
                branch_output = await self._execute_git_command(["branch", "--show-current"])
                branch = branch_output.strip()

            logger.info(f"[GIT] Pulling {branch} from {remote}...")

            # Fetch first
            await self._execute_git_command(["fetch", remote, branch], timeout=300)

            # Attempt pull
            try:
                pull_output = await self._execute_git_command(["pull", remote, branch], timeout=300)
                logger.info(f"[GIT] Pull completed successfully")
                return {
                    "success": True,
                    "conflicts": [],
                    "message": "Pull completed successfully"
                }
            except Exception as pull_error:
                # Check if it's a merge conflict
                status_output = await self._execute_git_command(["status", "--porcelain"])
                conflicts = []
                for line in status_output.split('\n'):
                    if line.startswith("UU ") or line.startswith("AA ") or line.startswith("DD "):
                        file_path = line[3:].strip()
                        conflicts.append(file_path)

                if conflicts:
                    logger.warning(f"[GIT] Pull resulted in {len(conflicts)} conflicts")
                    return {
                        "success": False,
                        "conflicts": conflicts,
                        "message": f"Pull completed with {len(conflicts)} conflicts"
                    }
                else:
                    raise pull_error

        except Exception as e:
            logger.error(f"[GIT] Failed to pull: {e}", exc_info=True)
            raise RuntimeError(f"Failed to pull from remote: {str(e)}") from e

    async def get_commit_history(
        self,
        limit: int = 50,
        branch: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get commit history.

        Args:
            limit: Maximum number of commits to retrieve
            branch: Specific branch (None = current branch)

        Returns:
            List of commit dictionaries with sha, author, message, timestamp

        Raises:
            RuntimeError: If history retrieval fails
        """
        try:
            # Build log command
            log_args = [
                "log",
                f"-{limit}",
                "--pretty=format:%H|%an|%ae|%s|%ct"
            ]
            if branch:
                log_args.append(branch)

            log_output = await self._execute_git_command(log_args, timeout=60)

            commits = []
            for line in log_output.split('\n'):
                if not line.strip():
                    continue

                parts = line.split('|')
                if len(parts) >= 5:
                    commits.append({
                        "sha": parts[0],
                        "author_name": parts[1],
                        "author_email": parts[2],
                        "message": parts[3],
                        "timestamp": int(parts[4])
                    })

            logger.info(f"[GIT] Retrieved {len(commits)} commits")
            return commits

        except Exception as e:
            logger.error(f"[GIT] Failed to get commit history: {e}", exc_info=True)
            raise RuntimeError(f"Failed to get commit history: {str(e)}") from e

    async def list_branches(self) -> List[Dict[str, Any]]:
        """
        List all branches.

        Returns:
            List of branch dictionaries with name, current, remote

        Raises:
            RuntimeError: If branch listing fails
        """
        try:
            # Get all branches including remotes
            branch_output = await self._execute_git_command(["branch", "-a", "-v"])

            branches = []
            current_branch = None

            for line in branch_output.split('\n'):
                if not line.strip():
                    continue

                is_current = line.startswith('*')
                line = line.lstrip('* ').strip()

                # Parse branch info
                parts = line.split()
                if not parts:
                    continue

                branch_name = parts[0]

                # Skip HEAD references
                if "HEAD" in branch_name:
                    continue

                # Determine if remote branch
                is_remote = branch_name.startswith('remotes/')
                if is_remote:
                    branch_name = branch_name.replace('remotes/', '')

                branches.append({
                    "name": branch_name,
                    "current": is_current,
                    "remote": is_remote
                })

                if is_current:
                    current_branch = branch_name

            logger.info(f"[GIT] Found {len(branches)} branches (current: {current_branch})")
            return branches

        except Exception as e:
            logger.error(f"[GIT] Failed to list branches: {e}", exc_info=True)
            raise RuntimeError(f"Failed to list branches: {str(e)}") from e

    async def create_branch(self, name: str, checkout: bool = True) -> bool:
        """
        Create a new branch.

        Args:
            name: Branch name
            checkout: Whether to checkout the new branch

        Returns:
            True if successful

        Raises:
            RuntimeError: If branch creation fails
        """
        try:
            logger.info(f"[GIT] Creating branch: {name}")

            if checkout:
                await self._execute_git_command(["checkout", "-b", name])
            else:
                await self._execute_git_command(["branch", name])

            logger.info(f"[GIT] Branch created: {name}")
            return True

        except Exception as e:
            logger.error(f"[GIT] Failed to create branch: {e}", exc_info=True)
            raise RuntimeError(f"Failed to create branch: {str(e)}") from e

    async def switch_branch(self, name: str) -> bool:
        """
        Switch to a different branch.

        Args:
            name: Branch name to switch to

        Returns:
            True if successful

        Raises:
            RuntimeError: If branch switch fails
        """
        try:
            logger.info(f"[GIT] Switching to branch: {name}")
            await self._execute_git_command(["checkout", name])
            logger.info(f"[GIT] Switched to branch: {name}")
            return True

        except Exception as e:
            logger.error(f"[GIT] Failed to switch branch: {e}", exc_info=True)
            raise RuntimeError(f"Failed to switch branch: {str(e)}") from e

    async def get_diff(
        self,
        file_path: Optional[str] = None,
        staged: bool = False
    ) -> str:
        """
        Get diff of changes.

        Args:
            file_path: Specific file to diff (None = all files)
            staged: Whether to show staged changes only

        Returns:
            Diff output

        Raises:
            RuntimeError: If diff fails
        """
        try:
            diff_args = ["diff"]
            if staged:
                diff_args.append("--cached")
            if file_path:
                diff_args.append(file_path)

            diff_output = await self._execute_git_command(diff_args, timeout=60)
            return diff_output

        except Exception as e:
            logger.error(f"[GIT] Failed to get diff: {e}", exc_info=True)
            raise RuntimeError(f"Failed to get diff: {str(e)}") from e
