"""Phase 1 — typed AppAction dispatcher.

Routes a typed `(app_instance, action_name, input)` call to the right
handler kind on today's per-install runtime:

* ``http_post``      — POST to the running pod's ``primary_url + path``.
* ``k8s_job``        — build a V1Job, mount the per-install volume, poll.
* ``hosted_agent``   — route to ``hosted_agent_runtime`` (Phase 1 ships
                       the key-mint flow; Phase 3 wires the warm pool +
                       actual agent loop).

The dispatcher validates ``input`` against the action's ``input_schema``
before dispatch and validates the resulting ``output`` against the
action's ``output_schema`` before returning. It persists each declared
``artifacts:`` entry as a ``automation_run_artifacts`` row (inline storage
in Phase 1; CAS routing lands Phase 3) and emits a single ``SpendRecord``
attribution row.

Phase 1 simplifications (called out so Phase 3 doesn't have to grep):

* ``shared_singleton`` and ``per_invocation`` tenancy reject with
  :class:`ActionHandlerNotSupported`. Phase 3 introduces
  ``AppRuntimeDeployment`` to make those reachable.
* ``http_post`` does not wake a scaled-to-zero pod — Phase 3 adds
  ``provision_for_run`` cold-start.
* ``k8s_job`` requires ``DEPLOYMENT_MODE=kubernetes``; Docker runs the
  same handler shape only when Phase 4 wires Docker job execution.
* Connector Proxy injection is Phase 3 — the dispatcher does not append
  any ``X-OpenSail-*`` headers beyond invocation correlation.
* ``result_template`` rendering is dispatched to the long-lived sandboxed
  render worker (:mod:`app.services.apps.template_render`) when an action
  declares one. The rendered string is surfaced on
  :class:`ActionDispatchResult.rendered` for delivery hops to consume; a
  render failure logs and leaves the field ``None`` so the action still
  returns its typed ``output`` (delivery falls back to JSON dump).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AppVersion, Container, Project
from ...models_automations import AppAction, AppInstance
from . import billing_dispatcher
from .runtime_urls import container_url
from .template_render import RenderError, get_render_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public errors
# ---------------------------------------------------------------------------


class ActionDispatchError(Exception):
    """Base class for typed action dispatcher errors."""


class AppActionNotFound(ActionDispatchError):
    """Raised when ``(app_version_id, action_name)`` resolves to no row."""


class AppInstanceNotFound(ActionDispatchError):
    """Raised when ``app_instance_id`` does not resolve to an AppInstance."""


class ActionInputInvalid(ActionDispatchError):
    """Caller supplied input that does not validate against ``input_schema``."""


class ActionOutputInvalid(ActionDispatchError):
    """Handler returned output that does not validate against ``output_schema``.

    This is a creator bug — the app declared a contract its handler did not
    honor. The dispatcher refuses to deliver the value to downstream
    consumers (templates, deliveries, run history) so the silent-fail class
    described in the plan §"output_schema enforced at action-call boundary"
    can never happen.
    """


class ActionDispatchFailed(ActionDispatchError):
    """Handler reached its target but the target returned a non-success."""

    def __init__(self, message: str, *, status: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status = status
        self.body = body


class ActionHandlerNotSupported(ActionDispatchError):
    """The action's handler kind / tenancy is not implementable in Phase 1."""

    def __init__(self, message: str, *, kind: str | None = None, current_mode: str | None = None):
        super().__init__(message)
        self.kind = kind
        self.current_mode = current_mode


# ---------------------------------------------------------------------------
# Public result shape
# ---------------------------------------------------------------------------


