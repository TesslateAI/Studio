#!/usr/bin/env python3
"""
Generate a cryptographically secure random key for use as SECRET_KEY in FastAPI/Django apps.
Output: 64-character hexadecimal string (32 bytes)
"""

import secrets

def generate_secret_key(length: int = 32) -> str:
    """
    Generate a cryptographically secure random key.

    Args:
        length: Number of random bytes (default 32 = 64 hex chars)

    Returns:
        Hexadecimal string representation of random bytes
    """
    return secrets.token_hex(length)


if __name__ == "__main__":
    key = generate_secret_key()
    print(key)
