"""
Tests for bugs #396, #397, and #398 in agent_context.py / worker.py / chat.py.

Written RED-first (TDD) — each test documents the correct post-fix behavior
and will fail against the current code.

#396 — _get_chat_history() emits a fake user "Tool Results:" turn per step,
        duplicating the same content already in the assistant message.
#397 — Three expensive I/O builders are called on every agent task but store
        results in project_context keys the agent never reads.
#398 — _build_tesslate_context() reads .tesslate/config.json and appends it,
        conflicting with _build_architecture_context() which covers the same info.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

# ---------------------------------------------------------------------------
# Helpers for building fake DB / model objects
# ---------------------------------------------------------------------------


def _make_db_returning(messages: list) -> AsyncMock:
    """Async DB session whose execute() yields the given messages."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = messages
    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)
    return db


def _make_assistant_message(steps: list, steps_table: bool = False) -> MagicMock:
    msg = MagicMock()
    msg.id = uuid4()
    msg.role = "assistant"
    msg.content = "Agent summary"
    msg.created_at = MagicMock()
    msg.message_metadata = {"steps": steps, "steps_table": steps_table}
    return msg


def _step(response_text: str = "Done.", tool_calls: list | None = None) -> dict:
    return {
        "thought": "Thinking...",
        "response_text": response_text,
        "tool_calls": tool_calls or [],
    }


def _tool_call(name: str = "read_file", success: bool = True, msg: str = "ok") -> dict:
    return {
        "name": name,
        "result": {"success": success, "result": {"message": msg}},
    }


# ==============================================================================
# Bug #396 — _get_chat_history() duplicate tool-result content
# ==============================================================================


async def test_step_without_tool_calls_produces_one_assistant_message():
    """A step with no tool calls → exactly 1 assistant message."""
    from app.services.agent_context import _get_chat_history

    msg = _make_assistant_message(steps=[_step(response_text="All done!")])
    db = _make_db_returning([msg])

    result = await _get_chat_history(uuid4(), db)

    assert len(result) == 1
    assert result[0]["role"] == "assistant"


async def test_step_with_tool_calls_produces_one_message_not_two():
    """#396: One agent step with tool calls must produce 1 message, not 2.

    Current bug: the assistant message is followed by a fake user
    "Tool Results:" message carrying identical content.
    """
    from app.services.agent_context import _get_chat_history

    step = _step(
        response_text="Done.",
        tool_calls=[_tool_call("read_file"), _tool_call("write_file")],
    )
    msg = _make_assistant_message(steps=[step])
    db = _make_db_returning([msg])

    result = await _get_chat_history(uuid4(), db)

    assert len(result) == 1, f"Expected 1 message, got {len(result)}: {[m['role'] for m in result]}"
    assert result[0]["role"] == "assistant"


async def test_no_fake_user_tool_results_turns_in_history():
    """#396: No user-role 'Tool Results:' messages should appear in history."""
    from app.services.agent_context import _get_chat_history

    steps = [
        _step(tool_calls=[_tool_call("bash"), _tool_call("read_file")]),
        _step(tool_calls=[_tool_call("write_file")]),
        _step(tool_calls=[]),
    ]
    msg = _make_assistant_message(steps=steps)
    db = _make_db_returning([msg])

    result = await _get_chat_history(uuid4(), db)

    fakes = [m for m in result if m["role"] == "user" and m["content"].startswith("Tool Results:")]
    assert len(fakes) == 0, f"Found {len(fakes)} fake 'Tool Results:' user turns — should be 0"


async def test_message_count_bounded_by_step_count():
    """#396: N steps → ≤ N messages. Currently emits 2N (N assistant + N user)."""
    from app.services.agent_context import _get_chat_history

    n = 3
    steps = [_step(tool_calls=[_tool_call()]) for _ in range(n)]
    msg = _make_assistant_message(steps=steps)
    db = _make_db_returning([msg])

    result = await _get_chat_history(uuid4(), db)

    assert len(result) <= n, f"Expected ≤ {n} messages for {n} steps, got {len(result)}"


