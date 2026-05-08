"""Hash-pin test for the 2026-06 manifest schema.

Mirrors test_manifest_schema_2025_02_frozen.py. 2026-06 is the container-shape
additive successor to 2025-02 (compute.credentials[],
compute.containers[].readiness_port, state.mount_path). Once it lands in main
the schema bytes are immutable; bump to a new dated file for any further
evolution.
"""

from app.services.apps.manifest_parser import schema_hash

PINNED_SHA256 = "19ee47b3d6382b49e0c63b29c58bdb91fa3978f4ed17902256e4c9507acb4b8f"


def test_manifest_schema_2026_06_bytes_frozen() -> None:
    actual = schema_hash("2026-06")
    assert actual == PINNED_SHA256, (
        "app_manifest_2026_06.schema.json has changed.\n"
        f"  pinned:  {PINNED_SHA256}\n"
        f"  current: {actual}\n"
        "2026-06 is frozen. To evolve the manifest, add a new dated schema file."
    )
