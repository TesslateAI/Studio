"""
Channel factory and credential encryption utilities.
"""

import base64
import json
import logging
import secrets
from typing import Any

from cryptography.fernet import Fernet

from ...config import get_settings
from .base import AbstractChannel

logger = logging.getLogger(__name__)

# Channel type → implementation class mapping
# Populated by _register_channels() on first access
CHANNEL_MAP: dict[str, type[AbstractChannel]] = {}

_registered = False


def _register_channels() -> None:
    """Lazily register all channel implementations."""
    global _registered
    if _registered:
        return
    _registered = True

    from .discord_bot import DiscordBotChannel
    from .slack import SlackChannel
    from .telegram import TelegramChannel
    from .whatsapp import WhatsAppChannel

    CHANNEL_MAP["telegram"] = TelegramChannel
    CHANNEL_MAP["slack"] = SlackChannel
    CHANNEL_MAP["discord"] = DiscordBotChannel
    CHANNEL_MAP["whatsapp"] = WhatsAppChannel

    logger.info(f"Registered {len(CHANNEL_MAP)} channel types: {list(CHANNEL_MAP.keys())}")


def get_channel(channel_type: str, credentials: dict[str, Any]) -> AbstractChannel:
    """
    Factory function: create a channel instance by type.

    Args:
        channel_type: One of 'telegram', 'slack', 'discord', 'whatsapp'
        credentials: Decrypted credential dict for the channel

    Returns:
        Instantiated channel

    Raises:
        ValueError: If channel_type is unknown
    """
    _register_channels()

    ChannelClass = CHANNEL_MAP.get(channel_type)
    if not ChannelClass:
        available = ", ".join(CHANNEL_MAP.keys())
        raise ValueError(f"Unknown channel type '{channel_type}'. Available: {available}")

    return ChannelClass(credentials)


def _get_fernet() -> Fernet:
    """Get Fernet instance using the channel encryption key."""
    settings = get_settings()
    key = settings.get_channel_encryption_key
    if not key:
        raise ValueError(
            "No encryption key configured. Set CHANNEL_ENCRYPTION_KEY, "
            "DEPLOYMENT_ENCRYPTION_KEY, or SECRET_KEY."
        )
    # If key is not base64, derive a Fernet-compatible key
    try:
        # Try using as-is (already a valid Fernet key)
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception:
        # Derive a Fernet key from the secret by padding/hashing
        import hashlib
        derived = base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest())
        return Fernet(derived)


def encrypt_credentials(credentials: dict[str, Any]) -> str:
    """Encrypt a credentials dict to a Fernet-encrypted string."""
    f = _get_fernet()
    plaintext = json.dumps(credentials).encode("utf-8")
    return f.encrypt(plaintext).decode("utf-8")


def decrypt_credentials(encrypted: str) -> dict[str, Any]:
    """Decrypt a Fernet-encrypted credentials string to a dict."""
    f = _get_fernet()
    plaintext = f.decrypt(encrypted.encode("utf-8"))
    return json.loads(plaintext.decode("utf-8"))


def generate_webhook_secret() -> str:
    """Generate a cryptographically secure webhook secret."""
    return secrets.token_hex(32)