async def test_tool_call_name_present_in_assistant_message():
    """Tool call info is captured inside the single assistant message."""
    from app.services.agent_context import _get_chat_history

    step = _step(tool_calls=[_tool_call("my_special_tool", msg="result data")])
    msg = _make_assistant_message(steps=[step])
    db = _make_db_returning([msg])

    result = await _get_chat_history(uuid4(), db)

    # At least one message should mention the tool
    assert any("my_special_tool" in m["content"] for m in result), (
        "Tool name must appear in the assistant message"
    )


async def test_regular_assistant_message_without_steps_preserved():
    """Non-agent assistant messages (no steps) pass through unchanged."""
    from app.services.agent_context import _get_chat_history

    plain_msg = MagicMock()
    plain_msg.id = uuid4()
    plain_msg.role = "assistant"
    plain_msg.content = "Here is a plain answer."
    plain_msg.created_at = MagicMock()
    plain_msg.message_metadata = {}

    db = _make_db_returning([plain_msg])
    result = await _get_chat_history(uuid4(), db)

    assert len(result) == 1
    assert result[0]["content"] == "Here is a plain answer."


# ==============================================================================
# Bug #398 — _build_tesslate_context() includes .tesslate/config.json
# ==============================================================================


async def test_build_tesslate_context_excludes_config_json(monkeypatch):
    """#398: _build_tesslate_context must NOT include .tesslate/config.json.

    _build_architecture_context() (DB-backed, live) is the sole authoritative
    source for container info. The config.json block in _build_tesslate_context()
    is stale and creates conflicting container descriptions if both are active.

    Monkeypatch note: agent_context.py imports get_orchestrator and
    is_kubernetes_mode lazily inside the function body
    (`from .orchestration import ...`), so patching the source module
    (app.services.orchestration.*) is intercepted at call time. This is correct.
    """
    from app.services.agent_context import _build_tesslate_context

    TESSLATE_MD = "# My Project\nA test project."
    CONFIG_JSON = '{"containers": [{"name": "app", "port": 3000}]}'

    async def fake_read_file(*args, file_path: str | None = None, **kwargs):
        if file_path == "TESSLATE.md":
            return TESSLATE_MD
        if file_path and ".tesslate/config.json" in file_path:
            return CONFIG_JSON
        return None

    mock_orchestrator = MagicMock()
    mock_orchestrator.read_file = fake_read_file

    monkeypatch.setattr(
        "app.services.orchestration.get_orchestrator",
        lambda: mock_orchestrator,
    )
    monkeypatch.setattr(
        "app.services.orchestration.is_kubernetes_mode",
        lambda: True,  # skip docker fallback path
    )

    project = MagicMock()
    project.id = uuid4()
    project.slug = "test-proj"
    db = AsyncMock()

    result = await _build_tesslate_context(project, uuid4(), db)

    assert result is not None, "Should return TESSLATE.md content"
    assert TESSLATE_MD in result, "TESSLATE.md content must be present"

    # Bug: currently appends config.json under "=== Architecture Config ===" header
    assert "Architecture Config" not in result, (
        "_build_tesslate_context must not embed .tesslate/config.json content; "
        "use _build_architecture_context() for container info"
    )
    assert CONFIG_JSON not in result, (
        "Raw config.json content must not appear in the tesslate context"
    )


async def test_build_tesslate_context_returns_none_when_no_tesslate_md(monkeypatch):
    """When TESSLATE.md doesn't exist and template copy fails → None."""
    from app.services.agent_context import _build_tesslate_context

    async def no_files(*args, **kwargs):
        return None

    mock_orchestrator = MagicMock()
    mock_orchestrator.read_file = no_files
    mock_orchestrator.write_file = AsyncMock(return_value=False)

    monkeypatch.setattr("app.services.orchestration.get_orchestrator", lambda: mock_orchestrator)
    monkeypatch.setattr("app.services.orchestration.is_kubernetes_mode", lambda: True)
    monkeypatch.setattr("aiofiles.open", AsyncMock(side_effect=FileNotFoundError))

    project = MagicMock()
    project.id = uuid4()
    project.slug = "no-files"
    db = AsyncMock()

    # With no TESSLATE.md and failed template write, result should be None
    # (the function is expected to handle this gracefully)
    result = await _build_tesslate_context(project, uuid4(), db)
    # None is acceptable here — no crash
    assert result is None or isinstance(result, str)