@dataclass
class ActionDispatchResult:
    """Typed return value of :func:`dispatch_app_action`.

    On error, ``output`` is empty, ``artifacts`` is empty, ``error`` is set
    to the human-readable failure message and the dispatcher RAISES rather
    than silently returning this shape. The dataclass field exists so a
    higher-level caller (e.g. the automation worker) can build a failure
    result without re-deriving the shape.
    """

    output: dict[str, Any] = field(default_factory=dict)
    artifacts: list[UUID] = field(default_factory=list)
    spend_usd: Decimal = field(default_factory=lambda: Decimal("0"))
    duration_seconds: float = 0.0
    error: str | None = None
    # Rendered ``result_template`` body (sandboxed Jinja, output-capped). None
    # if the action did not declare a template, or if rendering failed (the
    # dispatcher logs and leaves the field None rather than failing the
    # whole action — delivery hops fall back to the typed ``output``).
    rendered: str | None = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


# Inline storage cap for Phase 1 (~32 KB). Anything above is truncated with
# a marker; Phase 3 will route oversize payloads to CAS.
_INLINE_MAX_BYTES = 32 * 1024
_OUTPUT_HARD_CAP_BYTES = 32 * 1024  # plan §"output_schema enforced at action-call boundary"
_DEFAULT_TIMEOUT_SECONDS = 60
_JOB_POLL_INTERVAL_SECONDS = 5


async def _load_app_instance(db: AsyncSession, app_instance_id: UUID) -> AppInstance:
    inst = (
        await db.execute(select(AppInstance).where(AppInstance.id == app_instance_id))
    ).scalar_one_or_none()
    if inst is None:
        raise AppInstanceNotFound(f"app_instance {app_instance_id} not found")
    return inst


async def _load_app_action(
    db: AsyncSession, app_version_id: UUID, action_name: str
) -> AppAction:
    row = (
        await db.execute(
            select(AppAction)
            .where(AppAction.app_version_id == app_version_id)
            .where(AppAction.name == action_name)
        )
    ).scalar_one_or_none()
    if row is None:
        raise AppActionNotFound(
            f"action {action_name!r} not declared on app_version {app_version_id}"
        )
    return row


def _validate_schema(schema: dict | None, value: Any, *, error_cls: type[ActionDispatchError]) -> None:
    """Validate ``value`` against ``schema`` (a JSON Schema dict).

    No-op when ``schema`` is None — the manifest parser allows schemaless
    actions and the dispatcher must not crash on them.
    """
    if not schema:
        return
    # Local import keeps import cost off the hot path for callers who never
    # dispatch a schema-bound action.
    import jsonschema
    from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

    try:
        jsonschema.Draft202012Validator(schema).validate(value)
    except JsonSchemaValidationError as exc:
        raise error_cls(f"schema validation failed: {exc.message}") from exc


def _enforce_output_size(output: Any) -> None:
    """Reject oversized outputs at the dispatch boundary.

    Solves the silent-fail class where a 10 MB JSON output sails through
    schema validation, fails to render in a template, and the run logs
    'delivered' even though Slack rejected the payload. We bail loudly at
    the action-call boundary instead.
    """
    try:
        encoded = json.dumps(output, default=str).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ActionOutputInvalid(f"output is not JSON-serializable: {exc}") from exc
    if len(encoded) > _OUTPUT_HARD_CAP_BYTES:
        raise ActionOutputInvalid(
            f"output exceeds {_OUTPUT_HARD_CAP_BYTES}-byte cap "
            f"({len(encoded)} bytes); persist via artifacts: instead"
        )


def _resolve_dot_path(root: dict, path: str) -> Any:
    """Walk a simple ``a.b.c`` dot-path through nested dicts.

    Phase 1 keeps this deliberately dumb — no ``$.``, no jq, no bracket
    indexing. The manifest's documented pattern is ``output.<key>`` or
    ``input.<key>``, so we only need to descend dict keys. Returns
    ``None`` for any missing segment so the artifact loop can skip.
    """
    if not path:
        return None
    cur: Any = root
    for segment in path.split("."):
        if isinstance(cur, dict) and segment in cur:
            cur = cur[segment]
        else:
            return None
    return cur


