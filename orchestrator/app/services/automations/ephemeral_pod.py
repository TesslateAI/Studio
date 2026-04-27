"""Tier 1 ephemeral compute pod for AutomationRuns (Phase 4).

The dispatcher routes ``contract.max_compute_tier == 1`` runs through this
module instead of :func:`wake.provision_for_run`. Tier 1 is one-shot:
spin up a small pod, run the agent, harvest the write-tracker sidecar's
log lines into ``automation_run_artifacts``, and let the pod garbage-
collect itself (``restartPolicy: Never`` + the controller's reaper).

Why a separate module from ``compute_manager.ComputeManager``
-------------------------------------------------------------
``compute_manager`` covers Tier-1 *project* compute (interactive shells,
``run_command`` one-shots driven by routers / agent tools). Those pods
mount the project's btrfs PVC and run with the owner's UID. The
*automation* path is materially different:

* Pod identity is the AutomationRun (env carries ``OPENSAIL_RUN_ID``),
  not the project. Naming + labels pivot on run id so the controller can
  reap by selector.
* Workspace mount is conditional on the resolved Grant — Tier-0 control-
  plane runs may have no fs access at all.
* The run-history needs the write-tracker sidecar log surfaced as an
  artifact, which compute_manager does not produce.

The two paths share the YAML template at
``k8s/base/compute-pool/ephemeral-pod-template.yaml`` (rendered here) and
the same compute-pool namespace + NetworkPolicy / ResourceQuota
(applied by ``ComputeManager._ensure_compute_namespace`` — we call that
on entry so the cluster state stays one-source-of-truth).

Sidecar lifecycle
-----------------
The write-tracker is appended programmatically (Task 2/3). When the
agent container exits, kubelet sends SIGTERM to the sidecar; the sidecar
flushes inotify and exits. ``activeDeadlineSeconds=1800`` is the safety
net — neither container can outlive 30 minutes.

K8s client convention
---------------------
We mirror :mod:`wake` and :mod:`compute_manager`: synchronous
``kubernetes`` library wrapped in ``asyncio.to_thread`` so the event
loop stays free. The codebase did not standardise on
``kubernetes_asyncio``; switching here would diverge from the existing
container-orchestration code path.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# Path to the canonical YAML template. Resolved relative to the repo root
# so the same logic works for in-tree dev (running pytest from the
# orchestrator dir) and the packaged container (where the file is copied
# into the image at build time).
_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[4]
    / "k8s"
    / "base"
    / "compute-pool"
    / "ephemeral-pod-template.yaml"
)

# Sidecar image — built from ``services/btrfs-csi/cmd/write-tracker``.
# Override in tests via ``render_pod(write_tracker_image=...)``.
_DEFAULT_WRITE_TRACKER_IMAGE = "opensail-write-tracker:latest"

# Mount path for the project workspace inside the pod. The trailing
# ``{run_id}`` namespace lets multiple Tier-1 pods running on the same
# node distinguish their workspace volumes in their own filesystem
# views (mount paths are pod-local, but downstream tooling logs the
# absolute path).
_WORKSPACE_MOUNT_PARENT = "/automations"

# Phase-4 readiness: how long we wait for the pod to reach Running
# before we consider startup failed. Short — Tier-1 cold-start is the
# fast path and a stuck pod should not pin a worker slot.
_DEFAULT_READY_TIMEOUT_SECONDS = 90

# How long we block waiting for the pod to reach a terminal phase
# before yielding to the caller. The pod-level
# ``activeDeadlineSeconds=1800`` is the hard ceiling; this default
# keeps the in-process wait shorter so the controller can poll.
_DEFAULT_TERMINAL_TIMEOUT_SECONDS = 1800

# Tail this many sidecar log lines when harvesting. The sidecar emits
# one JSON line per write event; in practice a healthy run has zero,
# a leaky-tool run has a handful. Cap protects against a sidecar that
# floods (broken inotify watcher).
_TRACKER_LOG_TAIL_LINES = 500


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FilesystemGrant:
    """Subset of a Grant that this module actually uses.

    Phase 4's grant_resolver returns a richer object; we only need the
    bits that drive the pod surface: whether to mount a workspace, the
    backing PVC name, and whether the mount is read-only. Keeping a
    narrow interface lets the resolver evolve without re-spinning the
    pod template.
    """

    has_filesystem: bool
    pvc_name: str | None = None
    read_only: bool = False
    volume_id: str | None = None


@dataclass(frozen=True)
class TrackerWarning:
    """One parsed write-tracker JSON log line."""

    path: str
    ts: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "ts": self.ts}


@dataclass
class EphemeralPodResult:
    """Outcome of one Tier-1 ephemeral run.

    ``terminal_phase`` is the final pod-level ``status.phase``
    (``Succeeded`` / ``Failed`` / ``Unknown``). ``exit_code`` is the
    agent container's exit code, or ``None`` if the container never
    started (image pull failure, scheduling failure).
    """

    pod_name: str
    namespace: str
    terminal_phase: str
    exit_code: int | None
    duration_seconds: float
    tracker_warnings: list[TrackerWarning] = field(default_factory=list)
    artifact_id: UUID | None = None
    reason: str | None = None


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------


def _load_template() -> dict[str, Any]:
    """Read + parse the YAML template fresh per call.

    The template is small (~3 KiB); the once-per-run read cost is
    irrelevant compared to the K8s API round-trip. Re-reading also
    means an ops-driven template edit takes effect on the next run
    without a process restart — useful for emergency hardening tweaks.
    """
    if not _TEMPLATE_PATH.exists():
        raise FileNotFoundError(
            f"ephemeral pod template missing at {_TEMPLATE_PATH}; "
            "verify k8s/base/compute-pool/ephemeral-pod-template.yaml"
        )
    return yaml.safe_load(_TEMPLATE_PATH.read_text(encoding="utf-8"))


def _substitute_strings(node: Any, replacements: dict[str, str]) -> Any:
    """Recursively substitute ``{key}`` placeholders in a parsed YAML tree.

    We deliberately do NOT use ``str.format_map`` on the whole document
    string before parsing because legitimate YAML may include ``{`` /
    ``}`` characters (e.g., in env values). Walking the tree keeps the
    substitution scope to leaf strings.
    """
    if isinstance(node, dict):
        return {k: _substitute_strings(v, replacements) for k, v in node.items()}
    if isinstance(node, list):
        return [_substitute_strings(v, replacements) for v in node]
    if isinstance(node, str):
        out = node
        for key, value in replacements.items():
            placeholder = "{" + key + "}"
            if placeholder in out:
                out = out.replace(placeholder, value)
        return out
    return node


def _add_workspace_mount(
    pod: dict[str, Any],
    *,
    run_id: UUID,
    grant: FilesystemGrant,
) -> None:
    """Append the workspace volume + mount when the Grant allows fs access.

    No-op when ``grant.has_filesystem`` is False — Tier-0 / read-only
    metadata-only runs never see /automations/{run_id}.
    """
    if not grant.has_filesystem or not grant.pvc_name:
        return

    mount_path = f"{_WORKSPACE_MOUNT_PARENT}/{run_id}"
    volume_name = "workspace"

    spec = pod["spec"]
    spec.setdefault("volumes", []).append(
        {
            "name": volume_name,
            "persistentVolumeClaim": {
                "claimName": grant.pvc_name,
                "readOnly": bool(grant.read_only),
            },
        }
    )
    # Mount on the agent container only — the write-tracker watches the
    # root filesystem and reports anything outside /tmp + /automations,
    # so giving it the workspace mount would just be noise.
    agent = spec["containers"][0]
    agent.setdefault("volumeMounts", []).append(
        {
            "name": volume_name,
            "mountPath": mount_path,
            "readOnly": bool(grant.read_only),
        }
    )
    # Update the agent's working directory so the runtime starts in the
    # workspace dir without having to know the run id.
    agent["workingDir"] = mount_path


def _build_write_tracker_container(
    *, image: str, exclude_paths: list[str] | None = None
) -> dict[str, Any]:
    """Container spec for the inotify write-tracker sidecar.

    Mounts the host root **read-only** so inotify can observe writes
    anywhere — but the sidecar itself cannot mutate state. The
    exclude-path env var filters expected write surfaces (/tmp,
    /automations) so the JSON log only carries genuine surprises.
    """
    excludes = exclude_paths or ["/tmp", _WORKSPACE_MOUNT_PARENT]
    return {
        "name": "write-tracker",
        "image": image,
        "imagePullPolicy": "IfNotPresent",
        "env": [
            {"name": "OPENSAIL_TRACKER_EXCLUDES", "value": ":".join(excludes)},
            # Top-level dirs to recursively watch. Skipping /proc and /sys
            # avoids inotify limits hitting kernel pseudo-fs quirks.
            {"name": "OPENSAIL_TRACKER_ROOTS", "value": "/etc:/var:/opt:/usr"},
        ],
        "resources": {
            "requests": {"cpu": "10m", "memory": "32Mi"},
            "limits": {"cpu": "50m", "memory": "64Mi"},
        },
        "securityContext": {
            "allowPrivilegeEscalation": False,
            "readOnlyRootFilesystem": True,
            "runAsNonRoot": True,
            "runAsUser": 1000,
            "runAsGroup": 1000,
            "capabilities": {"drop": ["ALL"]},
            "seccompProfile": {"type": "RuntimeDefault"},
        },
    }


def render_pod(
    *,
    run_id: UUID,
    automation_id: UUID,
    namespace: str,
    image: str,
    grant: FilesystemGrant,
    write_tracker_image: str = _DEFAULT_WRITE_TRACKER_IMAGE,
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Render a fully-substituted Pod manifest as a plain dict.

    The dict shape matches what ``kubernetes.client.CoreV1Api`` accepts
    for ``create_namespaced_pod`` (and what ``kubectl apply -f -`` would
    accept). Returning a dict instead of a typed V1Pod keeps the caller
    decoupled from the kubernetes import — tests can inspect the
    structure directly without instantiating client objects.
    """
    pod = _load_template()
    replacements = {
        "run_id": str(run_id),
        "automation_id": str(automation_id),
        "namespace": namespace,
        "image": image,
        # Tier-0 runs have no volume; substitute empty so the env var is
        # an empty string rather than a literal "{volume_id}".
        "volume_id": grant.volume_id or "",
    }
    pod = _substitute_strings(pod, replacements)

    # Conditionally graft on the workspace volume + mount.
    _add_workspace_mount(pod, run_id=run_id, grant=grant)

    # Apply extra env (e.g., budget keys) before appending the sidecar
    # so the env list lives only on the agent container.
    if extra_env:
        agent_env = pod["spec"]["containers"][0].setdefault("env", [])
        for key, value in extra_env.items():
            agent_env.append({"name": key, "value": value})

    # Sidecar is always added — the cost (50m CPU / 64Mi mem at the
    # ceiling) is small enough to be worth the universal write-leak
    # signal.
    sidecar = _build_write_tracker_container(image=write_tracker_image)
    pod["spec"]["containers"].append(sidecar)

    return pod


