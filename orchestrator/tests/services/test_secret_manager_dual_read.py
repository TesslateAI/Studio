"""Unit tests for the secret_manager_env dual-read path.

``container_env`` must:
  * return decrypted ``encrypted_secrets`` values
  * fall back to a best-effort base64 decode of legacy ``environment_vars``
    entries and emit a ``secret_backfill_needed`` structured warning
  * prefer ``encrypted_secrets`` when the same key appears in both
  * pass through plaintext non-secret values verbatim
"""
from __future__ import annotations

import base64
import json
import logging
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.deployment_encryption import get_deployment_encryption_service
from app.services.secret_manager_env import container_env


def _container(
    *,
    environment_vars: dict | None = None,
    encrypted_secrets: dict | None = None,
) -> SimpleNamespace:
    """A minimal container shim — container_env only reads a few attrs."""
    return SimpleNamespace(
        id=uuid4(),
        project_id=uuid4(),
        environment_vars=environment_vars,
        encrypted_secrets=encrypted_secrets,
    )


def test_encrypted_secrets_only_returns_decrypted_plaintext() -> None:
    enc = get_deployment_encryption_service()
    cipher = enc.encrypt("super-secret")
    c = _container(environment_vars=None, encrypted_secrets={"API_KEY": cipher})

    resolved = container_env(c)
    assert resolved == {"API_KEY": "super-secret"}


def test_encrypted_wins_over_environment_vars_for_same_key() -> None:
    enc = get_deployment_encryption_service()
    cipher = enc.encrypt("from-encrypted")
    c = _container(
        environment_vars={"API_KEY": "from-plain"},
        encrypted_secrets={"API_KEY": cipher},
    )

    resolved = container_env(c)
    assert resolved["API_KEY"] == "from-encrypted"


def test_plaintext_non_secret_passes_through() -> None:
    c = _container(
        environment_vars={"PORT": "3000", "NAME": "my-app"},
        encrypted_secrets=None,
    )
    resolved = container_env(c)
    assert resolved == {"PORT": "3000", "NAME": "my-app"}


def test_legacy_base64_environment_var_is_decoded_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Legacy base64 secret shape — only environment_vars has it, no
    # encrypted_secrets yet.
    legacy_value = base64.b64encode(b"legacy-secret-abcdef").decode("utf-8")
    c = _container(environment_vars={"LEGACY_KEY": legacy_value}, encrypted_secrets=None)

    with caplog.at_level(logging.WARNING, logger="app.services.secret_manager_env"):
        resolved = container_env(c)

    assert resolved["LEGACY_KEY"] == "legacy-secret-abcdef"

    # Warning emitted as a structured JSON log for ops
    warning_logs = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any(
        "secret_backfill_needed" in r.getMessage() for r in warning_logs
    ), f"Expected structured backfill warning, got: {[r.getMessage() for r in warning_logs]}"

    # The warning is JSON-shaped with the expected key
    for r in warning_logs:
        try:
            parsed = json.loads(r.getMessage())
        except Exception:
            continue
        if parsed.get("event") == "secret_backfill_needed":
            assert parsed.get("key") == "LEGACY_KEY"
            break
    else:
        pytest.fail("no structured secret_backfill_needed JSON log found")


def test_empty_environment_vars_returns_empty_map() -> None:
    c = _container(environment_vars=None, encrypted_secrets=None)
    assert container_env(c) == {}