async def _resolve_handler_container(
    db: AsyncSession, instance: AppInstance, container_name: str | None
) -> Container:
    """Find the Container row for ``handler.container`` on this install.

    The manifest's ``actions[].handler.container`` is a logical name that
    matches the manifest's ``compute.containers[].name`` (== Container.name
    on the per-install Project). When ``container_name`` is None, fall back
    to the install's primary container.
    """
    if instance.project_id is None:
        raise ActionDispatchFailed(
            "AppInstance has no project_id (per-install runtime not provisioned)"
        )

    if container_name:
        ctr = (
            await db.execute(
                select(Container)
                .where(Container.project_id == instance.project_id)
                .where(Container.name == container_name)
            )
        ).scalar_one_or_none()
        if ctr is not None:
            return ctr
        raise ActionDispatchFailed(
            f"handler.container={container_name!r} did not match any "
            f"Container on project {instance.project_id}"
        )

    # Fall back to the install's primary container pointer.
    if instance.primary_container_id is not None:
        ctr = await db.get(Container, instance.primary_container_id)
        if ctr is not None:
            return ctr

    # Last resort — first container by created_at on the project.
    ctr = (
        (
            await db.execute(
                select(Container)
                .where(Container.project_id == instance.project_id)
                .order_by(Container.created_at.asc())
            )
        )
        .scalars()
        .first()
    )
    if ctr is None:
        raise ActionDispatchFailed(
            f"no Container row resolves for app_instance {instance.id}"
        )
    return ctr


def _build_container_url(project: Project, container: Container) -> str:
    """Build the externally-reachable URL for a container.

    Reuses ``runtime_urls.container_url`` so the dispatcher stays in
    lockstep with how ingress + the existing scheduled-invocation path
    construct the same URL. Phase 3's Connector Proxy + cold-start wake
    will replace this with a ``primary_url`` resolver on
    ``AppRuntimeDeployment`` — but the shape stays the same.
    """
    from ...config import get_settings

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


async def _persist_artifacts(
    db: AsyncSession,
    *,
    run_id: UUID | None,
    artifacts_spec: list[dict],
    output: dict,
    input_value: dict,
) -> list[UUID]:
    """Persist each manifest-declared artifact as an
    ``automation_run_artifacts`` row.

    ``run_id`` is required by the table FK; when the dispatcher is invoked
    outside a run (e.g. agent tool ad-hoc call before Phase 1's automation
    worker is wired through), we skip artifact persistence rather than
    fabricate a synthetic run row. Returns the empty list in that case.

    Storage routing is delegated to
    :func:`services.automations.artifacts.create_artifact`, which routes
    inline ↔ CAS based on payload size and writes the canonical preview.
    The dispatcher loop only owns the manifest-spec → content extraction
    here (``from`` dot-path resolution, default-to-whole-output behavior).
    """
    if not artifacts_spec or run_id is None:
        return []

    # Local import keeps the artifacts module off the hot path for callers
    # that never produce artifacts (e.g., http_post handlers with empty
    # ``actions[].artifacts``).
    from ..automations.artifacts import create_artifact

    ids: list[UUID] = []
    root = {"output": output, "input": input_value}

    for spec in artifacts_spec:
        if not isinstance(spec, dict):
            continue
        name = spec.get("name") or "artifact"
        kind = spec.get("kind") or "json"
        from_path = spec.get("from")
        mime_type = spec.get("mime_type")

        if from_path:
            value = _resolve_dot_path(root, from_path)
        else:
            # Default behavior: persist the whole output blob.
            value = output

        if value is None:
            logger.debug(
                "action_dispatcher: skip artifact name=%s from=%s (no value)",
                name,
                from_path,
            )
            continue

        try:
            row = await create_artifact(
                db,
                run_id=run_id,
                kind=kind,
                name=name,
                mime_type=mime_type,
                content=value,
                metadata={"from": from_path} if from_path else None,
            )
        except Exception as exc:  # noqa: BLE001 — artifact must never fail dispatch
            logger.warning(
                "action_dispatcher: artifact persist failed name=%s err=%r",
                name,
                exc,
            )
            continue
        ids.append(row.id)

    return ids


