"""
Stage 1 — static structural scanner for a marketplace submission.

The scanner runs a fixed list of deterministic checks against the persisted
:class:`~app.models.Submission` row's manifest + bundle metadata and records
each result via :func:`submissions.record_check`. On all-pass it advances
the submission to ``stage2``; on any hard failure it transitions to
``rejected``. Warnings never fail the stage.

This is the marketplace-side replacement for the orchestrator's Wave 7
``services/apps/stage1_scanner.py``. The orchestrator-side implementation
referenced ``AppSubmission`` / ``AppVersion`` rows that no longer live on
this service; the checks below run against the marketplace's own
:class:`Submission` row and its ``manifest`` JSON.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from . import submissions

__all__ = ["run_stage1_scan", "STAGE1_CHECKS"]

logger = logging.getLogger(__name__)

# Slug character set — the same lowercase-alnum + dash + underscore allowed
# by the orchestrator. Defined here once so the scanner and the publish
# path share a single source of truth.
_SLUG_ALLOWED = set("abcdefghijklmnopqrstuvwxyz0123456789-_")

# Hard-coded baseline server feature set for stage1 ``features_supported``.
# In production this would be loaded from a config table; for the federated
# service the orchestrator forwards `required_features` in the manifest and
# we accept whatever the orchestrator declared. The list below is the
# minimum the marketplace itself can serve.
_SUPPORTED_FEATURES: frozenset[str] = frozenset(
    {
        "agent",
        "skill",
        "mcp_server",
        "base",
        "app",
        "theme",
        "workflow_template",
        "manifest_2025_01",
        "manifest_2025_02",
        "manifest_2026_05",
    }
)


def _get(manifest: dict[str, Any], key: str, default: Any = None) -> Any:
    return manifest.get(key, default) if isinstance(manifest, dict) else default


def _check_slug_format(slug: str) -> tuple[str, str | None, dict[str, Any] | None]:
    if not slug:
        return "failed", "slug is empty", None
    if any(c not in _SLUG_ALLOWED for c in slug):
        return "failed", f"slug must be lowercase alphanumeric: {slug!r}", None
    return "passed", None, {"slug": slug}


def _check_manifest_shape(
    manifest: dict[str, Any] | None,
) -> tuple[str, str | None, dict[str, Any] | None]:
    if manifest is None:
        return "warning", "no manifest provided", None
    if not isinstance(manifest, dict):
        return "failed", "manifest must be a JSON object", None
    return "passed", None, {"manifest_keys": sorted(list(manifest.keys()))}


def _check_features_supported(
    manifest: dict[str, Any] | None,
) -> tuple[str, str | None, dict[str, Any] | None]:
    required = []
    if isinstance(manifest, dict):
        raw = manifest.get("required_features", [])
        if isinstance(raw, list):
            required = [str(x) for x in raw if x]
    missing = [f for f in required if f not in _SUPPORTED_FEATURES]
    if missing:
        return "failed", f"unsupported features: {missing}", {"missing": missing}
    return "passed", None, {"required": required}


def _check_disclosure(
    manifest: dict[str, Any] | None,
) -> tuple[str, str | None, dict[str, Any] | None]:
    if not isinstance(manifest, dict):
        # Already covered by manifest_shape; skip downstream so the test
        # surface stays clean.
        return "skipped", "no manifest available", None
    missing = []
    if _get(manifest, "source_visibility") in (None, ""):
        missing.append("source_visibility")
    if _get(manifest, "forkable") is None:
        missing.append("forkable")
    if missing:
        # Disclosure being unset is a warning, not a hard failure: the
        # orchestrator's pre-Wave-8 behaviour rejected on missing disclosure
        # but the marketplace surface accepts non-app kinds (skills, themes,
        # workflow_templates) for which the disclosure flags don't apply.
        return "warning", f"missing disclosure fields: {missing}", {"missing": missing}
    return "passed", None, {}


def _check_billing_dims(
    manifest: dict[str, Any] | None,
) -> tuple[str, str | None, dict[str, Any] | None]:
    billing = _get(manifest, "billing", {}) or {}
    dims = billing.get("dimensions", []) if isinstance(billing, dict) else []
    if not isinstance(dims, list):
        return "failed", "billing.dimensions must be a JSON array", None
    bad = [d.get("name") for d in dims if isinstance(d, dict) and not d.get("payer")]
    if bad:
        return "failed", f"billing dimensions missing payer: {bad}", {"dimensions": bad}
    return "passed", None, {"dimensions": len(dims)}


def _check_bundle_metadata(
    declared_sha: str | None,
    declared_size: int | None,
) -> tuple[str, str | None, dict[str, Any] | None]:
    if declared_sha is None or declared_size is None:
        return "warning", "manifest-only submission (no bundle declared)", None
    if not declared_sha or len(declared_sha) != 64:
        return "failed", "bundle_sha256 must be a 64-char hex digest", None
    if declared_size <= 0:
        return "failed", "bundle_size_bytes must be positive", None
    return "passed", None, {"sha256": declared_sha, "size_bytes": declared_size}


# Ordered tuple — also exported so tests can introspect the check list.
STAGE1_CHECKS: tuple[str, ...] = (
    "slug_format",
    "manifest_shape",
    "features_supported",
    "disclosure_present",
    "billing_dims_have_payer",
    "bundle_metadata",
)


async def run_stage1_scan(
    db: AsyncSession,
    *,
    submission_id: uuid.UUID,
) -> dict[str, Any]:
    """Run Stage1 structural checks and advance the submission stage.

    Returns a dict reporting check counts, the failure list, and the next
    stage so callers can react without re-querying the DB.
    """
    sub = await submissions.load_submission(db, submission_id)
    manifest = sub.manifest if isinstance(sub.manifest, dict) else None

    results: list[tuple[str, str, str | None, dict[str, Any] | None]] = []
    status, message, details = _check_slug_format(sub.slug)
    results.append(("slug_format", status, message, details))
    status, message, details = _check_manifest_shape(manifest)
    results.append(("manifest_shape", status, message, details))
    status, message, details = _check_features_supported(manifest)
    results.append(("features_supported", status, message, details))
    status, message, details = _check_disclosure(manifest)
    results.append(("disclosure_present", status, message, details))
    status, message, details = _check_billing_dims(manifest)
    results.append(("billing_dims_have_payer", status, message, details))
    status, message, details = _check_bundle_metadata(
        sub.bundle_sha256, sub.bundle_size_bytes
    )
    results.append(("bundle_metadata", status, message, details))

    failures: list[str] = []
    for name, status, message, details in results:
        await submissions.record_check(
            db,
            submission_id=submission_id,
            stage="stage1",
            name=name,
            status=status,  # type: ignore[arg-type]
            message=message,
            details=details,
        )
        if status in ("failed", "errored"):
            failures.append(name)

    if failures:
        await submissions.advance_stage(
            db,
            submission_id=submission_id,
            to_stage="rejected",
            decision_reason=f"stage1 failed: {','.join(failures)}",
        )
        target = "rejected"
    else:
        await submissions.advance_stage(db, submission_id=submission_id, to_stage="stage2")
        target = "stage2"

    logger.info(
        "stage1.scan submission=%s checks=%d failures=%d -> %s",
        submission_id,
        len(results),
        len(failures),
        target,
    )
    return {"checks_run": len(results), "failures": failures, "advanced_to": target}
