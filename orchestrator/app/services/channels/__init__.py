"""
Messaging Channel System

Provides a unified interface for sending/receiving messages across
Telegram, Slack, Discord, and WhatsApp platforms.
"""

from .base import AbstractChannel, InboundMessage
from .registry import get_channel, encrypt_credentials, decrypt_credentials, CHANNEL_MAP

__all__ = [
    "AbstractChannel",
    "InboundMessage",
    "get_channel",
    "encrypt_credentials",
    "decrypt_credentials",
    "CHANNEL_MAP",
]