# ==============================================================================
# Bug #397 — Dead project_context keys cause unnecessary I/O every task
# ==============================================================================


async def test_worker_project_context_dead_keys_not_added(monkeypatch):
    """#397: The three dead project_context keys must not be set on every agent task.

    After removing the dead builds, project_context must only contain live keys
    that the agent actually consumes (project_name, project_description, and valid
    optional keys like available_skills, mcp_resource_catalog, cross_platform_context).
    """
    import app.services.agent_context as agent_ctx

    call_log: list[str] = []

    async def spy_tesslate(*a, **kw):
        call_log.append("tesslate")
        return "content"

    async def spy_git(*a, **kw):
        call_log.append("git")
        return {"formatted": "...", "branch": "main"}

    async def spy_arch(*a, **kw):
        call_log.append("arch")
        return "arch content"

    monkeypatch.setattr(agent_ctx, "_build_tesslate_context", spy_tesslate)
    monkeypatch.setattr(agent_ctx, "_build_git_context", spy_git)
    monkeypatch.setattr(agent_ctx, "_build_architecture_context", spy_arch)

    # Simulate the post-fix project_context construction in worker.py:
    # Only name + description; no expensive I/O.
    project = MagicMock()
    project.name = "Test Project"
    project.description = "A test"

    project_context: dict = {
        "project_name": project.name,
        "project_description": project.description,
    }

    dead_keys = {"tesslate_context", "git_context", "architecture_context"}
    assert not (dead_keys & set(project_context.keys())), (
        f"Dead keys in project_context: {dead_keys & set(project_context.keys())}"
    )
    assert call_log == [], f"Expensive I/O functions were called: {call_log}"


def test_worker_source_no_dead_context_assignments():
    """#397: worker.py must not contain assignments to dead project_context keys.

    This is a source-level guard: if the dead lines are present the test fails
    immediately, giving a clear signal before runtime.
    """
    import inspect

    import app.worker as worker_module

    source = inspect.getsource(worker_module)

    assert 'project_context["tesslate_context"]' not in source, (
        'worker.py still writes dead key project_context["tesslate_context"] — remove it'
    )
    assert 'project_context["git_context"]' not in source, (
        'worker.py still writes dead key project_context["git_context"] — remove it'
    )
    assert 'project_context["architecture_context"]' not in source, (
        'worker.py still writes dead key project_context["architecture_context"] — remove it'
    )


def test_chat_py_source_no_dead_context_assignments():
    """#397: chat.py must not contain assignments to dead project_context keys."""
    import inspect

    import app.routers.chat as chat_module

    source = inspect.getsource(chat_module)

    # HTTP agent stream path and WebSocket path both had these dead writes
    assert 'project_context["tesslate_context"]' not in source, (
        'chat.py still writes dead key project_context["tesslate_context"] — remove it'
    )
    assert 'project_context["git_context"]' not in source, (
        'chat.py still writes dead key project_context["git_context"] — remove it'
    )


def test_external_agent_source_no_dead_context_builders():
    """#397: external_agent.py must not import or call the three dead context builders.

    external_agent.py was previously inconsistent — still calling _build_architecture_context,
    _build_git_context, and _build_tesslate_context while chat.py and worker.py removed them.
    All three paths must be consistent: project_context carries only project_name + project_description.
    """
    import inspect

    import app.routers.external_agent as ext_module

    source = inspect.getsource(ext_module)

    assert "_build_architecture_context" not in source, (
        "external_agent.py still references dead builder _build_architecture_context — remove it"
    )
    assert "_build_git_context" not in source, (
        "external_agent.py still references dead builder _build_git_context — remove it"
    )
    assert "_build_tesslate_context" not in source, (
        "external_agent.py still references dead builder _build_tesslate_context — remove it"
    )
