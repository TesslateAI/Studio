"""Stage1 ("AI-assisted review") scanner.

Wave 7 ships a deterministic structural scanner. Real LLM-assisted review
hooks plug into the same per-check recording surface later.

Checks run (in order):

1. ``manifest_parses``     : re-validates the persisted manifest_json.
2. ``features_supported``  : required_features ⊆ current server features.
3. ``mcp_scope_safe_list`` : informational warning (no safe-list yet).
4. ``disclosure_present``  : source_visibility + forkable declared.
5. ``billing_dims_have_payer`` : every billing dimension names a payer.

On all-pass we advance to ``stage2``; on any hard failure we jump to
``rejected``. Warnings never fail the stage.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ... import config_features
from ...models import AppSubmission, AppVersion
from . import submissions
from .manifest_parser import ManifestValidationError, parse

__all__ = ["run_stage1_scan"]

logger = logging.getLogger(__name__)


def _get(manifest: dict[str, Any], key: str, default: Any = None) -> Any:
    return manifest.get(key, default) if isinstance(manifest, dict) else default


def _check_manifest_parses(manifest_json: dict) -> tuple[str, dict]:
    try:
        parse(manifest_json)
        return "passed", {}
    except ManifestValidationError as exc:
        return "failed", {"error": str(exc), "errors": exc.errors}
    except Exception as exc:  # pragma: no cover - defensive
        return "errored", {"error": repr(exc)}


def _check_features_supported(required: list[str]) -> tuple[str, dict]:
    missing = config_features.diff(list(required or []))
    if missing:
        return "failed", {"missing_features": missing}
    return "passed", {"required": list(required or [])}


def _check_mcp_safe_list(manifest: dict) -> tuple[str, dict]:
    # Wave 7: no configured safe-list yet. Emit a warning so the audit trail
    # is explicit and future tightening is a single change.
    mcp = _get(manifest, "mcp_scopes", []) or []
    return "warning", {"declared_mcp_scopes": list(mcp), "note": "no safe-list configured"}


def _check_disclosure(manifest: dict) -> tuple[str, dict]:
    missing = []
    if _get(manifest, "source_visibility") in (None, ""):
        missing.append("source_visibility")
    if _get(manifest, "forkable") is None:
        missing.append("forkable")
    if missing:
        return "failed", {"missing_fields": missing}
    return "passed", {}


def _check_billing_dims(manifest: dict) -> tuple[str, dict]:
    billing = _get(manifest, "billing", {}) or {}
    dims = billing.get("dimensions", []) if isinstance(billing, dict) else []
    bad = [d.get("name") for d in dims if isinstance(d, dict) and not d.get("payer")]
    if bad:
        return "failed", {"dimensions_missing_payer": bad}
    return "passed", {"dimensions": len(dims)}


async def run_stage1_scan(
    db: AsyncSession,
    *,
    submission_id: UUID,
) -> dict:
    """Run Stage1 structural checks and advance the submission stage."""
    sub = (
        await db.execute(
            select(AppSubmission).where(AppSubmission.id == submission_id)
        )
    ).scalar_one_or_none()
    if sub is None:
        raise submissions.SubmissionNotFoundError(str(submission_id))

    av = (
        await db.execute(
            select(AppVersion).where(AppVersion.id == sub.app_version_id)
        )
    ).scalar_one_or_none()
    if av is None:
        raise LookupError(f"app_version {sub.app_version_id} not found")

    manifest = av.manifest_json if isinstance(av.manifest_json, dict) else {}
    required = list(av.required_features or [])

    results = [
        ("manifest_parses", *_check_manifest_parses(manifest)),
        ("features_supported", *_check_features_supported(required)),
        ("mcp_scope_safe_list", *_check_mcp_safe_list(manifest)),
        ("disclosure_present", *_check_disclosure(manifest)),
        ("billing_dims_have_payer", *_check_billing_dims(manifest)),
    ]

    failures: list[str] = []
    for check_name, status, details in results:
        await submissions.record_check(
            db,
            submission_id=submission_id,
            stage="stage1",
            check_name=check_name,
            status=status,
            details=details,
        )
        if status in ("failed", "errored"):
            failures.append(check_name)

    target = "stage2" if not failures else "rejected"
    await submissions.advance_stage(
        db,
        submission_id=submission_id,
        to_stage=target,
        decision_notes=(
            None if target == "stage2" else f"stage1 failed: {','.join(failures)}"
        ),
    )
    logger.info(
        "stage1.scan submission=%s checks=%d failures=%d -> %s",
        submission_id,
        len(results),
        len(failures),
        target,
    )
    return {"checks_run": len(results), "failures": failures, "advanced_to": target}