async def _record_spend_safe(
    db: AsyncSession,
    *,
    instance: AppInstance,
    run_id: UUID | None,
    duration_seconds: float,
    invocation_subject_id: UUID | None = None,
) -> Decimal:
    """Emit a SpendRecord attribution row for this dispatch.

    Phase 1 records ``$0`` against ``ai_compute`` (mirrors the existing
    ``app_invocations.py`` ledger pattern). Phase 2 fills in actual cost
    from the InvocationSubject; Phase 3 splits across dimensions.

    All three Automation Runtime attribution columns
    (``automation_run_id``, ``invocation_subject_id``, ``agent_id``) flow
    through the widened ``billing_dispatcher.record_spend()`` signature
    rather than a post-hoc UPDATE — closes the brief race window where
    a row could be queried before the FK columns landed.

    Wrapped in a try/except so a billing write failure NEVER fails an
    otherwise successful dispatch — billing is async accounting, not part
    of the synchronous correctness path.
    """
    try:
        request_id = str(uuid4())
        meta: dict[str, Any] = {
            "request_id": request_id,
            "source": "action_dispatch",
            "duration_seconds": round(duration_seconds, 4),
        }
        if run_id is not None:
            meta["automation_run_id"] = str(run_id)
        outcome = await billing_dispatcher.record_spend(
            db,
            app_instance_id=instance.id,
            installer_user_id=instance.installer_user_id,
            dimension="ai_compute",
            amount_usd=Decimal("0"),
            meta=meta,
            automation_run_id=run_id,
            invocation_subject_id=invocation_subject_id,
        )
        return outcome.amount_usd
    except Exception:  # noqa: BLE001 — billing write must never fail dispatch
        logger.exception(
            "action_dispatcher: spend record write failed app_instance=%s run=%s",
            instance.id,
            run_id,
        )
        return Decimal("0")


# ---------------------------------------------------------------------------
# Handler implementations
# ---------------------------------------------------------------------------


async def _dispatch_http_post(
    db: AsyncSession,
    *,
    instance: AppInstance,
    handler: dict,
    input_value: dict,
    timeout_seconds: int,
    run_id: UUID | None,
) -> dict:
    if instance.project_id is None:
        raise ActionDispatchFailed("AppInstance has no project_id (no runtime)")
    project = await db.get(Project, instance.project_id)
    if project is None:
        raise ActionDispatchFailed(f"project {instance.project_id} not found")

    container = await _resolve_handler_container(db, instance, handler.get("container"))
    base_url = _build_container_url(project, container)
    path = handler.get("path") or "/"
    target = base_url.rstrip("/") + "/" + path.lstrip("/")

    headers = {
        "Content-Type": "application/json",
        "X-OpenSail-Action": "1",
    }
    if run_id is not None:
        headers["X-OpenSail-Run-Id"] = str(run_id)
    headers["X-OpenSail-Instance-Id"] = str(instance.id)

    # Phase 3 cold-start wake. If the AppRuntimeDeployment is scaled to
    # zero, ask wake.provision_for_run() to scale it up and wait for
    # readiness BEFORE the HTTP POST. Bounded readiness timeout inside
    # provision_for_run; on failure, surface a clean ActionDispatchFailed
    # with paused_reason hint instead of a vague httpx ConnectError.
    runtime_deployment = getattr(instance, "runtime_deployment", None)
    if (
        run_id is not None
        and runtime_deployment is not None
        and runtime_deployment.scaled_to_zero_at is not None
    ):
        from ..automations.wake import provision_for_run as _wake

        logger.info(
            "action_dispatcher.http_post: cold-start wake instance=%s deployment=%s",
            instance.id,
            runtime_deployment.id,
        )
        try:
            from ..k8s_client import get_k8s_client
            k8s = get_k8s_client()
        except Exception:  # noqa: BLE001 — wake handles None client gracefully
            k8s = None

        result = await _wake(
            run_id,
            db,
            k8s,
            deployment_override=runtime_deployment,
        )
        if not result.ready:
            raise ActionDispatchFailed(
                f"cold-start wake failed: reason={result.reason}",
                status=None,
                body=None,
            )

    logger.info(
        "action_dispatcher.http_post target=%s instance=%s run=%s",
        target,
        instance.id,
        run_id,
    )

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            resp = await client.post(target, json=input_value, headers=headers)
    except httpx.HTTPError as exc:
        raise ActionDispatchFailed(
            f"http_post transport error: {exc!r}",
            status=None,
            body=None,
        ) from exc

    body_text = resp.text
    if resp.status_code < 200 or resp.status_code >= 300:
        raise ActionDispatchFailed(
            f"http_post target returned {resp.status_code}",
            status=resp.status_code,
            body=body_text[:4000],
        )

    if not body_text.strip():
        return {}
    try:
        parsed = resp.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise ActionDispatchFailed(
            f"http_post target returned non-JSON body: {exc}",
            status=resp.status_code,
            body=body_text[:4000],
        ) from exc

    if not isinstance(parsed, dict):
        # Wrap scalar/array returns so the result is always a dict — keeps
        # the contract with output_schema validation simple.
        return {"value": parsed}
    return parsed


