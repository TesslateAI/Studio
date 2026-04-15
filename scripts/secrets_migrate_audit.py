#!/usr/bin/env python3
"""Audit container env vars for ambiguous / unmigrated secrets.

Usage::

    uv run python scripts/secrets_migrate_audit.py [--fix-dry-run]

Walks every ``Container`` row. For each, classifies env-var keys as:

  * preset-secret   — matched by the service_definitions preset.
  * regex-secret    — matched by the secret-shape regex.
  * ambiguous       — value looks base64-ish but key is not recognized as a
                      secret by either classifier.
  * plain           — nothing to worry about.

Exits non-zero if ambiguous keys exist (useful as a CI gate before running
migration 0058). ``--fix-dry-run`` prints the row-by-row actions the
``0057_backfill_container_secrets`` migration would take, without mutating
any data.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
import os
import re
import sys
from pathlib import Path

# Allow running from repo root: add orchestrator/ to sys.path.
_ORCH = Path(__file__).resolve().parent.parent / "orchestrator"
if str(_ORCH) not in sys.path:
    sys.path.insert(0, str(_ORCH))

_SECRET_KEY_RE = re.compile(r"(?i)(KEY|SECRET|TOKEN|PASSWORD|PASS|CREDENTIAL|PRIVATE)")
_BASE64_RE = re.compile(r"^[A-Za-z0-9+/=]+$")


def _looks_base64(value: str) -> bool:
    if not value or len(value) < 8 or len(value) % 4 != 0:
        return False
    if not _BASE64_RE.match(value):
        return False
    try:
        decoded = base64.b64decode(value.encode("utf-8"), validate=True).decode(
            "utf-8"
        )
    except (binascii.Error, UnicodeDecodeError):
        return False
    return all(ord(c) >= 32 or c in "\n\r\t" for c in decoded)


async def _run(fix_dry_run: bool) -> int:
    # Import after sys.path patch
    from sqlalchemy import select  # noqa: E402

    from app.database import AsyncSessionLocal  # noqa: E402
    from app.models import Container  # noqa: E402
    from app.services.service_definitions import get_service  # noqa: E402

    total = 0
    preset_secrets = 0
    regex_secrets = 0
    ambiguous: list[tuple[str, str]] = []
    fix_rows: list[tuple[str, list[str]]] = []

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Container))
        containers = result.scalars().all()

        for container in containers:
            env_vars = container.environment_vars or {}
            encrypted = container.encrypted_secrets or {}
            if not env_vars:
                continue
            preset_keys: set[str] = set()
            if container.service_slug:
                svc = get_service(container.service_slug)
                if svc and svc.credential_fields:
                    preset_keys = {f.key for f in svc.credential_fields}
            row_fix: list[str] = []
            for key, value in env_vars.items():
                total += 1
                if key in preset_keys:
                    preset_secrets += 1
                    if key not in encrypted:
                        row_fix.append(key)
                    continue
                if _SECRET_KEY_RE.search(key):
                    regex_secrets += 1
                    if key not in encrypted:
                        row_fix.append(key)
                    continue
                if isinstance(value, str) and _looks_base64(value):
                    ambiguous.append((str(container.id), key))
            if row_fix:
                fix_rows.append((str(container.id), row_fix))

    print(f"Total env-var entries scanned: {total}")
    print(f"Preset-matched secret keys   : {preset_secrets}")
    print(f"Regex-matched secret keys    : {regex_secrets}")
    print(f"Ambiguous (base64-ish values, unknown keys): {len(ambiguous)}")
    for cid, key in ambiguous[:20]:
        print(f"  - container={cid} key={key}")
    if len(ambiguous) > 20:
        print(f"  … and {len(ambiguous) - 20} more")

    if fix_dry_run:
        print()
        print("Fix plan (what migration 0057 would move to encrypted_secrets):")
        for cid, keys in fix_rows:
            print(f"  - container={cid} keys={keys}")

    return 1 if ambiguous else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fix-dry-run",
        action="store_true",
        help="Also print the per-container fix plan without mutating anything.",
    )
    args = parser.parse_args()
    # Ensure a DB URL is set — the script fails fast with a clearer message
    # if the caller forgot to load the orchestrator's env.
    if not os.getenv("DATABASE_URL"):
        print(
            "DATABASE_URL not set — source the orchestrator's .env before running.",
            file=sys.stderr,
        )
        return 2
    return asyncio.run(_run(args.fix_dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
