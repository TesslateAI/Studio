"""Unit tests for ``services.automations.ephemeral_pod``.

Coverage matrix:

* :func:`render_pod` produces a structurally valid pod dict.
* :func:`render_pod` always appends the write-tracker sidecar.
* :func:`render_pod` adds the workspace volume + mount only when the
  Grant says so.
* :func:`render_pod` substitutes every ``{run_id}`` / ``{automation_id}``
  / ``{namespace}`` / ``{image}`` / ``{volume_id}`` placeholder.
* End-to-end :func:`run_in_ephemeral_pod` against a fake CoreV1Api:
  pod is created, terminal phase is observed, sidecar log is parsed
  into TrackerWarning rows, and the artifact is persisted on the
  injected DB session.

The K8s client is a hand-rolled fake so the tests do NOT depend on
the real ``kubernetes`` package being importable.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Importing the model modules registers tables on Base.metadata.
from app import models, models_automations  # noqa: F401
from app.database import Base
from app.models_automations import AutomationRunArtifact
from app.services.automations.ephemeral_pod import (
    EphemeralPodResult,
    FilesystemGrant,
    TrackerWarning,
    render_pod,
    run_in_ephemeral_pod,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    """Per-test SQLite engine — mirrors test_artifacts.py's pattern."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


# ---------------------------------------------------------------------------
# Fake CoreV1Api
# ---------------------------------------------------------------------------


class _FakeCoreV1:
    """Minimal duck-typed CoreV1Api covering the surface ephemeral_pod uses.

    ``phases`` is a queue of pod-status phases returned in order from
    successive ``read_namespaced_pod`` calls; once exhausted, the last
    value sticks. ``log_text`` is what ``read_namespaced_pod_log``
    returns. Counters expose call counts so tests can assert the
    happy-path control flow without mocking framework noise.
    """

    def __init__(
        self,
        *,
        phases: list[str],
        log_text: str = "",
        agent_exit_code: int | None = 0,
        create_raises: Exception | None = None,
    ) -> None:
        self._phases = list(phases)
        self._log_text = log_text
        self._agent_exit_code = agent_exit_code
        self._create_raises = create_raises
        self.created_pods: list[dict[str, Any]] = []
        self.log_calls: list[dict[str, Any]] = []
        self.read_calls = 0

    def create_namespaced_pod(self, *, namespace: str, body: Any) -> Any:
        if self._create_raises is not None:
            raise self._create_raises
        # body may be a dict (our renderer) or a typed V1Pod (real client).
        if isinstance(body, dict):
            self.created_pods.append(body)
            name = body.get("metadata", {}).get("name", "")
        else:
            self.created_pods.append({"raw": body})
            name = getattr(getattr(body, "metadata", None), "name", "")
        return SimpleNamespace(metadata=SimpleNamespace(name=name))

    def read_namespaced_pod(self, *, name: str, namespace: str) -> Any:  # noqa: ARG002
        self.read_calls += 1
        if self._phases:
            phase = self._phases.pop(0) if len(self._phases) > 1 else self._phases[0]
        else:
            phase = "Pending"
        terminated = None
        if phase in ("Succeeded", "Failed") and self._agent_exit_code is not None:
            terminated = SimpleNamespace(exit_code=self._agent_exit_code)
        agent_status = SimpleNamespace(
            name="agent",
            state=SimpleNamespace(terminated=terminated),
        )
        return SimpleNamespace(
            status=SimpleNamespace(
                phase=phase,
                container_statuses=[agent_status],
            ),
        )

    def read_namespaced_pod_log(
        self,
        *,
        name: str,
        namespace: str,
        container: str,
        tail_lines: int,
    ) -> str:
        self.log_calls.append(
            {
                "name": name,
                "namespace": namespace,
                "container": container,
                "tail_lines": tail_lines,
            }
        )
        return self._log_text


# ---------------------------------------------------------------------------
# render_pod tests
# ---------------------------------------------------------------------------


