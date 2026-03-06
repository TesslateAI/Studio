"""Utilities for encoding/decoding secret values."""

import base64


def encode_secret(value: str) -> str:
    """Encode a secret for storage."""
    return base64.b64encode(value.encode()).decode()


def decode_secret(encoded: str) -> str:
    """Decode a stored secret."""
    return base64.b64decode(encoded.encode()).decode()


def encode_secret_map(values: dict[str, str]) -> dict[str, str]:
    """Encode a mapping of secret values."""
    return {key: encode_secret(value) for key, value in values.items()}


def decode_secret_map(values: dict[str, str]) -> dict[str, str]:
    """Decode a mapping of secret values."""
    return {key: decode_secret(value) for key, value in values.items()}
