"""Sidecar handshake helpers — port + bearer + ready-line shape."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_ENTRY = _REPO / "desktop" / "sidecar" / "entrypoint.py"


def _load():
    spec = importlib.util.spec_from_file_location("sidecar_entrypoint", _ENTRY)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_format_ready_line_shape():
    m = _load()
    line = m.format_ready_line(43210, "tok-abc")
    assert line == "TESSLATE_READY 43210 tok-abc"


def test_pick_free_port_returns_valid_loopback_port():
    m = _load()
    port = m._pick_free_port()
    assert 1 <= port <= 65535


def test_mint_bearer_is_long_random_token():
    m = _load()
    a, b = m._mint_bearer(), m._mint_bearer()
    assert len(a) > 30 and a != b


def test_configure_environment_sets_desktop_defaults(tmp_path, monkeypatch):
    m = _load()
    monkeypatch.delenv("DEPLOYMENT_MODE", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    m._configure_environment(tmp_path)
    import os

    assert os.environ["DEPLOYMENT_MODE"] == "desktop"
    assert os.environ["DATABASE_URL"].startswith("sqlite+aiosqlite:///")
    assert os.environ["REDIS_URL"] == ""
