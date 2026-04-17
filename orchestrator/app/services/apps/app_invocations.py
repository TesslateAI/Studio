"""Scheduled/webhook dispatch into a running app instance.

The scheduler worker enqueues :func:`invoke_app_instance_task` whenever a
:class:`~app.models.ScheduleTriggerEvent` fires for a schedule bound to an
:class:`~app.models.AppInstance`. Two strategies:

* ``"job"`` (default) — build a Kubernetes ``V1Job`` using the primary
  container's image + schedule entrypoint as the command, volume-mount the
  install's persistent volume, and capture stdout/stderr into the event row.
* ``"http-post"`` — resolve the primary container's runtime URL and POST the
  event payload with an invocation-key Bearer token.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select

from ...database import AsyncSessionLocal
from ...models import (
    AgentSchedule,
    AppInstance,
    Container,
    Project,
    ScheduleTriggerEvent,
)

logger = logging.getLogger(__name__)

_DEFAULT_JOB_TIMEOUT_SECONDS = 300
_DEFAULT_INVOCATION_BUDGET_USD = Decimal("0.25")


async def _mint_invocation_key(
    db,
    *,
    installer_user_id: UUID,
    app_instance_id: UUID,
    budget_usd: Decimal,
) -> str | None:
    """Mint an invocation-tier LiteLLM key, returning the ``key_id``.

    Prefers ``litellm_keys.mint_invocation``; falls back to the generic
    ``mint`` helper on the ``invocation`` tier if the specialized helper
    isn't present yet.
    """
    from ...services import litellm_keys
    from ...services.litellm_service import LiteLLMService

    delegate = LiteLLMService()  # LiteLLMDelegate implementation

    try:
        mint_invocation = getattr(litellm_keys, "mint_invocation", None)
        if mint_invocation is not None:
            row = await mint_invocation(
                db,
                delegate=delegate,
                installer_user_id=installer_user_id,
                app_instance_id=app_instance_id,
                budget_usd=budget_usd,
            )
        else:
            # Fallback: base mint on the invocation tier.
            row = await litellm_keys.mint(
                db,
                delegate=delegate,
                tier="invocation",
                user_id=installer_user_id,
                app_instance_id=app_instance_id,
                budget_usd=budget_usd,
            )
        return row.key_id
    except Exception:
        logger.exception(
            "app_invocations.mint failed instance=%s", app_instance_id
        )
        return None


async def _resolve_env(container: Container) -> list[Any]:
    """Translate Container.environment_vars into pod env vars via env_resolver.

    Any ``${secret:…}`` refs are rewritten to ``valueFrom.secretKeyRef`` — we
    fail hard if resolution errors rather than leak plaintext refs into the pod.
    """
    from .env_resolver import resolve_env_for_pod

    env_map: dict[str, str] = dict(container.environment_vars or {})
    return resolve_env_for_pod(env_map)


def _resolve_primary_url(
    project: Project, container: Container
) -> str | None:
    """Resolve the externally-reachable URL for the primary container.

    Uses :func:`runtime_urls.container_url` to stay in lockstep with
    ingress creation.
    """
    try:
        from ...config import get_settings
        from .runtime_urls import container_url

        settings = get_settings()
        protocol = getattr(settings, "k8s_container_url_protocol", "http")
        domain = settings.app_domain
        dir_or_name = container.directory or container.name
        return container_url(
            project_slug=project.slug,
            container_dir_or_name=dir_or_name,
            app_domain=domain,
            protocol=protocol,
        )
    except Exception:
        logger.exception(
            "app_invocations: failed to resolve primary URL for project=%s",
            getattr(project, "id", None),
        )
        return None


def _build_job_manifest(
    *,
    job_name: str,
    image: str,
    command: str,
    env_vars: list[Any],
    volume_id: str | None,
    timeout_seconds: int,
):
    """Build a minimal V1Job spec for a one-shot app invocation."""
    from kubernetes import client as k8s_client  # type: ignore

    volumes: list[Any] = []
    volume_mounts: list[Any] = []
    if volume_id:
        volumes.append(
            k8s_client.V1Volume(
                name="app-data",
                persistent_volume_claim=k8s_client.V1PersistentVolumeClaimVolumeSource(
                    claim_name=volume_id
                ),
            )
        )
        volume_mounts.append(
            k8s_client.V1VolumeMount(name="app-data", mount_path="/app")
        )

    container = k8s_client.V1Container(
        name="runner",
        image=image,
        command=["sh", "-c", command],
        env=env_vars,
        volume_mounts=volume_mounts,
    )
    pod_spec = k8s_client.V1PodSpec(
        restart_policy="Never",
        containers=[container],
        volumes=volumes,
    )
    return k8s_client.V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=k8s_client.V1ObjectMeta(name=job_name),
        spec=k8s_client.V1JobSpec(
            ttl_seconds_after_finished=600,
            active_deadline_seconds=timeout_seconds,
            backoff_limit=0,
            template=k8s_client.V1PodTemplateSpec(
                metadata=k8s_client.V1ObjectMeta(labels={"app-invocation": "true"}),
                spec=pod_spec,
            ),
        ),
    )


async def invoke_app_instance_task(
    ctx: dict,
    schedule_id: str,
    event_id: str,
    payload: dict,
) -> dict[str, Any]:
    """ARQ task: dispatch a scheduled/webhook trigger into an app instance."""
    import asyncio

    result: dict[str, Any] = {"schedule_id": schedule_id, "event_id": event_id}

    async with AsyncSessionLocal() as db:
        schedule = (
            await db.execute(
                select(AgentSchedule).where(AgentSchedule.id == UUID(schedule_id))
            )
        ).scalar_one_or_none()
        if schedule is None or schedule.app_instance_id is None:
            logger.warning(
                "invoke_app_instance_task: schedule %s not found or not bound",
                schedule_id,
            )
            return {**result, "status": "skipped", "reason": "missing_schedule"}

        instance = (
            await db.execute(
                select(AppInstance).where(AppInstance.id == schedule.app_instance_id)
            )
        ).scalar_one_or_none()
        if instance is None or instance.project_id is None:
            return {**result, "status": "failed", "reason": "missing_instance_project"}

        project = (
            await db.execute(
                select(Project).where(Project.id == instance.project_id)
            )
        ).scalar_one_or_none()
        if project is None:
            return {**result, "status": "failed", "reason": "missing_project"}

        # Primary container resolution — prefer explicit pointer on the
        # AppInstance, then the is_primary flag, then first container.
        primary_ctr: Container | None = None
        primary_id = getattr(instance, "primary_container_id", None)
        if primary_id is not None:
            primary_ctr = (
                await db.execute(
                    select(Container).where(Container.id == primary_id)
                )
            ).scalar_one_or_none()
        if primary_ctr is None:
            primary_ctr = (
                await db.execute(
                    select(Container)
                    .where(Container.project_id == project.id)
                    .where(Container.is_primary.is_(True))
                )
            ).scalar_one_or_none()
        if primary_ctr is None:
            primary_ctr = (
                await db.execute(
                    select(Container)
                    .where(Container.project_id == project.id)
                    .order_by(Container.created_at.asc())
                )
            ).scalars().first()
        if primary_ctr is None:
            return {**result, "status": "failed", "reason": "no_primary_container"}

        trig_cfg: dict[str, Any] = dict(schedule.trigger_config or {})
        execution = trig_cfg.get("execution", "job")
        entrypoint = trig_cfg.get("entrypoint") or ""

        # Mint invocation key for this run (budget bookkeeping).
        invocation_key_id = await _mint_invocation_key(
            db,
            installer_user_id=instance.installer_user_id,
            app_instance_id=instance.id,
            budget_usd=_DEFAULT_INVOCATION_BUDGET_USD,
        )
        await db.commit()

        status = "failed"
        error: str | None = None
        summary: dict[str, Any] = {}

        try:
            if execution == "http-post":
                import httpx

                primary_url = _resolve_primary_url(project, primary_ctr)
                if not primary_url:
                    raise RuntimeError("primary_url unresolved (runtime_urls dependency missing)")
                target = primary_url.rstrip("/") + "/" + entrypoint.lstrip("/")
                headers = {
                    "Content-Type": "application/json",
                    "X-Invocation-Id": invocation_key_id or "",
                    "X-Schedule-Id": schedule_id,
                    "X-Event-Id": event_id,
                }
                if invocation_key_id:
                    headers["Authorization"] = f"Bearer {invocation_key_id}"
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(
                        target,
                        json=payload or {},
                        headers=headers,
                    )
                summary = {
                    "kind": "http-post",
                    "status_code": resp.status_code,
                    "body": resp.text[:4000],
                }
                status = "succeeded" if resp.is_success else "failed"
                if not resp.is_success:
                    error = f"http {resp.status_code}"
            else:
                # Job execution path.
                from kubernetes import client as k8s_client
                from ...services.orchestration.kubernetes.client import (
                    KubernetesClient,
                )

                k8s = KubernetesClient()
                namespace = k8s.get_project_namespace(str(project.id))
                ts = int(datetime.now(tz=timezone.utc).timestamp())
                job_name = f"app-inv-{schedule_id[:8]}-{ts}"

                env_vars = list(await _resolve_env(primary_ctr))
                env_vars.extend([
                    k8s_client.V1EnvVar(name="INVOCATION_ID", value=invocation_key_id or ""),
                    k8s_client.V1EnvVar(name="SCHEDULE_ID", value=schedule_id),
                    k8s_client.V1EnvVar(name="EVENT_ID", value=event_id),
                ])

                image = getattr(primary_ctr, "image", None)
                if not image and getattr(primary_ctr, "base", None) is not None:
                    image = getattr(primary_ctr.base, "image", None)
                if not image:
                    image = (primary_ctr.environment_vars or {}).get("_image")
                if not image:
                    raise RuntimeError(
                        "primary container has no resolvable image "
                        "(installer must populate Container.image)"
                    )

                job = _build_job_manifest(
                    job_name=job_name,
                    image=image,
                    command=entrypoint or (primary_ctr.startup_command or "true"),
                    env_vars=env_vars,
                    volume_id=getattr(project, "volume_id", None),
                    timeout_seconds=_DEFAULT_JOB_TIMEOUT_SECONDS,
                )

                created = await k8s.create_job(namespace, job)
                if created is None:
                    raise RuntimeError(f"job {job_name} create returned None")

                # Poll for completion.
                deadline = asyncio.get_event_loop().time() + _DEFAULT_JOB_TIMEOUT_SECONDS
                job_status = "running"
                while asyncio.get_event_loop().time() < deadline:
                    job_status = await k8s.get_job_status(job_name, namespace)
                    if job_status in {"succeeded", "failed"}:
                        break
                    await asyncio.sleep(5)
                status = job_status if job_status in {"succeeded", "failed"} else "failed"
                summary = {"kind": "job", "job_name": job_name, "job_status": job_status}
                if status != "succeeded":
                    error = f"job_status={job_status}"
        except Exception as exc:
            logger.exception("invoke_app_instance_task failed schedule=%s", schedule_id)
            status = "failed"
            error = repr(exc)[:1000]

        # Persist bookkeeping in a fresh session (the prior commit released locks).
        try:
            async with AsyncSessionLocal() as db2:
                event = (
                    await db2.execute(
                        select(ScheduleTriggerEvent).where(
                            ScheduleTriggerEvent.id == UUID(event_id)
                        )
                    )
                ).scalar_one_or_none()
                if event is not None:
                    event.result_status = status
                    event.processed_at = datetime.now(tz=timezone.utc)
                    if error:
                        event.error = error
                    payload_update = dict(event.payload or {})
                    payload_update["_invocation_summary"] = summary
                    event.payload = payload_update

                sched2 = (
                    await db2.execute(
                        select(AgentSchedule).where(AgentSchedule.id == UUID(schedule_id))
                    )
                ).scalar_one_or_none()
                if sched2 is not None:
                    sched2.last_run_at = datetime.now(tz=timezone.utc)
                    sched2.last_status = status
                    sched2.last_error = error
                    sched2.runs_completed = (sched2.runs_completed or 0) + 1

                # Lifecycle ledger entry — amount=0 records the invocation
                # happened even when no AI spend was incurred.
                try:
                    from . import billing_dispatcher

                    await billing_dispatcher.record_spend(
                        db2,
                        app_instance_id=instance.id,
                        installer_user_id=instance.installer_user_id,
                        dimension="ai_compute",
                        amount_usd=Decimal("0"),
                        litellm_key_id=invocation_key_id,
                        meta={"request_id": event_id, "source": "app_invocation"},
                    )
                except Exception:
                    logger.exception(
                        "invoke_app_instance_task: ledger write failed event=%s",
                        event_id,
                    )

                await db2.commit()
        except Exception:
            logger.exception(
                "invoke_app_instance_task: bookkeeping failed schedule=%s",
                schedule_id,
            )

        result.update({"status": status, "error": error, "summary": summary})
        return result
