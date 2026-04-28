"""Long-lived sandboxed Jinja render subprocess.

Reads JSON ``{"template": str, "context": dict}`` from stdin (one JSON
object per line). Writes JSON ``{"ok": bool, "rendered": str?, "error":
str?}`` to stdout (one per line, ``flush=True``).

Exits cleanly on EOF or after :data:`MAX_RENDERS` renders to bound memory
and recycle the Python interpreter (mitigates jinja2 cache growth /
imported-template leaks). Supervisor side
(:mod:`app.services.apps.template_render`) restarts the worker when it
exits.

Run::

    python -m app.services.apps.template_render_worker

Self-contained imports only — no app.* imports allowed beyond stdlib +
jinja2 — so the cold-start cost stays close to "import jinja2.sandbox"
(~20 ms) and we never accidentally pull in SQLAlchemy / FastAPI on the
hot start path.

Sandbox decisions (see plan §"result_template — sandboxed Jinja"):

* :class:`SandboxedEnvironment` (autoescape on) refuses ``__builtins__``
  / dunder attribute access in templates by construction.
* Filter allowlist below strips everything that lets a template walk
  attributes (``attr``, ``map(attribute=...)``, ``selectattr``) — a
  defence-in-depth layer on top of the sandbox.
* Globals are cleared so ``{{ namespace() }}`` / ``{{ range(...) }}``
  cannot be used to spin loops or reflect into Python objects.
* Render context is stripped to ``{"input", "output"}`` only — even if a
  caller passes extra keys they are filtered out before render.
* Template body is capped at 4 KB to prevent runaway parse cost.
* Rendered output is capped at 3.5 KB and truncated with a marker so
  delivery channels (Slack, etc.) never see a 10 MB body.
"""

from __future__ import annotations

import json
import sys

from jinja2.sandbox import SandboxedEnvironment

# Bound the worker lifetime — supervisor will respawn after exit. The
# limit defends against compiled-template cache growth in long-running
# orchestrator processes.
MAX_RENDERS = 1000

# Cap on the raw template body. 4 KB is generous for a delivery template
# and matches the plan's stated ceiling.
TEMPLATE_LIMIT_BYTES = 4096

# Cap on rendered output. 3.5 KB matches the plan; we leave headroom for
# the truncate marker so the net string length stays <= 3.5 KB.
OUTPUT_LIMIT_CHARS = 3500
TRUNCATE_MARKER = "… [truncated, see run history for full output]"

# Allowlist of safe filters. Anything that walks attributes (``attr``,
# ``map``, ``selectattr``, ``rejectattr``, ``groupby``) is dropped — the
# sandbox already refuses ``__class__`` access but stripping the filters
# is a belt-and-braces defence against jinja2 sandbox CVEs.
SAFE_FILTERS = frozenset(
    {
        "tojson",
        "default",
        "length",
        "upper",
        "lower",
        "truncate",
        "replace",
    }
)

# Render context keys the manifest contract documents. Anything else is
# silently dropped before render so a buggy caller can't leak request
# headers / DB rows into a template.
ALLOWED_CONTEXT_KEYS = frozenset({"input", "output"})


def _build_env() -> SandboxedEnvironment:
    env = SandboxedEnvironment(autoescape=True)
    # Strip non-allowlisted filters.
    for filter_name in list(env.filters.keys()):
        if filter_name not in SAFE_FILTERS:
            del env.filters[filter_name]
    # No globals: ``range``, ``namespace``, ``cycler``, ``joiner``, ``dict``
    # all gone. Templates work with the ``input``/``output`` context dict
    # and the allowlisted filters — nothing else.
    env.globals.clear()
    # No tests either — ``defined``/``undefined`` etc. could be a vector
    # for chained-attribute walks in older jinja2 sandbox builds.
    env.tests.clear()
    return env


ENV = _build_env()


def render_one(payload: dict) -> dict:
    """Render a single ``{template, context}`` payload to a result dict.

    Returns ``{"ok": True, "rendered": str}`` on success or
    ``{"ok": False, "error": str}`` on any failure. Never raises — a
    raise here would desync the supervisor's stdin/stdout pipe.
    """
    try:
        template_str = payload.get("template")
        context = payload.get("context", {})

        if not isinstance(template_str, str):
            return {"ok": False, "error": "template must be a string"}
        # Encode-then-len matches the plan's "4 KB" wording (bytes not chars).
        if len(template_str.encode("utf-8")) > TEMPLATE_LIMIT_BYTES:
            return {
                "ok": False,
                "error": f"template exceeds {TEMPLATE_LIMIT_BYTES}-byte limit",
            }
        if not isinstance(context, dict):
            return {"ok": False, "error": "context must be a dict"}

        # Restrict context to the documented keys.
        safe_context = {
            k: v for k, v in context.items() if k in ALLOWED_CONTEXT_KEYS
        }

        template = ENV.from_string(template_str)
        rendered = template.render(**safe_context)

        if len(rendered) > OUTPUT_LIMIT_CHARS:
            head_len = OUTPUT_LIMIT_CHARS - len(TRUNCATE_MARKER)
            if head_len < 0:
                head_len = 0
            rendered = rendered[:head_len] + TRUNCATE_MARKER

        return {"ok": True, "rendered": rendered}
    except Exception as exc:  # noqa: BLE001 — template errors must not crash worker
        # Truncate the message so a giant traceback can't blow the IPC line.
        message = str(exc)
        if len(message) > 200:
            message = message[:200] + "…"
        return {"ok": False, "error": f"{type(exc).__name__}: {message}"}


def main() -> None:
    rendered_count = 0
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            sys.stdout.write(
                json.dumps({"ok": False, "error": f"malformed JSON: {exc}"}) + "\n"
            )
            sys.stdout.flush()
            continue
        if not isinstance(payload, dict):
            sys.stdout.write(
                json.dumps({"ok": False, "error": "payload must be a JSON object"})
                + "\n"
            )
            sys.stdout.flush()
            continue
        result = render_one(payload)
        sys.stdout.write(json.dumps(result) + "\n")
        sys.stdout.flush()
        rendered_count += 1
        if rendered_count >= MAX_RENDERS:
            # Clean exit — supervisor's next call will spawn a fresh worker.
            return


if __name__ == "__main__":
    main()
