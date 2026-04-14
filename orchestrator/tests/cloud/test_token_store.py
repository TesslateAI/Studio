"""Token store: env override, file round-trip, clear."""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest


@pytest.fixture
def studio_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("TESSLATE_STUDIO_HOME", str(tmp_path))
    monkeypatch.delenv("TESSLATE_CLOUD_TOKEN", raising=False)
    (tmp_path / "cache").mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_get_returns_none_when_unpaired(studio_home: Path) -> None:
    from app.services import token_store

    assert token_store.get_cloud_token() is None
    assert token_store.is_paired() is False


def test_set_then_get_roundtrip(studio_home: Path) -> None:
    from app.services import token_store

    token_store.set_cloud_token("tsk_abcd1234")
    assert token_store.get_cloud_token() == "tsk_abcd1234"
    assert token_store.is_paired() is True

    path = studio_home / "cache" / "cloud_token.json"
    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8")) == {"token": "tsk_abcd1234"}

    if sys.platform != "win32":
        mode = stat.S_IMODE(os.stat(path).st_mode)
        assert mode == 0o600


def test_env_var_overrides_file(studio_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import token_store

    token_store.set_cloud_token("tsk_from_file")
    monkeypatch.setenv("TESSLATE_CLOUD_TOKEN", "tsk_from_env")
    assert token_store.get_cloud_token() == "tsk_from_env"


def test_clear_removes_file(studio_home: Path) -> None:
    from app.services import token_store

    token_store.set_cloud_token("tsk_xyz")
    token_store.clear_cloud_token()
    assert token_store.get_cloud_token() is None
    # Idempotent
    token_store.clear_cloud_token()


def test_set_rejects_empty(studio_home: Path) -> None:
    from app.services import token_store

    with pytest.raises(ValueError):
        token_store.set_cloud_token("")
