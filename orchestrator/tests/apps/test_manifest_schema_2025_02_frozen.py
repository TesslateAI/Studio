"""Hash-pin test for the 2025-02 manifest schema.

Mirrors test_manifest_schema_frozen.py. Once 2025-02 lands in main it is
immutable; bump to a new dated file for any further evolution.
"""

from app.services.apps.manifest_parser import schema_hash

PINNED_SHA256 = "646f9adf3522d59464182bd5c9de1c6e19a91bfa018c8bbef33309025280d7cc"


def test_manifest_schema_2025_02_bytes_frozen() -> None:
    actual = schema_hash("2025-02")
    assert actual == PINNED_SHA256, (
        "app_manifest_2025_02.schema.json has changed.\n"
        f"  pinned:  {PINNED_SHA256}\n"
        f"  current: {actual}\n"
        "2025-02 is frozen. To evolve the manifest, add a new dated schema file."
    )
