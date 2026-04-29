"""
Detached ed25519 signatures over bundle SHA-256 digests.

Each bundle gets a base64-encoded signature in its envelope. Orchestrators that
flip `bundles.signed_manifests` ON verify the signature against the hub's
published key set in `/v1/manifest.attestation_keys`.

Signing key:
- Loaded from `ATTESTATION_KEY_PATH` (PEM-encoded ed25519 private key).
- Generated and persisted on first boot if the path doesn't exist.
- Public half is exported via `Attestor.public_key_pem()`.

The signing target is the bundle's hex SHA-256 string encoded as ASCII bytes —
keeping the message a stable, easy-to-rebuild artefact.
"""

from __future__ import annotations

import base64
import logging
import os
import threading
from pathlib import Path
from typing import NamedTuple

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from ..config import Settings, get_settings

logger = logging.getLogger(__name__)


class Attestation(NamedTuple):
    signature: str
    key_id: str
    algorithm: str


class Attestor:
    """Singleton-like wrapper around the hub's signing key."""

    _instance: "Attestor | None" = None
    _lock = threading.Lock()

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._private_key = self._load_or_create_key(Path(settings.attestation_key_path))

    # ---------- key loading ----------

    @staticmethod
    def _load_or_create_key(path: Path) -> Ed25519PrivateKey:
        if path.exists():
            try:
                pem = path.read_bytes()
                key = serialization.load_pem_private_key(pem, password=None)
                if not isinstance(key, Ed25519PrivateKey):
                    raise TypeError("attestation key must be ed25519")
                return key
            except Exception as exc:  # noqa: BLE001 - malformed keys regenerate
                logger.warning("attestation key at %s is unreadable (%s); regenerating", path, exc)

        key = Ed25519PrivateKey.generate()
        path.parent.mkdir(parents=True, exist_ok=True)
        pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(pem)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        logger.info("generated new attestation key at %s", path)
        return key

    # ---------- signing ----------

    def _signing_message(self, sha256_hex: str) -> bytes:
        return sha256_hex.lower().encode("ascii")

    def sign_sha256(self, sha256_hex: str) -> Attestation:
        message = self._signing_message(sha256_hex)
        signature = self._private_key.sign(message)
        return Attestation(
            signature=base64.b64encode(signature).decode("ascii"),
            key_id=self._settings.attestation_key_id,
            algorithm="ed25519",
        )

    def verify_sha256(self, sha256_hex: str, signature_b64: str) -> bool:
        message = self._signing_message(sha256_hex)
        try:
            sig = base64.b64decode(signature_b64.encode("ascii"))
        except Exception:
            return False
        try:
            self._private_key.public_key().verify(sig, message)
        except Exception:
            return False
        return True

    # ---------- key export ----------

    def public_key(self) -> Ed25519PublicKey:
        return self._private_key.public_key()

    def public_key_pem(self) -> str:
        return self.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")

    def public_key_id(self) -> str:
        return self._settings.attestation_key_id


def get_attestor(settings: Settings | None = None) -> Attestor:
    """Process-singleton accessor."""
    settings = settings or get_settings()
    if Attestor._instance is None:
        with Attestor._lock:
            if Attestor._instance is None:
                Attestor._instance = Attestor(settings)
    return Attestor._instance


def reset_attestor_cache() -> None:
    Attestor._instance = None
