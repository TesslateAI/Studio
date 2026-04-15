"""Hash-pin test for the frozen manifest schema.

The schema file at services/apps/app_manifest_2025_01.schema.json is IMMUTABLE.
Any change to its bytes must fail this test. To publish a new manifest version,
create a sibling file (e.g. app_manifest_2026_01.schema.json) and a new
Pydantic model — do not mutate the existing file.

If this test fails after an intentional v1 correction (e.g. typo in a
description field), update PINNED_SHA256 only after explicit review and
documentation of the exception in the PR description.
"""

from app.services.apps.manifest_parser import schema_hash

PINNED_SHA256 = "12cb669f28580ad41e495c3d5d231c8ffdf13a763e149a20f95d0e754b3833c4"


def test_manifest_schema_v1_bytes_frozen() -> None:
    actual = schema_hash()
    assert actual == PINNED_SHA256, (
        "app_manifest_2025_01.schema.json has changed.\n"
        f"  pinned:  {PINNED_SHA256}\n"
        f"  current: {actual}\n"
        "v1 is frozen. To evolve the manifest, add a new dated schema file."
    )
