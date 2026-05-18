"""Tests for the compute-profile runner registry (Phase B, issue #471).

Pure unit tests; no DB. Covers:

* ``select_runner`` returns the right class for each profile.
* ``connector_only`` blanks ``project_id`` / ``container_id`` and
  preserves the rest of the payload.
* ``persistent_workspace`` is a pass-through that just stamps the
  profile.
* ``ephemeral_workspace`` falls back to ``persistent_workspace`` since
  the throwaway-PVC runner is a Phase B follow-up.
"""

from __future__ import annotations


def _make_payload(**overrides):
    from app.services.agent_task import AgentTaskPayload

    base = {
        "task_id": "t-1",
        "user_id": "u-1",
        "chat_id": "c-1",
        "message": "hello",
        "project_id": "proj-uuid",
        "project_slug": "my-project",
        "container_id": "ctr-uuid",
        "container_name": "dev-1",
        "container_directory": "/workspace",
    }
    base.update(overrides)
    return AgentTaskPayload(**base)


def test_select_runner_returns_connector_only_for_connector_only():
    import app.services.workflows.runners.connector_only  # noqa: F401
    from app.services.workflows.runners import select_runner

    runner = select_runner("connector_only")
    assert runner.profile == "connector_only"


def test_select_runner_returns_persistent_for_default():
    import app.services.workflows.runners.connector_only  # noqa: F401
    from app.services.workflows.runners import select_runner

    runner = select_runner(None)
    assert runner.profile == "persistent_workspace"


def test_select_runner_falls_back_for_ephemeral():
    import app.services.workflows.runners.connector_only  # noqa: F401
    from app.services.workflows.runners import select_runner

    runner = select_runner("ephemeral_workspace")
    # Phase B follow-up: ephemeral falls back to persistent.
    assert runner.profile == "persistent_workspace"


def test_connector_only_runner_blanks_workspace_fields():
    import app.services.workflows.runners.connector_only  # noqa: F401
    from app.services.workflows.runners import select_runner

    payload = _make_payload(message="say hi to slack")
    runner = select_runner("connector_only")
    shaped = runner.shape_payload(payload)

    assert shaped.project_id == ""
    assert shaped.project_slug == ""
    assert shaped.container_id is None
    assert shaped.container_name is None
    assert shaped.container_directory is None
    assert shaped.compute_profile == "connector_only"
    # Non-workspace fields preserved.
    assert shaped.task_id == "t-1"
    assert shaped.user_id == "u-1"
    assert shaped.chat_id == "c-1"
    assert shaped.message == "say hi to slack"


def test_persistent_workspace_runner_preserves_payload():
    import app.services.workflows.runners.connector_only  # noqa: F401
    from app.services.workflows.runners import select_runner

    payload = _make_payload()
    runner = select_runner("persistent_workspace")
    shaped = runner.shape_payload(payload)

    assert shaped.project_id == "proj-uuid"
    assert shaped.container_id == "ctr-uuid"
    assert shaped.compute_profile == "persistent_workspace"
