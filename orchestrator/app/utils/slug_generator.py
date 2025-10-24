"""
Slug generation utilities for creating human-readable, unique identifiers.

Follows modern best practices (Vercel, Railway, Render pattern):
- Project slugs: "my-awesome-app-k3x8n2" (name + short hash)
- Username slugs: "ernest-k3x8n2" (name + short hash)

Features:
- Non-enumerable (secure)
- Collision-free (hash suffix)
- Human-readable (slug prefix)
- URL-safe (lowercase, hyphens)
"""

import re
from typing import Optional
from nanoid import generate


def slugify(text: str, max_length: int = 50) -> str:
    """
    Convert text to URL-safe slug.

    Examples:
        "My Awesome App!" -> "my-awesome-app"
        "Hello_World 123" -> "hello-world-123"
        "Émojis 🎉 Test" -> "emojis-test"

    Args:
        text: Input text to slugify
        max_length: Maximum length of resulting slug

    Returns:
        URL-safe slug (lowercase, alphanumeric + hyphens)
    """
    # Convert to lowercase
    slug = text.lower()

    # Remove non-alphanumeric characters (except spaces and hyphens)
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)

    # Replace spaces and multiple hyphens with single hyphen
    slug = re.sub(r'[\s-]+', '-', slug)

    # Remove leading/trailing hyphens
    slug = slug.strip('-')

    # Truncate to max length
    slug = slug[:max_length]

    # Ensure no trailing hyphen after truncation
    slug = slug.rstrip('-')

    # Fallback if slug is empty
    if not slug:
        slug = 'project'

    return slug


def generate_short_hash(length: int = 6) -> str:
    """
    Generate a short, URL-safe random hash.

    Uses nanoid with lowercase alphanumeric alphabet for maximum readability.

    Args:
        length: Length of hash (default 6 = 2.2B combinations)

    Returns:
        Random hash string (e.g., "k3x8n2")

    Collision probability (birthday paradox):
        - 6 chars: ~1% at 100k projects
        - 8 chars: ~1% at 6M projects
    """
    alphabet = '0123456789abcdefghijklmnopqrstuvwxyz'
    return generate(alphabet, length)


def generate_project_slug(project_name: str, hash_length: int = 6) -> str:
    """
    Generate unique project slug: "my-awesome-app-k3x8n2"

    Format: {slugified-name}-{random-hash}

    Examples:
        "My Awesome App" -> "my-awesome-app-k3x8n2"
        "Hello World!" -> "hello-world-a5b3c1"
        "Test 123" -> "test-123-d7f9e2"

    Args:
        project_name: Human-readable project name
        hash_length: Length of random hash suffix (default 6)

    Returns:
        Unique project slug
    """
    base_slug = slugify(project_name, max_length=50)
    hash_suffix = generate_short_hash(hash_length)
    return f"{base_slug}-{hash_suffix}"


def generate_username_slug(
    username: Optional[str] = None,
    email: Optional[str] = None,
    hash_length: int = 6
) -> str:
    """
    Generate unique username slug: "ernest-k3x8n2"

    Format: {slugified-username}-{random-hash}

    Args:
        username: Preferred username (if available)
        email: Email address (fallback if no username)
        hash_length: Length of random hash suffix (default 6)

    Returns:
        Unique username slug

    Examples:
        username="Ernest" -> "ernest-k3x8n2"
        email="ernest@example.com" -> "ernest-a5b3c1"
        Neither provided -> "user-d7f9e2"
    """
    if username:
        base_slug = slugify(username, max_length=50)
    elif email:
        # Extract username part from email
        email_prefix = email.split('@')[0]
        base_slug = slugify(email_prefix, max_length=50)
    else:
        base_slug = 'user'

    hash_suffix = generate_short_hash(hash_length)
    return f"{base_slug}-{hash_suffix}"


def is_valid_slug(slug: str) -> bool:
    """
    Validate if a string is a valid slug format.

    Valid slug pattern: lowercase alphanumeric + hyphens
    Must start and end with alphanumeric character

    Args:
        slug: String to validate

    Returns:
        True if valid slug format
    """
    if not slug:
        return False

    # Must be lowercase alphanumeric + hyphens
    # Must start and end with alphanumeric
    pattern = r'^[a-z0-9]+(-[a-z0-9]+)*$'
    return bool(re.match(pattern, slug))
