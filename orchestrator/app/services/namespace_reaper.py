"""
Namespace Reaper — cleans up proj-* namespaces stuck in Terminating state.

Root cause: PVC-backed volume unmounts can hang when the btrfs-CSI gRPC
connection drops, creating a deadlock between kubernetes.io/pvc-protection
finalizers and pod termination.  This reaper breaks the deadlock via
2-stage escalation:

  1. Force-delete pods remaining in the namespace
  2. Strip finalizers from the namespace itself

PVC finalizers are intentionally NOT stripped — doing so would trigger
CSI DeleteVolume which destroys the btrfs subvolume.  Since S3 sync is
non-blocking, the subvolume could be destroyed before sync completes,
causing data loss.  K8s pvc-protection controller removes the finalizer
automatically once pods are gone.
"""

import logging
from dataclasses import dataclass, field

from kubernetes import client
from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)


@dataclass
class ReaperResult:
    """Outcome of a single reaper run."""

    namespaces_reaped: int = 0
    pods_deleted: int = 0
    namespaces_finalized: int = 0
    errors: list[str] = field(default_factory=list)


class NamespaceReaper:
    """Reaps proj-* namespaces stuck in Terminating state."""

    def __init__(self, core_v1: client.CoreV1Api | None = None):
        if core_v1 is None:
            from kubernetes import config

            config.load_incluster_config()
            core_v1 = client.CoreV1Api()
        self._v1 = core_v1

    def reap(self) -> ReaperResult:
        """Find and clean up all stuck proj-* Terminating namespaces."""
        result = ReaperResult()

        stuck = self._list_stuck_namespaces()
        if not stuck:
            logger.info("No stuck proj-* namespaces found")
            return result

        logger.info("Found %d stuck namespace(s)", len(stuck))

        for ns in stuck:
            ns_name = ns.metadata.name
            logger.info("Reaping namespace: %s", ns_name)
            result.namespaces_reaped += 1

            self._force_delete_pods(ns_name, result)
            self._strip_namespace_finalizers(ns_name, result)

        logger.info(
            "Reaper complete — namespaces=%d pods=%d finalized=%d errors=%d",
            result.namespaces_reaped,
            result.pods_deleted,
            result.namespaces_finalized,
            len(result.errors),
        )
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _list_stuck_namespaces(self) -> list[client.V1Namespace]:
        """Return proj-* namespaces in Terminating phase."""
        all_ns = self._v1.list_namespace().items
        return [
            ns
            for ns in all_ns
            if ns.metadata.name.startswith("proj-") and ns.status.phase == "Terminating"
        ]

    def _force_delete_pods(self, namespace: str, result: ReaperResult) -> None:
        """Stage 1: force-delete all pods in the namespace."""
        try:
            pods = self._v1.list_namespaced_pod(namespace=namespace).items
        except ApiException as e:
            if e.status == 404:
                return
            result.errors.append(f"list pods in {namespace}: {e.reason}")
            return

        for pod in pods:
            try:
                self._v1.delete_namespaced_pod(
                    name=pod.metadata.name,
                    namespace=namespace,
                    body=client.V1DeleteOptions(grace_period_seconds=0),
                    grace_period_seconds=0,
                )
                result.pods_deleted += 1
                logger.info("  Force-deleted pod: %s", pod.metadata.name)
            except ApiException as e:
                if e.status != 404:
                    result.errors.append(
                        f"delete pod {pod.metadata.name} in {namespace}: {e.reason}"
                    )

    def _strip_namespace_finalizers(self, namespace: str, result: ReaperResult) -> None:
        """Stage 3: strip finalizers from the namespace itself."""
        try:
            ns_obj = self._v1.read_namespace(name=namespace)
        except ApiException as e:
            if e.status == 404:
                return
            result.errors.append(f"read namespace {namespace}: {e.reason}")
            return

        if not ns_obj.spec.finalizers:
            return

        try:
            self._v1.replace_namespace_finalize(
                name=namespace,
                body=client.V1Namespace(
                    metadata=client.V1ObjectMeta(name=namespace),
                    spec=client.V1NamespaceSpec(finalizers=[]),
                ),
            )
            result.namespaces_finalized += 1
            logger.info("  Stripped namespace finalizers from: %s", namespace)
        except ApiException as e:
            if e.status != 404:
                result.errors.append(f"finalize namespace {namespace}: {e.reason}")