# ---------------------------------------------------------------------------
# K8s client adapter
# ---------------------------------------------------------------------------


def _default_core_v1() -> Any:
    """Lazily build a CoreV1Api client. Mirrors compute_manager's pattern."""
    from kubernetes import client as k8s_client
    from kubernetes import config as k8s_config

    try:
        k8s_config.load_incluster_config()
    except k8s_config.ConfigException:
        k8s_config.load_kube_config()
    return k8s_client.CoreV1Api()


# ---------------------------------------------------------------------------
# Pod lifecycle
# ---------------------------------------------------------------------------


async def _create_pod(core_v1: Any, namespace: str, body: dict[str, Any]) -> str:
    """Submit the rendered pod and return its resolved name.

    Returns the name from ``status.metadata.name`` on the response so
    the caller observes any name-generation done server-side (e.g., if
    we ever switch to ``generateName``).
    """
    created = await asyncio.to_thread(
        core_v1.create_namespaced_pod, namespace=namespace, body=body
    )
    name = (
        getattr(getattr(created, "metadata", None), "name", None)
        or body.get("metadata", {}).get("name", "")
    )
    return str(name)


async def _wait_for_terminal(
    core_v1: Any,
    *,
    name: str,
    namespace: str,
    timeout_seconds: int,
    poll_interval_seconds: float = 1.0,
) -> tuple[str, int | None, str | None]:
    """Poll until the pod reaches a terminal phase or the timeout fires.

    Returns ``(phase, exit_code, reason)``. ``exit_code`` is None if the
    agent container never started (e.g., ImagePullBackOff). ``reason``
    is set when the wait timed out so the caller can surface it.
    """
    deadline = asyncio.get_event_loop().time() + timeout_seconds
    last_phase = "Unknown"
    while asyncio.get_event_loop().time() < deadline:
        try:
            pod = await asyncio.to_thread(
                core_v1.read_namespaced_pod, name=name, namespace=namespace
            )
        except Exception as exc:  # noqa: BLE001 — informational, retry
            logger.debug(
                "ephemeral_pod: read_namespaced_pod transient err name=%s err=%r",
                name,
                exc,
            )
            await asyncio.sleep(poll_interval_seconds)
            continue
        phase = (getattr(pod.status, "phase", None) or "Unknown") if pod.status else "Unknown"
        last_phase = phase
        if phase in ("Succeeded", "Failed"):
            exit_code = _extract_agent_exit_code(pod)
            return phase, exit_code, None
        await asyncio.sleep(poll_interval_seconds)
    return last_phase, None, "wait_timeout"


