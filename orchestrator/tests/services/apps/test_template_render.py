"""Tests for the sandboxed template render worker + supervisor.

Covers:
  * Happy path: valid template + context renders to expected string.
  * RCE attempt: ``{{ output.__class__.__mro__ }}`` is rejected by the
    sandbox / filter allowlist.
  * Output cap: a render that produces > 3.5 KB is truncated with the
    documented marker.
  * Template body cap: a > 4 KB template is rejected.
  * Filter allowlist: ``attr`` / ``map`` / ``selectattr`` are stripped.
  * Worker rotation: the supervisor handles the worker self-exiting at
    its rotation threshold without dropping requests.
  * Worker crash mid-render: a kill mid-call raises RenderError, next
    call respawns successfully.
  * Render timeout: a slow render raises RenderError and kills the
    worker so the next call respawns.
  * Manifest install-time validator: a manifest with a syntax-error
    template is rejected with a structured error list.

The worker is a real subprocess — these tests boot ``python -m
app.services.apps.template_render_worker`` and exercise the full IPC
contract. They use the `orchestrator/` directory as cwd so the module
import resolves.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from app.services.apps import template_render
from app.services.apps.template_render import (
    RenderError,
    TemplateRenderClient,
    shutdown_render_client,
)
from app.services.apps.template_render_worker import (
    OUTPUT_LIMIT_CHARS,
    TEMPLATE_LIMIT_BYTES,
    TRUNCATE_MARKER,
)


# Force the worker subprocess cwd to the orchestrator package root so
# `python -m app.services.apps.template_render_worker` resolves regardless
# of where pytest was invoked from.
_ORCH_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _orchestrator_cwd(monkeypatch):
    """Pin cwd to orchestrator/ so `python -m app.services.apps.*` works."""
    monkeypatch.chdir(str(_ORCH_ROOT))
    # Ensure PYTHONPATH includes orchestrator/ for the spawned worker.
    existing = os.environ.get("PYTHONPATH", "")
    parts = [str(_ORCH_ROOT)] + ([existing] if existing else [])
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(parts))


@pytest.fixture
async def client():
    """Fresh client per test — full lifecycle including subprocess teardown."""
    c = TemplateRenderClient()
    try:
        yield c
    finally:
        await c.close()


@pytest.fixture(autouse=True)
async def _reset_singleton():
    """Make sure tests that touch the module-level singleton don't leak."""
    yield
    await shutdown_render_client()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_render_happy_path(client):
    rendered = await client.render(
        "Hello {{ output.name }}!",
        {"output": {"name": "world"}},
    )
    assert rendered == "Hello world!"


@pytest.mark.asyncio
async def test_render_uses_input_and_output_keys(client):
    rendered = await client.render(
        "{{ input.q }} → {{ output.summary }}",
        {"input": {"q": "hi"}, "output": {"summary": "ok"}},
    )
    assert rendered == "hi → ok"


@pytest.mark.asyncio
async def test_render_strips_unknown_context_keys(client):
    """Even if the caller stuffs extra keys, the worker drops them
    before render so the template can't reach them."""
    rendered = await client.render(
        "{{ secret | default('redacted') }}",
        {"output": {}, "secret": "leaked"},
    )
    # ``secret`` was dropped; ``default`` filter kicks in.
    assert rendered == "redacted"


# ---------------------------------------------------------------------------
# Sandbox / filter allowlist defenses
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_render_blocks_dunder_attribute_walk(client):
    """The classic ``{{ x.__class__.__mro__ }}`` RCE class must fail."""
    with pytest.raises(RenderError):
        await client.render(
            "{{ output.__class__.__mro__ }}",
            {"output": {"a": 1}},
        )


@pytest.mark.asyncio
async def test_render_drops_disallowed_filters(client):
    """``map`` / ``attr`` / ``selectattr`` were removed from the env."""
    # The template references a stripped filter — Jinja parses the syntax
    # but raises at render time when the filter isn't registered.
    with pytest.raises(RenderError):
        await client.render(
            "{{ output | map(attribute='x') | list }}",
            {"output": [{"x": 1}]},
        )


@pytest.mark.asyncio
async def test_render_drops_globals(client):
    """``range``, ``namespace`` etc. are gone — no spinning loops."""
    with pytest.raises(RenderError):
        await client.render(
            "{% for i in range(10) %}{{ i }}{% endfor %}",
            {"output": {}},
        )


# ---------------------------------------------------------------------------
# Caps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_template_body_cap_rejects_oversize(client):
    big_template = "x" * (TEMPLATE_LIMIT_BYTES + 1)
    with pytest.raises(RenderError, match="exceeds"):
        await client.render(big_template, {"output": {}})


@pytest.mark.asyncio
async def test_output_cap_truncates_with_marker(client):
    # Build an output that, once tojson-ed, easily exceeds 3.5 KB.
    big = {"data": "y" * (OUTPUT_LIMIT_CHARS * 2)}
    rendered = await client.render(
        "{{ output | tojson }}",
        {"output": big},
    )
    assert rendered.endswith(TRUNCATE_MARKER)
    assert len(rendered) <= OUTPUT_LIMIT_CHARS


