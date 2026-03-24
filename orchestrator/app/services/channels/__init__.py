"""
Messaging Channel System

Provides a unified interface for sending/receiving messages across
Telegram, Slack, Discord, and WhatsApp platforms.
"""

from .base import AbstractChannel, InboundMessage
from .registry import CHANNEL_MAP, decrypt_credentials, encrypt_credentials, get_channel

__all__ = [
    "AbstractChannel",
    "InboundMessage",
    "get_channel",
    "encrypt_credentials",
    "decrypt_credentials",
    "CHANNEL_MAP",
]