def _extract_agent_exit_code(pod: Any) -> int | None:
    """Pull the agent container's terminated exit code out of pod status."""
    statuses = getattr(pod.status, "container_statuses", None) or []
    for cs in statuses:
        if cs.name != "agent":
            continue
        state = getattr(cs, "state", None)
        terminated = getattr(state, "terminated", None) if state else None
        if terminated is not None:
            return getattr(terminated, "exit_code", None)
    return None


async def _harvest_tracker_log(
    core_v1: Any,
    *,
    name: str,
    namespace: str,
    tail_lines: int = _TRACKER_LOG_TAIL_LINES,
) -> list[TrackerWarning]:
    """Read sidecar logs, parse JSON lines, return parsed warnings.

    Anything that fails to parse is logged and dropped — the tracker
    log is best-effort signal, not authoritative state. A garbled
    sidecar must NOT prevent the run's terminal status from landing.
    """
    try:
        raw = await asyncio.to_thread(
            core_v1.read_namespaced_pod_log,
            name=name,
            namespace=namespace,
            container="write-tracker",
            tail_lines=tail_lines,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "ephemeral_pod: tracker log read failed name=%s err=%r", name, exc
        )
        return []
    warnings: list[TrackerWarning] = []
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            logger.debug("ephemeral_pod: skipping non-JSON tracker line: %r", line)
            continue
        if obj.get("event") != "write_outside_tmp":
            continue
        path = obj.get("path")
        ts = obj.get("ts")
        if not isinstance(path, str) or not isinstance(ts, str):
            continue
        warnings.append(TrackerWarning(path=path, ts=ts))
    return warnings