def _resolve_job_image(container: Container) -> str:
    """Mirror the image resolution rule used by the legacy job path."""
    image = getattr(container, "image", None)
    if image:
        return image
    base = getattr(container, "base", None)
    if base is not None:
        base_image = getattr(base, "image", None)
        if base_image:
            return base_image
    fallback = (container.environment_vars or {}).get("_image")
    if fallback:
        return fallback
    raise ActionDispatchFailed(
        "k8s_job container has no resolvable image "
        "(installer must populate Container.image)"
    )


async def _read_job_pod_log(k8s_client, namespace: str, job_name: str) -> str | None:
    """Fetch the (last) Pod log for a completed Job.

    Pods owned by a Job carry the ``job-name=<job_name>`` label. The
    dispatcher reads the log from the most recent Pod and returns the raw
    text — handler convention is "the LAST line of stdout is a JSON dict".
    """
    try:
        pods = await asyncio.to_thread(
            k8s_client.core_v1.list_namespaced_pod,
            namespace=namespace,
            label_selector=f"job-name={job_name}",
        )
    except Exception:  # noqa: BLE001 — log fetch is best-effort
        logger.exception("action_dispatcher: list pods failed for job=%s", job_name)
        return None
    if not getattr(pods, "items", None):
        return None
    pod = pods.items[-1]
    pod_name = pod.metadata.name
    try:
        log = await asyncio.to_thread(
            k8s_client.core_v1.read_namespaced_pod_log,
            name=pod_name,
            namespace=namespace,
        )
        return log if isinstance(log, str) else log.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 — log fetch is best-effort
        logger.exception("action_dispatcher: read log failed pod=%s", pod_name)
        return None


