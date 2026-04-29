"""
Build seed tar.zst bundles from the JSON seed files.

For each seed entry we generate a tiny tar.zst archive containing one
`item.manifest.json` blob (and `app.manifest.json` for the `app` kind, per the
plan). The result lives at `app/bundles/<kind>/<slug>/<version>.tar.zst`.

These are *real* archives — `safe_extract` round-trips them in tests, and the
bundle envelope's signed URL streams them back to clients.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from app.services.install_check import write_tar_zst

logger = logging.getLogger("bundle_builder")


SEED_FILES: list[str] = [
    "agents.json",
    "opensource_agents.json",
    "bases.json",
    "community_bases.json",
    "skills_opensource.json",
    "skills_tesslate.json",
    "mcp_servers.json",
    "themes.json",
    "workflow_templates.json",
    "apps.json",
]


def _build_bundle_bytes(entry: dict, kind: str) -> bytes:
    members: dict[str, bytes] = {
        "item.manifest.json": json.dumps(entry, indent=2, sort_keys=True).encode("utf-8"),
    }
    if kind == "app":
        members["app.manifest.json"] = json.dumps(
            {
                "manifest_schema": "2026-05",
                "slug": entry["slug"],
                "name": entry.get("name", entry["slug"]),
                "version": entry.get("version", "0.1.0"),
            },
            indent=2,
        ).encode("utf-8")
    if kind == "skill":
        skill_body = entry.get("skill_body") or entry.get("fallback_skill_body") or ""
        members["SKILL.md"] = skill_body.encode("utf-8")
    if kind == "base":
        members["base.manifest.json"] = json.dumps(
            {
                "git_repo_url": entry.get("git_repo_url"),
                "default_branch": entry.get("default_branch", "main"),
                "tech_stack": entry.get("tech_stack", []),
            },
            indent=2,
        ).encode("utf-8")
    return write_tar_zst(members)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=Path, default=Path("app/seeds"))
    parser.add_argument("--output", type=Path, default=Path("app/bundles"))
    parser.add_argument("--version", default="0.1.0")
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    total = 0
    for filename in SEED_FILES:
        path = args.seeds / filename
        if not path.exists():
            logger.warning("seed file %s missing; skipping", path)
            continue
        try:
            entries = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.error("could not parse %s: %s", path, exc)
            continue
        if not isinstance(entries, list):
            logger.warning("%s is not a list", path)
            continue
        for entry in entries:
            kind = entry.get("kind")
            slug = entry.get("slug")
            if not kind or not slug:
                logger.warning("seed entry missing kind/slug: %s", entry)
                continue
            version = entry.get("version") or args.version
            bundle = _build_bundle_bytes(entry, kind)
            dest = args.output / kind / slug
            dest.mkdir(parents=True, exist_ok=True)
            target = dest / f"{version}.tar.zst"
            target.write_bytes(bundle)
            total += 1
            logger.debug("wrote %s (%d bytes)", target, len(bundle))
    logger.info("built %d bundles", total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