def test_render_pod_substitutes_all_placeholders() -> None:
    run_id = uuid.uuid4()
    automation_id = uuid.uuid4()
    pod = render_pod(
        run_id=run_id,
        automation_id=automation_id,
        namespace="tesslate-compute-pool",
        image="opensail-agent:42",
        grant=FilesystemGrant(has_filesystem=False),
        write_tracker_image="opensail-write-tracker:test",
    )

    # Metadata substitutions.
    assert pod["metadata"]["name"] == f"ephemeral-{run_id}"
    assert pod["metadata"]["namespace"] == "tesslate-compute-pool"
    labels = pod["metadata"]["labels"]
    assert labels["tesslate.io/run-id"] == str(run_id)
    assert labels["tesslate.io/automation-id"] == str(automation_id)

    # The agent env carries every OPENSAIL_* marker.
    agent = pod["spec"]["containers"][0]
    env = {e["name"]: e["value"] for e in agent["env"]}
    assert env["OPENSAIL_RUN_ID"] == str(run_id)
    assert env["OPENSAIL_AUTOMATION_ID"] == str(automation_id)
    assert env["OPENSAIL_NAMESPACE"] == "tesslate-compute-pool"
    assert env["OPENSAIL_VOLUME_ID"] == ""  # No grant → empty string
    # The image literal flows through unchanged.
    assert agent["image"] == "opensail-agent:42"


def test_render_pod_always_appends_sidecar() -> None:
    pod = render_pod(
        run_id=uuid.uuid4(),
        automation_id=uuid.uuid4(),
        namespace="ns",
        image="agent:1",
        grant=FilesystemGrant(has_filesystem=False),
        write_tracker_image="custom-tracker:7",
    )
    containers = pod["spec"]["containers"]
    assert len(containers) == 2
    assert containers[1]["name"] == "write-tracker"
    assert containers[1]["image"] == "custom-tracker:7"
    # Sidecar runs read-only and dropped caps — verify the hardening
    # bits we care about.
    sec = containers[1]["securityContext"]
    assert sec["readOnlyRootFilesystem"] is True
    assert sec["allowPrivilegeEscalation"] is False
    assert sec["capabilities"]["drop"] == ["ALL"]


def test_render_pod_skips_workspace_when_grant_disallows_fs() -> None:
    pod = render_pod(
        run_id=uuid.uuid4(),
        automation_id=uuid.uuid4(),
        namespace="ns",
        image="agent:1",
        grant=FilesystemGrant(has_filesystem=False),
    )
    volume_names = {v["name"] for v in pod["spec"]["volumes"]}
    # /tmp is always present; no workspace volume.
    assert "tmp" in volume_names
    assert "workspace" not in volume_names
    # Agent has only the /tmp mount.
    agent_mounts = pod["spec"]["containers"][0].get("volumeMounts", [])
    mount_paths = {m["mountPath"] for m in agent_mounts}
    assert mount_paths == {"/tmp"}


def test_render_pod_adds_workspace_when_grant_present() -> None:
    run_id = uuid.uuid4()
    pod = render_pod(
        run_id=run_id,
        automation_id=uuid.uuid4(),
        namespace="ns",
        image="agent:1",
        grant=FilesystemGrant(
            has_filesystem=True,
            pvc_name="vol-pvc-abc",
            read_only=False,
            volume_id="abc",
        ),
    )
    volumes = pod["spec"]["volumes"]
    workspace_volume = next(v for v in volumes if v["name"] == "workspace")
    assert workspace_volume["persistentVolumeClaim"]["claimName"] == "vol-pvc-abc"
    assert workspace_volume["persistentVolumeClaim"]["readOnly"] is False

    agent = pod["spec"]["containers"][0]
    mount_paths = {m["mountPath"] for m in agent["volumeMounts"]}
    expected_workspace = f"/automations/{run_id}"
    assert expected_workspace in mount_paths
    assert "/tmp" in mount_paths
    # workingDir tracks the workspace mount so the runtime starts there.
    assert agent["workingDir"] == expected_workspace
    # OPENSAIL_VOLUME_ID is now populated.
    env = {e["name"]: e["value"] for e in agent["env"]}
    assert env["OPENSAIL_VOLUME_ID"] == "abc"