def _parse_job_output(log_text: str | None) -> dict:
    """Parse the last non-empty line of stdout as a JSON dict.

    Convention: a ``k8s_job`` action emits its result as the FINAL line of
    stdout, formatted as ``{"key": ...}``. We tolerate trailing whitespace
    and lines after the JSON only if they are blank. If the last
    non-blank line isn't valid JSON, the dispatcher returns an empty
    output dict (the action's ``output_schema`` will then reject the call
    if a schema was declared — surfacing the contract violation).
    """
    if not log_text:
        return {}
    last_line = ""
    for raw in log_text.splitlines()[::-1]:
        candidate = raw.strip()
        if candidate:
            last_line = candidate
            break
    if not last_line:
        return {}
    try:
        parsed = json.loads(last_line)
    except (ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(parsed, dict):
        return {"value": parsed}
    return parsed


async def _dispatch_k8s_job(
    db: AsyncSession,
    *,
    instance: AppInstance,
    handler: dict,
    input_value: dict,
    timeout_seconds: int,
    run_id: UUID | None,
) -> dict:
    from ...config import get_settings

    settings = get_settings()
    if not settings.is_kubernetes_mode:
        raise ActionHandlerNotSupported(
            "k8s_job handler requires DEPLOYMENT_MODE=kubernetes "
            "(Docker support lands in Phase 4)",
            kind="k8s_job",
            current_mode=settings.deployment_mode,
        )

    if instance.project_id is None:
        raise ActionDispatchFailed("AppInstance has no project_id (no runtime)")
    project = await db.get(Project, instance.project_id)
    if project is None:
        raise ActionDispatchFailed(f"project {instance.project_id} not found")

    container = await _resolve_handler_container(db, instance, handler.get("container"))
    image = _resolve_job_image(container)
    command = (
        handler.get("command")
        or handler.get("path")
        or container.startup_command
        or "true"
    )
    mount_path = handler.get("mount_path") or "/app"

    # Late imports keep the kubernetes client off the import path for
    # callers that never hit the k8s_job branch (most desktop / docker
    # tests).
    from kubernetes import client as k8s_client_lib

    from ..orchestration.kubernetes.client import KubernetesClient

    k8s = KubernetesClient()
    namespace = k8s.get_project_namespace(str(project.id))

    job_name = f"act-{str(instance.id)[:8]}-{int(time.time())}"

    env_vars = [
        k8s_client_lib.V1EnvVar(name="OPENSAIL_ACTION_INPUT", value=json.dumps(input_value)),
        k8s_client_lib.V1EnvVar(name="OPENSAIL_INSTANCE_ID", value=str(instance.id)),
    ]
    if run_id is not None:
        env_vars.append(k8s_client_lib.V1EnvVar(name="OPENSAIL_RUN_ID", value=str(run_id)))

    volumes: list[Any] = []
    volume_mounts: list[Any] = []
    volume_id = getattr(project, "volume_id", None)
    if volume_id:
        volumes.append(
            k8s_client_lib.V1Volume(
                name="app-data",
                persistent_volume_claim=k8s_client_lib.V1PersistentVolumeClaimVolumeSource(
                    claim_name=volume_id,
                ),
            )
        )
        volume_mounts.append(
            k8s_client_lib.V1VolumeMount(name="app-data", mount_path=mount_path)
        )

    # Phase 4: tmpfs at /tmp + read-only root for ephemeral / Tier-1
    # action runs. See ``app_invocations.py`` for the same pattern. Any
    # write outside /tmp / the per-install volume vanishes when the pod
    # terminates — that's the documented stateless contract.
    volumes.append(
        k8s_client_lib.V1Volume(
            name="ephemeral-tmp",
            empty_dir=k8s_client_lib.V1EmptyDirVolumeSource(
                medium="Memory", size_limit="256Mi"
            ),
        )
    )
    volume_mounts.append(
        k8s_client_lib.V1VolumeMount(name="ephemeral-tmp", mount_path="/tmp")
    )
    _ephemeral_sec_ctx = k8s_client_lib.V1SecurityContext(
        read_only_root_filesystem=True,
        allow_privilege_escalation=False,
    )

    job_container = k8s_client_lib.V1Container(
        name="action",
        image=image,
        command=["sh", "-c", command],
        env=env_vars,
        volume_mounts=volume_mounts,
        security_context=_ephemeral_sec_ctx,
    )
    pod_spec = k8s_client_lib.V1PodSpec(
        restart_policy="Never",
        containers=[job_container],
        volumes=volumes,
    )
    job = k8s_client_lib.V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=k8s_client_lib.V1ObjectMeta(
            name=job_name,
            labels={"opensail.app-action": "true"},
        ),
        spec=k8s_client_lib.V1JobSpec(
            ttl_seconds_after_finished=600,
            active_deadline_seconds=timeout_seconds,
            backoff_limit=0,
            template=k8s_client_lib.V1PodTemplateSpec(
                metadata=k8s_client_lib.V1ObjectMeta(
                    labels={"opensail.app-action": "true", "job-name": job_name}
                ),
                spec=pod_spec,
            ),
        ),
    )

    created = await k8s.create_job(namespace, job)
    if created is None:
        raise ActionDispatchFailed(f"k8s_job {job_name}: create returned None")

    deadline = asyncio.get_event_loop().time() + timeout_seconds
    job_status = "running"
    while asyncio.get_event_loop().time() < deadline:
        job_status = await k8s.get_job_status(job_name, namespace)
        if job_status in {"succeeded", "failed"}:
            break
        await asyncio.sleep(_JOB_POLL_INTERVAL_SECONDS)

    if job_status != "succeeded":
        # Best-effort: still try to read logs so error surface can include
        # tail output for debugging.
        log = await _read_job_pod_log(k8s, namespace, job_name)
        raise ActionDispatchFailed(
            f"k8s_job {job_name} status={job_status}",
            status=None,
            body=(log or "")[:4000],
        )

    log = await _read_job_pod_log(k8s, namespace, job_name)
    return _parse_job_output(log)


