"""Desktop sidecar entrypoint.

Spawned by the Tauri host (``desktop/src-tauri/src/sidecar.rs``). Contract:

1. Resolve ``$OPENSAIL_HOME`` and materialize its directory tree.
2. Set ``DEPLOYMENT_MODE=desktop`` + ``DATABASE_URL=sqlite+aiosqlite://``
   pointing at ``$OPENSAIL_HOME/opensail.db`` (override-able via env).
3. Pick an ephemeral free TCP port on ``127.0.0.1``.
4. Mint a per-launch bearer token (32 random bytes, urlsafe-base64).
5. Print ``TESSLATE_READY {port} {bearer}`` to stdout and flush — the Tauri
   supervisor scans for this prefix.
6. Hand off to ``uvicorn app.main:app`` bound to that port.

The bearer is exposed to FastAPI via ``TESSLATE_DESKTOP_BEARER`` so
middleware can require it on every request the loopback listener serves.
"""

from __future__ import annotations

import os
import secrets
import socket
import sys
from pathlib import Path

READY_LINE_PREFIX = "TESSLATE_READY"


def format_ready_line(port: int, bearer: str) -> str:
    """Format the stdout handshake line read by the Tauri supervisor."""
    return f"{READY_LINE_PREFIX} {port} {bearer}"


def _pick_free_port(host: str = "127.0.0.1") -> int:
    """Reserve an ephemeral port from the OS and return it.

    The socket is closed immediately; uvicorn re-binds via SO_REUSEADDR.
    A tiny race window exists but is harmless in single-process desktop mode.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def _mint_bearer() -> str:
    """32 random bytes, urlsafe-base64, no padding — ~43 chars."""
    return secrets.token_urlsafe(32)


def _load_dot_env(opensail_home: Path) -> None:
    """Load ``$OPENSAIL_HOME/.env`` into the process environment.

    Only sets variables that are not already present so that explicit env
    overrides (shell exports, CI) take priority.  Uses a minimal parser to
    avoid a python-dotenv dependency — supports ``KEY=value`` and
    ``KEY="value"`` lines; skips blank lines and ``#`` comments.
    """
    dot_env = opensail_home / ".env"
    if not dot_env.is_file():
        return
    try:
        with dot_env.open(encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
    except OSError:
        pass  # Best-effort; missing/unreadable .env is not fatal.


def _ensure_secret_key(opensail_home: Path) -> str:
    """Return a stable per-installation SECRET_KEY, generating one on first boot.

    The key is persisted at ``$OPENSAIL_HOME/.secret_key`` (0600) so
    that JWTs survive sidecar restarts.  If ``SECRET_KEY`` is already set in
    the environment (or loaded from ``.env``), that value is used as-is.
    """
    existing = os.environ.get("SECRET_KEY", "").strip()
    if len(existing) >= 32:
        return existing

    key_file = opensail_home / ".secret_key"
    if key_file.is_file():
        try:
            key = key_file.read_text(encoding="utf-8").strip()
            if len(key) >= 32:
                return key
        except OSError:
            pass

    # First boot — generate and persist.
    key = secrets.token_urlsafe(48)
    try:
        key_file.write_text(key, encoding="utf-8")
        key_file.chmod(0o600)
    except OSError:
        pass  # Best-effort; if the write fails we still use the in-memory key.
    return key


def _configure_environment(opensail_home: Path) -> None:
    """Set the env vars FastAPI / SQLAlchemy read at import time."""
    # User-supplied keys (OPENAI_API_KEY etc.) land first so the rest of the
    # defaults below don't accidentally shadow them.
    _load_dot_env(opensail_home)
    os.environ.setdefault("DEPLOYMENT_MODE", "desktop")
    os.environ.setdefault("DEPLOYMENT_ENV", "desktop")
    os.environ.setdefault("OPENSAIL_HOME", str(opensail_home))
    os.environ.setdefault(
        "DATABASE_URL", f"sqlite+aiosqlite:///{opensail_home / 'opensail.db'}"
    )
    # SQLite + desktop mode must not try to talk to Redis.
    os.environ.setdefault("REDIS_URL", "")
    # Ensure a stable JWT signing key (min 32 bytes required by jose/SHA-256).
    secret = _ensure_secret_key(opensail_home)
    os.environ.setdefault("SECRET_KEY", secret)


def _alembic_dir() -> Path:
    """Resolve the bundled alembic/ directory.

    PyInstaller --onedir places `datas` next to the executable; in the
    source checkout it lives at orchestrator/alembic/. The
    ``_MEIPASS`` attribute on sys identifies the runtime extract dir.
    """
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "alembic"
    return Path(__file__).resolve().parents[2] / "orchestrator" / "alembic"


def _run_migrations_in_process() -> None:
    """Drive alembic upgrade head without shelling out."""
    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(_alembic_dir()))
    cfg.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
    command.upgrade(cfg, "head")


def main() -> int:
    # Lazy imports — the env vars above land before SQLAlchemy / config cache.
    from app.services.desktop_paths import ensure_opensail_home

    opensail_home = ensure_opensail_home(os.environ.get("OPENSAIL_HOME"))
    _configure_environment(opensail_home)

    host = os.environ.get("TESSLATE_DESKTOP_HOST", "127.0.0.1")
    env_port = os.environ.get("TESSLATE_DESKTOP_PORT")
    if env_port:
        port = int(env_port)
        # Fail fast with a clear message if the pinned port is taken —
        # uvicorn would crash deep inside startup with a muddled traceback.
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((host, port))
        except OSError as exc:
            sys.stderr.write(
                f"sidecar: cannot bind {host}:{port} ({exc}); "
                f"another sidecar is probably already running. "
                f"`fuser -k {port}/tcp` (Linux) or kill it, then retry.\n"
            )
            return 1
    else:
        port = _pick_free_port(host)
    bearer = os.environ.get("TESSLATE_DESKTOP_BEARER") or _mint_bearer()
    os.environ["TESSLATE_DESKTOP_BEARER"] = bearer

    # Run alembic migrations BEFORE uvicorn starts. The orchestrator's
    # in-process retry loop shells out to the `alembic` CLI which doesn't
    # exist in a frozen bundle; we run them programmatically here instead.
    _run_migrations_in_process()

    sys.stdout.write(format_ready_line(port, bearer) + "\n")
    sys.stdout.flush()

    import uvicorn

    # The orchestrator's startup retry-loop shells out to the `alembic` CLI
    # which doesn't exist in a frozen bundle. We've already run upgrade head
    # above, so neuter the runner before app.main imports.
    import app.main as _app_main_module  # noqa: F401  (import side effects below)
    _app_main_module.run_alembic_migrations = lambda: None  # type: ignore[assignment]
    # Frozen bundles have no module path to resolve "app.main:app" — import
    # the FastAPI app instance directly and hand it to uvicorn.
    from app.main import app as fastapi_app

    uvicorn.run(
        fastapi_app,
        host=host,
        port=port,
        log_config=None,
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