def test_render_pod_appends_extra_env_to_agent_only() -> None:
    pod = render_pod(
        run_id=uuid.uuid4(),
        automation_id=uuid.uuid4(),
        namespace="ns",
        image="agent:1",
        grant=FilesystemGrant(has_filesystem=False),
        extra_env={"OPENSAIL_LITELLM_KEY": "sk-test"},
    )
    agent_env = {e["name"]: e["value"] for e in pod["spec"]["containers"][0]["env"]}
    assert agent_env["OPENSAIL_LITELLM_KEY"] == "sk-test"
    # Sidecar must NOT receive the LiteLLM key.
    sidecar_env = {e["name"]: e["value"] for e in pod["spec"]["containers"][1]["env"]}
    assert "OPENSAIL_LITELLM_KEY" not in sidecar_env


def test_render_pod_security_baseline_on_agent() -> None:
    """Agent container locks down the surface required by Tier 1 plan."""
    pod = render_pod(
        run_id=uuid.uuid4(),
        automation_id=uuid.uuid4(),
        namespace="ns",
        image="agent:1",
        grant=FilesystemGrant(has_filesystem=False),
    )
    sec = pod["spec"]["containers"][0]["securityContext"]
    assert sec["readOnlyRootFilesystem"] is True
    assert sec["runAsNonRoot"] is True
    assert sec["allowPrivilegeEscalation"] is False
    # Pod-level deadline + restartPolicy enforce one-shot semantics.
    assert pod["spec"]["restartPolicy"] == "Never"
    assert pod["spec"]["activeDeadlineSeconds"] == 1800
    # /tmp is tmpfs-backed.
    tmp_vol = next(v for v in pod["spec"]["volumes"] if v["name"] == "tmp")
    assert tmp_vol["emptyDir"]["medium"] == "Memory"
    assert tmp_vol["emptyDir"]["sizeLimit"] == "256Mi"
    # Resource ceilings match the plan: limits cpu=500m mem=512Mi.
    limits = pod["spec"]["containers"][0]["resources"]["limits"]
    assert limits["cpu"] == "500m"
    assert limits["memory"] == "512Mi"


# ---------------------------------------------------------------------------
# run_in_ephemeral_pod end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_in_ephemeral_pod_happy_path_persists_warnings(
    db: AsyncSession,
) -> None:
    """Pod runs to Succeeded; tracker emits two warnings; one artifact is written."""
    run_id = uuid.uuid4()
    automation_id = uuid.uuid4()
    log_text = "\n".join(
        [
            json.dumps({"event": "write_tracker_started", "path": "/var", "ts": "2026-04-26T00:00:00Z"}),
            json.dumps(
                {
                    "event": "write_outside_tmp",
                    "path": "/var/log/foo",
                    "ts": "2026-04-26T00:00:01Z",
                }
            ),
            json.dumps(
                {
                    "event": "write_outside_tmp",
                    "path": "/etc/fishy",
                    "ts": "2026-04-26T00:00:02Z",
                }
            ),
            "not-json garbage",
        ]
    )
    fake = _FakeCoreV1(
        phases=["Succeeded"],
        log_text=log_text,
        agent_exit_code=0,
    )

    result = await run_in_ephemeral_pod(
        run_id=run_id,
        automation_id=automation_id,
        image="agent:test",
        grant=FilesystemGrant(has_filesystem=False),
        namespace="tesslate-compute-pool",
        db=db,
        core_v1=fake,
        write_tracker_image="opensail-write-tracker:test",
    )

    assert isinstance(result, EphemeralPodResult)
    assert result.terminal_phase == "Succeeded"
    assert result.exit_code == 0
    assert len(result.tracker_warnings) == 2
    assert {w.path for w in result.tracker_warnings} == {"/var/log/foo", "/etc/fishy"}
    # Pod was created exactly once with our rendered body.
    assert len(fake.created_pods) == 1
    created = fake.created_pods[0]
    assert created["metadata"]["name"] == f"ephemeral-{run_id}"
    # Artifact landed in the DB.
    assert result.artifact_id is not None
    row = await db.get(AutomationRunArtifact, result.artifact_id)
    assert row is not None
    assert row.kind == "log"
    assert row.name == "write-tracker.log"
    assert row.run_id == run_id
    assert row.meta["warning_count"] == 2
    assert row.meta["preview"][0]["path"] == "/var/log/foo"