async def _dispatch_hosted_agent(
    db: AsyncSession,
    *,
    instance: AppInstance,
    handler: dict,
    input_value: dict,
    timeout_seconds: int,
    run_id: UUID | None,
) -> dict:
    """Phase 1 hosted-agent dispatch.

    Mints (and immediately settles) an invocation key via
    ``hosted_agent_runtime`` so the existing Phase 0 LiteLLM key plumbing
    is exercised by this code path. The Phase 1 surface intentionally does
    NOT spin up the agent loop — that's filled in by Phase 3 alongside the
    warm pool. The output dict mirrors the typed handle so an
    output_schema declaration like ``{required: [agent_id]}`` validates
    cleanly during early integration.
    """
    agent_id = handler.get("agent")
    if not agent_id:
        raise ActionDispatchFailed(
            "hosted_agent handler requires handler.agent to reference manifest "
            "compute.hosted_agents[].id"
        )

    # Late import — keeps the LiteLLM service off the import path for
    # callers that never dispatch a hosted agent.
    from ...services.litellm_service import LiteLLMService
    from . import hosted_agent_runtime

    delegate = LiteLLMService()
    handle = await hosted_agent_runtime.begin_hosted_invocation(
        db,
        app_instance_id=instance.id,
        agent_id=agent_id,
        installer_user_id=instance.installer_user_id,
        delegate=delegate,
        ttl_seconds=max(60, timeout_seconds),
    )
    try:
        # Phase 3 will run the actual agent loop here; for Phase 1 we
        # surface the typed handle so the output_schema can validate that
        # the dispatch actually wired through the key-mint path.
        return {
            "agent_id": handle.agent_id,
            "invocation_id": str(handle.invocation_id),
            "model": handle.model,
            "input_echo": input_value,
        }
    finally:
        try:
            await hosted_agent_runtime.end_hosted_invocation(
                db,
                invocation_id=handle.invocation_id,
                litellm_key_id=handle.litellm_key_id,
                delegate=delegate,
                outcome="complete",
            )
        except Exception:  # noqa: BLE001 — settlement failure is non-fatal
            logger.exception(
                "action_dispatcher: hosted agent settlement failed key=%s",
                handle.litellm_key_id,
            )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def dispatch_app_action(
    db: AsyncSession,
    *,
    app_instance_id: UUID,
    action_name: str,
    input: dict,
    run_id: UUID | None = None,
    invocation_subject_id: UUID | None = None,  # Phase 2 — accepted now, ignored until then
) -> ActionDispatchResult:
    """Dispatch a typed action call against an installed app.

    Validates ``input`` against the action's ``input_schema`` before
    dispatch. Validates ``output`` against the action's ``output_schema``
    before return. Persists each declared artifact in
    ``action.artifacts`` as an ``automation_run_artifacts`` row. Routes by
    ``handler.kind`` to ``http_post``, ``k8s_job``, or ``hosted_agent``.

    See module docstring for Phase 1 simplifications.
    """
    started_at = time.monotonic()

    instance = await _load_app_instance(db, app_instance_id)
    action = await _load_app_action(db, instance.app_version_id, action_name)

    # Phase 1: Reject tenancy modes that need AppRuntimeDeployment.
    version = await db.get(AppVersion, instance.app_version_id)
    if version is not None:
        manifest = version.manifest_json or {}
        runtime_block = manifest.get("runtime") or {}
        tenancy = runtime_block.get("tenancy_model")
        if tenancy in {"shared_singleton", "per_invocation"}:
            raise ActionHandlerNotSupported(
                f"tenancy_model={tenancy!r} requires AppRuntimeDeployment "
                "(lands in Phase 3)",
                kind="tenancy",
                current_mode=tenancy,
            )

    # Step 2 — input validation.
    if not isinstance(input, dict):
        raise ActionInputInvalid(
            f"input must be a dict, got {type(input).__name__}"
        )
    _validate_schema(action.input_schema, input, error_cls=ActionInputInvalid)

    # Step 3 — route to handler.
    handler = action.handler or {}
    if not isinstance(handler, dict):
        raise ActionDispatchFailed(
            f"action {action_name!r}: handler is not a dict ({type(handler).__name__})"
        )
    kind = handler.get("kind")
    timeout_seconds = action.timeout_seconds or _DEFAULT_TIMEOUT_SECONDS

    if kind == "http_post":
        output = await _dispatch_http_post(
            db,
            instance=instance,
            handler=handler,
            input_value=input,
            timeout_seconds=timeout_seconds,
            run_id=run_id,
        )
    elif kind == "k8s_job":
        output = await _dispatch_k8s_job(
            db,
            instance=instance,
            handler=handler,
            input_value=input,
            timeout_seconds=timeout_seconds,
            run_id=run_id,
        )
    elif kind == "hosted_agent":
        output = await _dispatch_hosted_agent(
            db,
            instance=instance,
            handler=handler,
            input_value=input,
            timeout_seconds=timeout_seconds,
            run_id=run_id,
        )
    else:
        raise ActionHandlerNotSupported(
            f"unknown handler.kind={kind!r}",
            kind=str(kind) if kind is not None else None,
        )

    # Step 4 — output validation (size cap, then declared schema).
    _enforce_output_size(output)
    _validate_schema(action.output_schema, output, error_cls=ActionOutputInvalid)

    # Step 5 — persist declared artifacts.
    artifact_ids = await _persist_artifacts(
        db,
        run_id=run_id,
        artifacts_spec=list(action.artifacts or []),
        output=output,
        input_value=input,
    )

    # Step 5b — render `result_template` via the sandboxed worker.
    # Failures here log + degrade to ``rendered=None`` rather than failing
    # the action: the typed ``output`` already validated, the artifacts are
    # persisted, and a delivery hop can fall back to ``json.dumps(output)``.
    rendered: str | None = None
    template_str = getattr(action, "result_template", None)
    if isinstance(template_str, str) and template_str.strip():
        try:
            rendered = await get_render_client().render(
                template_str,
                {"input": input, "output": output},
            )
        except RenderError as exc:
            logger.warning(
                "action_dispatcher: result_template render failed action=%s "
                "instance=%s run=%s err=%s",
                action_name,
                instance.id,
                run_id,
                exc,
            )
            rendered = None

    duration_seconds = time.monotonic() - started_at

    # Step 6 — spend attribution (best-effort, never fails dispatch).
    spend_usd = await _record_spend_safe(
        db,
        instance=instance,
        run_id=run_id,
        duration_seconds=duration_seconds,
        invocation_subject_id=invocation_subject_id,
    )

    logger.info(
        "action_dispatcher.complete instance=%s action=%s kind=%s run=%s "
        "duration=%.3fs artifacts=%d",
        instance.id,
        action_name,
        kind,
        run_id,
        duration_seconds,
        len(artifact_ids),
    )

    return ActionDispatchResult(
        output=output,
        artifacts=artifact_ids,
        spend_usd=spend_usd,
        duration_seconds=duration_seconds,
        error=None,
        rendered=rendered,
    )


# Re-exports kept conservative to match the rest of services/apps/.
__all__ = [
    "ActionDispatchError",
    "ActionDispatchFailed",
    "ActionDispatchResult",
    "ActionHandlerNotSupported",
    "ActionInputInvalid",
    "ActionOutputInvalid",
    "AppActionNotFound",
    "AppInstanceNotFound",
    "dispatch_app_action",
]