async def _persist_tracker_artifact(
    db: Any,
    *,
    run_id: UUID,
    warnings: list[TrackerWarning],
) -> UUID | None:
    """Write the tracker warnings as a single ``log`` artifact.

    No-op when the tracker logged nothing (the common case). When db
    is None (called from a thin path that doesn't have a session), we
    skip persistence and let the caller surface the warnings via the
    return value instead.
    """
    if not warnings or db is None:
        return None
    try:
        from .artifacts import create_artifact

        body = "\n".join(json.dumps(w.to_dict()) for w in warnings) + "\n"
        artifact = await create_artifact(
            db,
            run_id=run_id,
            kind="log",
            name="write-tracker.log",
            mime_type="application/x-ndjson",
            content=body,
            metadata={
                "source": "ephemeral_pod.write_tracker",
                "warning_count": len(warnings),
                # First few entries inline for snappy UI rendering; the
                # full log is in the artifact body.
                "preview": [w.to_dict() for w in warnings[:5]],
            },
        )
        return artifact.id
    except Exception as exc:  # noqa: BLE001 — non-fatal; warnings still flow back via return
        logger.warning(
            "ephemeral_pod: persist tracker artifact failed run=%s err=%r",
            run_id,
            exc,
        )
        return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def run_in_ephemeral_pod(
    *,
    run_id: UUID,
    automation_id: UUID,
    image: str,
    grant: FilesystemGrant,
    namespace: str | None = None,
    db: Any | None = None,
    core_v1: Any | None = None,
    write_tracker_image: str = _DEFAULT_WRITE_TRACKER_IMAGE,
    extra_env: dict[str, str] | None = None,
    terminal_timeout_seconds: int = _DEFAULT_TERMINAL_TIMEOUT_SECONDS,
) -> EphemeralPodResult:
    """End-to-end Tier 1 run: render → submit → wait → harvest.

    Args:
        run_id / automation_id: Identity stamped on the pod (labels +
            env vars) and used for the artifact attribution.
        image: Agent runtime image. Convention: callers pass
            ``settings.k8s_devserver_image`` unless they need a tier-
            specific override (e.g., a hardened minimal image).
        grant: Resolved filesystem grant. ``has_filesystem=False``
            yields a pod with no workspace mount.
        namespace: Override compute-pool namespace; defaults to
            ``settings.compute_pool_namespace``.
        db: Optional async session for artifact persistence. When None,
            tracker warnings are returned via the result but not
            written to ``automation_run_artifacts``.
        core_v1: Optional injected K8s client for tests. Production
            callers pass None and we lazy-init via the in-cluster
            config (mirrors compute_manager).
        write_tracker_image: Override the sidecar image (tests / local).
        extra_env: Additional env vars stamped on the agent container
            (typically the LiteLLM key envelope from the dispatcher).
        terminal_timeout_seconds: Caller-side wait ceiling. The pod's
            own ``activeDeadlineSeconds=1800`` is the K8s safety net.
    """
    from ...config import get_settings

    started = datetime.now(UTC)
    ns = namespace or get_settings().compute_pool_namespace

    if core_v1 is None:
        core_v1 = _default_core_v1()

    body = render_pod(
        run_id=run_id,
        automation_id=automation_id,
        namespace=ns,
        image=image,
        grant=grant,
        write_tracker_image=write_tracker_image,
        extra_env=extra_env,
    )
    pod_name = body["metadata"]["name"]

    try:
        actual_name = await _create_pod(core_v1, ns, body)
        if actual_name:
            pod_name = actual_name
    except Exception as exc:  # noqa: BLE001 — surface as failure result
        logger.error(
            "ephemeral_pod: create failed run=%s ns=%s err=%r",
            run_id,
            ns,
            exc,
        )
        return EphemeralPodResult(
            pod_name=pod_name,
            namespace=ns,
            terminal_phase="Unknown",
            exit_code=None,
            duration_seconds=(datetime.now(UTC) - started).total_seconds(),
            reason=f"create_failed: {exc!r}",
        )

    phase, exit_code, wait_reason = await _wait_for_terminal(
        core_v1,
        name=pod_name,
        namespace=ns,
        timeout_seconds=terminal_timeout_seconds,
    )

    # Harvest the sidecar log even on timeout — partial logs are still
    # useful for the run-history detail view.
    warnings = await _harvest_tracker_log(
        core_v1, name=pod_name, namespace=ns
    )
    artifact_id = await _persist_tracker_artifact(
        db, run_id=run_id, warnings=warnings
    )

    return EphemeralPodResult(
        pod_name=pod_name,
        namespace=ns,
        terminal_phase=phase,
        exit_code=exit_code,
        duration_seconds=(datetime.now(UTC) - started).total_seconds(),
        tracker_warnings=warnings,
        artifact_id=artifact_id,
        reason=wait_reason,
    )


__all__ = [
    "EphemeralPodResult",
    "FilesystemGrant",
    "TrackerWarning",
    "render_pod",
    "run_in_ephemeral_pod",
]
