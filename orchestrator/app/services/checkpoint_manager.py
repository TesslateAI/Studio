"""
Checkpoint Manager — file-level undo for agent turns.

Two strategies depending on platform and compute state:

1. **Git ghost commits** (Docker, K8s with running pod):
   Invisible detached commit objects capturing the working tree via a
   temporary index.  Doesn't touch user's branches, staging area, or
   git log.  GC'd after ~2 weeks.

2. **Volume fork** (K8s tier-0 — no pod running):
   Instant btrfs CoW clone of the project volume via the Volume Hub.
   On undo, swaps ``project.volume_id`` to the checkpoint fork.

The checkpoint reference stored in message metadata is prefixed:
  - ``git:<40-char-hash>``  — git ghost commit
  - ``vol:<volume-id>``     — btrfs volume fork
"""

import contextlib
import logging
import re
from uuid import UUID

logger = logging.getLogger(__name__)

# Valid 40-char lowercase hex git commit hash
_HASH_RE = re.compile(r"^[0-9a-f]{40}$")

# Sentinel for extracting exit codes from combined stdout+stderr output
_EXIT_SENTINEL = "__CKPT_EXIT:"


class CheckpointManager:
    """Creates and restores file-level checkpoints for agent undo."""

    def __init__(
        self,
        user_id: UUID,
        project_id: str,
        volume_id: str | None = None,
    ):
        self.user_id = user_id
        self.project_id = project_id
        self.volume_id = volume_id

    # ================================================================== #
    #  Public API                                                         #
    # ================================================================== #

    async def create_checkpoint(self) -> str | None:
        """Capture the current file state.

        Returns a prefixed reference string (``git:<hash>`` or
        ``vol:<id>``), or ``None`` if checkpointing is not possible.
        Failure is **non-fatal** — the caller should proceed without
        a checkpoint.
        """
        from .orchestration import is_kubernetes_mode

        # K8s with a volume but no running pod → btrfs volume fork
        if is_kubernetes_mode() and self.volume_id and not await self._has_running_pod():
            return await self._create_volume_fork()

        # Default: git ghost commit (Docker or K8s with running pod)
        git_hash = await self._create_git_checkpoint()
        return f"git:{git_hash}" if git_hash else None

    async def restore_checkpoint(self, ref: str, db=None) -> bool:
        """Restore files to a checkpoint.

        Args:
            ref: Checkpoint reference from ``create_checkpoint()``.
            db: AsyncSession — required for ``vol:`` checkpoints
                (updates ``project.volume_id``).

        Returns ``True`` on success.
        """
        if ref.startswith("git:"):
            return await self._restore_git_checkpoint(ref[4:])
        elif ref.startswith("vol:"):
            if db is None:
                logger.error("[CHECKPOINT] vol: restore requires db session")
                return False
            return await self._restore_volume_fork(ref[4:], db)
        else:
            # Legacy: bare 40-char hash (pre-prefix format)
            if _HASH_RE.match(ref):
                return await self._restore_git_checkpoint(ref)
            logger.warning("[CHECKPOINT] unknown ref format: %.60s", ref)
            return False

    # ================================================================== #
    #  Strategy 1: Git ghost commits                                      #
    # ================================================================== #

    async def _create_git_checkpoint(self) -> str | None:
        """Snapshot the working tree as a detached ghost commit."""
        script = (
            "cd /app && "
            "(test -d .git || git -c safe.directory=/app init -b main >/dev/null 2>&1) && "
            "mkdir -p .tesslate/checkpoints && "
            "CKPT_IDX=/app/.tesslate/checkpoints/tmp_index_$$ && "
            'rm -f "$CKPT_IDX" && '
            '(GIT_INDEX_FILE="$CKPT_IDX" git -c safe.directory=/app '
            "  read-tree HEAD 2>/dev/null || "
            ' GIT_INDEX_FILE="$CKPT_IDX" git -c safe.directory=/app '
            "  read-tree "
            "  $(git -c safe.directory=/app mktree </dev/null)) && "
            'GIT_INDEX_FILE="$CKPT_IDX" git -c safe.directory=/app '
            "  add -A -- . ':!.tesslate' && "
            'TREE=$(GIT_INDEX_FILE="$CKPT_IDX" git -c safe.directory=/app '
            "  write-tree) && "
            'rm -f "$CKPT_IDX" && '
            "COMMIT=$(printf 'tesslate-checkpoint' | "
            "  git -c safe.directory=/app "
            "  -c user.name='Tesslate' -c user.email='checkpoint@tesslate.com' "
            '  commit-tree "$TREE") && '
            'printf "%s" "$COMMIT"'
        )

        output, exit_code = await self._exec(script, timeout=10)

        if exit_code != 0:
            logger.warning("[CHECKPOINT] git create failed (exit %d): %.200s", exit_code, output)
            return None

        commit_hash = output.strip().rsplit("\n", 1)[-1].strip() if output.strip() else ""
        if not _HASH_RE.match(commit_hash):
            logger.warning("[CHECKPOINT] invalid hash: %.80s", commit_hash)
            return None

        logger.info("[CHECKPOINT] Git checkpoint %s", commit_hash[:8])
        return commit_hash

    async def _restore_git_checkpoint(self, commit_hash: str) -> bool:
        """Restore working tree from a git ghost commit."""
        if not _HASH_RE.match(commit_hash):
            logger.warning("[CHECKPOINT] invalid hash: %.40s", commit_hash)
            return False

        h = commit_hash  # validated as 40 hex chars above
        script = (
            "cd /app && "
            "RIDX=/app/.tesslate/checkpoints/restore_idx_$$ && "
            'rm -f "$RIDX" && '
            'GIT_DIR=/app/.git GIT_WORK_TREE=/app GIT_INDEX_FILE="$RIDX" '
            "  git -c safe.directory=/app read-tree " + h + " && "
            'GIT_DIR=/app/.git GIT_WORK_TREE=/app GIT_INDEX_FILE="$RIDX" '
            "  git -c safe.directory=/app checkout-index -a -f && "
            'rm -f "$RIDX" && { '
            "  git -c safe.directory=/app ls-tree -r --name-only " + h + " 2>/dev/null"
            "    | sort > /tmp/_ckpt_want; "
            "  find . -path ./.git -prune -o -path ./.tesslate -prune"
            "    -o -path ./node_modules -prune"
            "    -o -type f -print 2>/dev/null"
            "    | sed 's|^\\./||' | sort > /tmp/_ckpt_now; "
            "  comm -23 /tmp/_ckpt_now /tmp/_ckpt_want"
            "    > /tmp/_ckpt_new 2>/dev/null; "
            "  git -c safe.directory=/app ls-files --others --ignored"
            "    --exclude-standard 2>/dev/null"
            "    | sort > /tmp/_ckpt_ign; "
            "  comm -23 /tmp/_ckpt_new /tmp/_ckpt_ign 2>/dev/null"
            "    | tr '\\n' '\\0' | xargs -0 rm -f 2>/dev/null; "
            "  for _i in 1 2; do find . -path ./.git -prune -o -path ./.tesslate -prune"
            "    -o -path ./node_modules -prune"
            "    -o -mindepth 1 -type d -empty -exec rmdir {} + 2>/dev/null; done; "
            "  rm -f /tmp/_ckpt_want /tmp/_ckpt_now /tmp/_ckpt_new /tmp/_ckpt_ign; "
            "  echo RESTORED; "
            "}"
        )

        output, exit_code = await self._exec(script, timeout=10)

        if "RESTORED" not in output:
            logger.warning("[CHECKPOINT] git restore failed (exit %d): %.200s", exit_code, output)
            return False

        logger.info("[CHECKPOINT] Git restored to %s", commit_hash[:8])
        return True

    # ================================================================== #
    #  Strategy 2: Volume fork (K8s tier-0)                               #
    # ================================================================== #

    async def _create_volume_fork(self) -> str | None:
        """Fork the project volume via the Hub (instant btrfs CoW clone)."""
        try:
            from .volume_manager import VolumeManager

            vm = VolumeManager()
            fork_id, node = await vm.fork_volume(self.volume_id)
            logger.info(
                "[CHECKPOINT] Volume fork %s → %s on %s",
                self.volume_id,
                fork_id,
                node,
            )
            return f"vol:{fork_id}"
        except Exception as exc:
            logger.warning("[CHECKPOINT] volume fork failed: %s", exc)
            return None

    async def _restore_volume_fork(self, fork_volume_id: str, db) -> bool:
        """Restore by swapping project.volume_id to the checkpoint fork.

        The old (post-agent) volume is deleted.  This is safe for tier-0
        projects because no pod is referencing the volume.
        """
        try:
            from sqlalchemy import select

            from ..models import Project
            from .volume_manager import VolumeManager

            result = await db.execute(select(Project).where(Project.id == UUID(self.project_id)))
            project = result.scalar_one_or_none()
            if not project:
                logger.error("[CHECKPOINT] Project %s not found", self.project_id)
                return False

            old_volume_id = project.volume_id
            if not old_volume_id or old_volume_id == fork_volume_id:
                logger.warning("[CHECKPOINT] Volume already matches fork")
                return True

            # Swap to the checkpoint volume
            project.volume_id = fork_volume_id
            await db.commit()
            logger.info(
                "[CHECKPOINT] Volume swapped %s → %s",
                old_volume_id,
                fork_volume_id,
            )

            # Delete the old (post-agent) volume — best-effort
            try:
                vm = VolumeManager()
                await vm.delete_volume(old_volume_id)
                logger.info("[CHECKPOINT] Deleted old volume %s", old_volume_id)
            except Exception as del_err:
                logger.warning(
                    "[CHECKPOINT] Failed to delete old volume %s: %s",
                    old_volume_id,
                    del_err,
                )

            return True
        except Exception as exc:
            logger.error("[CHECKPOINT] volume restore failed: %s", exc)
            return False

    # ================================================================== #
    #  K8s pod detection                                                  #
    # ================================================================== #

    async def _has_running_pod(self) -> bool:
        """Check if the project has a running compute pod in K8s."""
        try:
            from .orchestration import get_orchestrator

            orchestrator = get_orchestrator()
            status = await orchestrator.is_container_ready(
                user_id=self.user_id,
                project_id=UUID(self.project_id),
                container_name="",
            )
            return status.get("ready", False)
        except Exception:
            return False

    # ================================================================== #
    #  Shell execution helpers                                            #
    # ================================================================== #

    async def _exec(self, script: str, timeout: int = 10) -> tuple[str, int]:
        """Run a shell script in the project workdir.

        Scripts are authored against ``/app`` (the container/pod workdir);
        ``/app`` is rewritten to the real host filesystem root on desktop
        and to the docker shared-volume path when falling back outside a
        container. Kubernetes keeps the literal ``/app`` — pods mount the
        project volume there.

        Returns ``(output, exit_code)``.  Never raises — returns
        ``("", -1)`` if the container exec itself fails.
        """
        from .orchestration import is_docker_mode, is_local_mode

        full_script = f"({script}) 2>&1; printf '\\n{_EXIT_SENTINEL}%d\\n' $?"

        try:
            if is_docker_mode():
                raw = await self._docker_exec(full_script, timeout)
            elif is_local_mode():
                raw = await self._local_exec(full_script, timeout)
            else:
                from .orchestration import get_orchestrator

                orchestrator = get_orchestrator()
                raw = await orchestrator.execute_command(
                    user_id=self.user_id,
                    project_id=self.project_id,
                    container_name=None,
                    command=["/bin/sh", "-c", full_script],
                    timeout=timeout,
                )
        except Exception as exc:
            logger.debug("[CHECKPOINT] exec failed: %s", exc)
            return "", -1

        output = raw
        exit_code = 0
        if _EXIT_SENTINEL in raw:
            parts = raw.rsplit(_EXIT_SENTINEL, 1)
            output = parts[0].strip()
            with contextlib.suppress(ValueError, IndexError):
                exit_code = int(parts[1].strip())
        return output, exit_code

    async def _docker_exec(self, full_script: str, timeout: int) -> str:
        """Run a command in a Docker project — container or direct filesystem.

        Tries ``docker exec --user 0`` first (root access needed because the
        orchestrator writes files as root, but containers run as ``node``).
        If no container is running (stopped projects), falls back to running
        git directly on the shared volume at ``/projects/{slug}/`` from the
        orchestrator process.
        """
        import asyncio

        from sqlalchemy import select

        from ..database import AsyncSessionLocal
        from ..models import Container as ContainerModel
        from ..models import Project

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Project).where(Project.id == UUID(self.project_id)))
            project = result.scalar_one_or_none()
            if not project:
                raise RuntimeError(f"Project {self.project_id} not found")

            result = await db.execute(
                select(ContainerModel.name)
                .where(ContainerModel.project_id == UUID(self.project_id))
                .order_by(ContainerModel.created_at)
                .limit(1)
            )
            container_name = result.scalar_one_or_none()

        # Try container exec first, fall back to direct filesystem
        if container_name:
            from .orchestration import get_orchestrator

            orch = get_orchestrator()
            service_name = orch._resolve_service_name(container_name, project.slug)
            docker_container = f"{project.slug}-{service_name}"

            try:
                process = await asyncio.create_subprocess_exec(
                    "docker",
                    "exec",
                    "--user",
                    "0",
                    docker_container,
                    "/bin/sh",
                    "-c",
                    full_script,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
                # 125 = container not running; fall through to direct mode
                if process.returncode != 125:
                    return stdout.decode() + stderr.decode()
            except Exception:
                pass  # Fall through to direct mode

        # Direct filesystem mode — run git on /projects/{slug}/ from the
        # orchestrator process (which has root access and git installed).
        project_path = f"/projects/{project.slug}"
        local_script = full_script.replace("/app", project_path)

        process = await asyncio.create_subprocess_exec(
            "/bin/sh",
            "-c",
            local_script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        return stdout.decode() + stderr.decode()

    async def _local_exec(self, full_script: str, timeout: int) -> str:
        """Desktop/local-mode checkpoint exec.

        Scripts are authored against ``/app``; rewrite it to the real
        on-disk project root (``$TESSLATE_STUDIO_HOME/projects/<slug>-<id>``)
        and run git as the calling user — no docker / kubectl in scope.
        """
        import asyncio

        from sqlalchemy import select

        from ..database import AsyncSessionLocal
        from ..models import Project
        from .project_fs import get_project_fs_path

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Project).where(Project.id == UUID(self.project_id)))
            project = result.scalar_one_or_none()

        if project is None:
            raise RuntimeError(f"Project {self.project_id} not found")

        fs_path = get_project_fs_path(project)
        if fs_path is None:
            raise RuntimeError(f"Project {self.project_id} has no host filesystem path")

        local_script = full_script.replace("/app", str(fs_path))

        process = await asyncio.create_subprocess_exec(
            "/bin/sh",
            "-c",
            local_script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        return stdout.decode() + stderr.decode()