# ---------------------------------------------------------------------------
# Worker lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_respawns_after_rotation(client, monkeypatch):
    """When the supervisor's render count crosses the rotation threshold,
    it drops its handle and the next call respawns. We patch the
    threshold low so the test runs fast."""
    monkeypatch.setattr(template_render, "ROTATION_THRESHOLD", 3)
    # First three renders use one worker.
    for _ in range(3):
        out = await client.render("{{ output.n }}", {"output": {"n": 1}})
        assert out == "1"
    # Capture the pid; the next render should start a fresh worker.
    first_proc_pid = client._proc  # noqa: SLF001
    assert first_proc_pid is None  # supervisor pre-emptively dropped handle
    # 4th render — supervisor spawns a new worker.
    out = await client.render("{{ output.n }}", {"output": {"n": 2}})
    assert out == "2"
    assert client._proc is not None  # noqa: SLF001


@pytest.mark.asyncio
async def test_worker_crash_recovered_on_next_call(client):
    """Killing the worker between calls forces a respawn on the next call.

    The next render either raises (if the supervisor's old handle was
    used and the pipe is closed mid-write) or succeeds against a fresh
    worker (if the supervisor noticed ``returncode != None`` first and
    spawned a new one). Either way, every subsequent render must
    continue to succeed — that's the supervisor's recovery contract.
    """
    # Warm the worker.
    await client.render("ok", {"output": {}})
    proc = client._proc  # noqa: SLF001
    assert proc is not None
    pid_before = proc.pid
    proc.kill()
    await proc.wait()
    # Next render: either succeeds (respawn happened cleanly) or raises
    # (we wrote to a dead pipe). Either is acceptable.
    try:
        await client.render("ok", {"output": {}})
    except RenderError:
        pass
    # Subsequent calls must all succeed against the respawned worker.
    rendered = await client.render(
        "Hello {{ output.name }}",
        {"output": {"name": "world"}},
    )
    assert rendered == "Hello world"
    # And it must be a different process from the one we killed.
    assert client._proc is not None  # noqa: SLF001
    assert client._proc.pid != pid_before  # noqa: SLF001


@pytest.mark.asyncio
async def test_render_timeout_kills_worker(client, monkeypatch):
    """A render that doesn't return within the timeout raises RenderError
    and the worker is killed so the next call respawns."""
    # Patch the worker's stdout.readline to hang forever — easier than
    # crafting a Jinja template that hangs in the sandbox (the sandbox
    # doesn't allow infinite loops in expressions, only in for-blocks
    # over an iterable, and ``range`` is gone).
    await client.render("warmup", {"output": {}})
    proc = client._proc  # noqa: SLF001
    assert proc is not None

    original_readline = proc.stdout.readline

    async def _hang():
        await asyncio.sleep(10)
        return await original_readline()

    proc.stdout.readline = _hang  # type: ignore[assignment]
    with pytest.raises(RenderError, match="timed out"):
        await client.render("ok", {"output": {}}, timeout=0.05)
    # Worker was killed; next call respawns.
    rendered = await client.render(
        "{{ output.x }}",
        {"output": {"x": "fresh"}},
    )
    assert rendered == "fresh"


@pytest.mark.asyncio
async def test_concurrent_renders_serialize(client):
    """Lock prevents interleaved JSON on the worker pipe."""

    async def _do(i: int) -> str:
        return await client.render(
            "n={{ output.n }}",
            {"output": {"n": i}},
        )

    results = await asyncio.gather(*[_do(i) for i in range(20)])
    assert sorted(results) == sorted(f"n={i}" for i in range(20))


# ---------------------------------------------------------------------------
# Install-time manifest validator
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manifest_validator_rejects_bad_template():
    from app.services.apps.manifest_parser import (
        ManifestValidationError,
        ParsedManifest,
        validate_result_templates,
    )

    raw = {
        "manifest_schema_version": "2026-05",
        "actions": [
            {
                "name": "good",
                "result_template": "Hello {{ output.x }}",
            },
            {
                "name": "bad_syntax",
                "result_template": "{{ output.x ",  # never closes
            },
            {
                "name": "rce_attempt",
                "result_template": "{{ output.__class__.__mro__ }}",
            },
        ],
    }
    parsed = ParsedManifest(
        manifest=None, raw=raw, canonical_hash="x", schema_version="2026-05"
    )

    with pytest.raises(ManifestValidationError) as excinfo:
        await validate_result_templates(parsed)

    err = excinfo.value
    failing_actions = {tuple(e["path"][1:2]) for e in err.errors}
    assert ("bad_syntax",) in failing_actions
    assert ("rce_attempt",) in failing_actions
    # The good template did not contribute an error.
    assert ("good",) not in failing_actions


@pytest.mark.asyncio
async def test_manifest_validator_noop_when_no_templates():
    from app.services.apps.manifest_parser import (
        ParsedManifest,
        validate_result_templates,
    )

    parsed = ParsedManifest(
        manifest=None,
        raw={"manifest_schema_version": "2025-01", "actions": []},
        canonical_hash="x",
        schema_version="2025-01",
    )
    # Should not raise, should not spawn a worker.
    await validate_result_templates(parsed)


@pytest.mark.asyncio
async def test_manifest_validator_accepts_valid_templates():
    from app.services.apps.manifest_parser import (
        ParsedManifest,
        validate_result_templates,
    )

    raw = {
        "manifest_schema_version": "2026-05",
        "actions": [
            {"name": "summarize", "result_template": "Summary: {{ output.summary }}"},
            {"name": "tojson_pass", "result_template": "{{ output | tojson }}"},
        ],
    }
    parsed = ParsedManifest(
        manifest=None, raw=raw, canonical_hash="x", schema_version="2026-05"
    )
    # No exception means the dry-render succeeded for every template.
    await validate_result_templates(parsed)
