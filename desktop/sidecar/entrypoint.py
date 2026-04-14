"""Desktop sidecar entrypoint.

Responsibilities:
  1. Resolve `$TESSLATE_STUDIO_HOME` via `app.services.desktop_paths`.
  2. Set `DEPLOYMENT_MODE=desktop` and `DATABASE_URL=sqlite+aiosqlite://.../studio.db`.
  3. Bind `127.0.0.1` on an ephemeral port.
  4. Mint a per-launch bearer token.
  5. Print `TESSLATE_READY {port} {bearer}` to stdout for the Tauri supervisor.
  6. Hand off to `uvicorn app.main:app`.

The current module documents the ready-line contract so
`src-tauri/src/sidecar.rs` has something to match against.
"""

from __future__ import annotations

READY_LINE_PREFIX = "TESSLATE_READY"


def format_ready_line(port: int, bearer: str) -> str:
    """Format the stdout handshake line read by the Tauri supervisor."""
    return f"{READY_LINE_PREFIX} {port} {bearer}"


if __name__ == "__main__":
    raise SystemExit("desktop sidecar entrypoint is not yet wired to uvicorn")