@pytest.mark.asyncio
async def test_run_in_ephemeral_pod_create_failure_returns_clean_result(
    db: AsyncSession,
) -> None:
    """create_namespaced_pod raises → caller sees a Result with reason set."""
    fake = _FakeCoreV1(
        phases=["Pending"],
        log_text="",
        create_raises=RuntimeError("ImagePullBackOff"),
    )
    result = await run_in_ephemeral_pod(
        run_id=uuid.uuid4(),
        automation_id=uuid.uuid4(),
        image="agent:test",
        grant=FilesystemGrant(has_filesystem=False),
        namespace="ns",
        db=db,
        core_v1=fake,
    )
    assert result.terminal_phase == "Unknown"
    assert result.exit_code is None
    assert result.reason is not None and "create_failed" in result.reason
    # No log harvest on create failure (we never had a name to query).
    assert fake.log_calls == []


@pytest.mark.asyncio
async def test_run_in_ephemeral_pod_no_tracker_lines_no_artifact(
    db: AsyncSession,
) -> None:
    """Empty sidecar log → no AutomationRunArtifact row written."""
    fake = _FakeCoreV1(phases=["Succeeded"], log_text="", agent_exit_code=0)
    result = await run_in_ephemeral_pod(
        run_id=uuid.uuid4(),
        automation_id=uuid.uuid4(),
        image="agent:test",
        grant=FilesystemGrant(has_filesystem=False),
        namespace="ns",
        db=db,
        core_v1=fake,
    )
    assert result.terminal_phase == "Succeeded"
    assert result.tracker_warnings == []
    assert result.artifact_id is None


@pytest.mark.asyncio
async def test_run_in_ephemeral_pod_log_request_targets_sidecar(
    db: AsyncSession,
) -> None:
    """We always read logs from the write-tracker container by name."""
    fake = _FakeCoreV1(phases=["Succeeded"], log_text="", agent_exit_code=0)
    await run_in_ephemeral_pod(
        run_id=uuid.uuid4(),
        automation_id=uuid.uuid4(),
        image="agent:test",
        grant=FilesystemGrant(has_filesystem=False),
        namespace="ns",
        db=db,
        core_v1=fake,
    )
    assert len(fake.log_calls) == 1
    assert fake.log_calls[0]["container"] == "write-tracker"


@pytest.mark.asyncio
async def test_run_in_ephemeral_pod_timeout_still_harvests_log(
    db: AsyncSession,
) -> None:
    """Wait timeout → reason='wait_timeout' but tracker log still parsed."""
    log_text = json.dumps(
        {
            "event": "write_outside_tmp",
            "path": "/var/cache/x",
            "ts": "2026-04-26T00:00:00Z",
        }
    )
    fake = _FakeCoreV1(
        phases=["Pending"],  # never reaches terminal
        log_text=log_text,
        agent_exit_code=None,
    )
    result = await run_in_ephemeral_pod(
        run_id=uuid.uuid4(),
        automation_id=uuid.uuid4(),
        image="agent:test",
        grant=FilesystemGrant(has_filesystem=False),
        namespace="ns",
        db=db,
        core_v1=fake,
        terminal_timeout_seconds=0,  # immediate timeout
    )
    assert result.reason == "wait_timeout"
    assert len(result.tracker_warnings) == 1
    assert result.tracker_warnings[0].path == "/var/cache/x"


def test_tracker_warning_to_dict_round_trip() -> None:
    w = TrackerWarning(path="/var/x", ts="2026-04-26T00:00:00Z")
    assert w.to_dict() == {"path": "/var/x", "ts": "2026-04-26T00:00:00Z"}
