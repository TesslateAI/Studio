"""Approval-card artifact attachment via the gateway runner.

Verifies the Phase 4 contract documented on
``app.services.gateway.runner.GatewayRunner._process_approval_card_delivery``:

* When an :class:`AutomationApprovalRequest.context_artifacts` is non-
  empty, the runner uploads each artifact to the destination's adapter
  BEFORE posting the card.
* Slack adapters get ``upload_file`` calls; Telegram adapters get
  ``send_document`` calls. Each upload carries the artifact's bytes
  (resolved from inline base64 storage) and filename.
* Artifacts larger than the 25 MiB cap are skipped, and the card body
  is annotated with a "(file too large to attach)" line so the user
  always knows what didn't come through.
* Slack DM destinations don't get the upload pass (text-only) — the
  initial cut prefers correctness over a 3-RTT DM upload.
* The approval request's ``delivered_to`` audit row records per-artifact
  upload outcomes so operators can debug attachment failures.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# Migration fixtures (mirror test_approval_card_dm_owner.py)
# ---------------------------------------------------------------------------


def _install_sqlite_now(engine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ARG001
        dbapi_conn.create_function(
            "now", 0, lambda: datetime.now(UTC).isoformat(sep=" ")
        )


def _alembic_cfg() -> Config:
    orchestrator_dir = Path(__file__).resolve().parents[2]
    cfg = Config(str(orchestrator_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(orchestrator_dir / "alembic"))
    return cfg


@pytest.fixture
def migrated_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    db_path = tmp_path / "approval_artifacts.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DEPLOYMENT_MODE", "desktop")

    from app.config import get_settings

    get_settings.cache_clear()
    orchestrator_dir = Path(__file__).resolve().parents[2]
    original = os.getcwd()
    os.chdir(orchestrator_dir)
    try:
        command.upgrade(_alembic_cfg(), "head")
    finally:
        os.chdir(original)
    yield url
    get_settings.cache_clear()


@pytest.fixture
def session_maker(migrated_sqlite: str):
    engine = create_async_engine(migrated_sqlite, future=True)
    _install_sqlite_now(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    asyncio.run(engine.dispose())


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_user(db) -> uuid.UUID:
    from sqlalchemy import insert as core_insert

    from app.models_auth import User

    user_id = uuid.uuid4()
    suffix = uuid.uuid4().hex[:8]
    await db.execute(
        core_insert(User.__table__).values(
            id=user_id,
            email=f"approval-art-{suffix}@example.com",
            hashed_password="x",
            is_active=True,
            is_superuser=False,
            is_verified=True,
            name="Approval Artifact Test User",
            username=f"u{suffix}",
            slug=f"u-{suffix}",
        )
    )
    await db.flush()
    return user_id


async def _seed_run(db, *, owner_user_id: uuid.UUID) -> uuid.UUID:
    from app.models_automations import (
        AutomationDefinition,
        AutomationEvent,
        AutomationRun,
    )

    autom_id = uuid.uuid4()
    db.add(
        AutomationDefinition(
            id=autom_id,
            name="art-approval",
            owner_user_id=owner_user_id,
            workspace_scope="none",
            contract={
                "allowed_tools": [],
                "max_compute_tier": 0,
                "on_breach": "pause_for_approval",
            },
            max_compute_tier=0,
            is_active=True,
        )
    )
    event_id = uuid.uuid4()
    db.add(
        AutomationEvent(
            id=event_id,
            automation_id=autom_id,
            payload={},
            trigger_kind="manual",
        )
    )
    run_id = uuid.uuid4()
    db.add(
        AutomationRun(
            id=run_id,
            automation_id=autom_id,
            event_id=event_id,
            status="running",
        )
    )
    await db.flush()
    return run_id


async def _seed_inline_artifact(
    db,
    *,
    run_id: uuid.UUID,
    name: str,
    content: bytes,
    mime_type: str = "text/plain",
) -> uuid.UUID:
    from app.models_automations import AutomationRunArtifact

    art_id = uuid.uuid4()
    db.add(
        AutomationRunArtifact(
            id=art_id,
            run_id=run_id,
            kind="text",
            name=name,
            mime_type=mime_type,
            storage_mode="inline",
            storage_ref=base64.b64encode(content).decode("ascii"),
            preview_text=content.decode("utf-8", errors="replace")[:200],
            size_bytes=len(content),
        )
    )
    await db.flush()
    return art_id


async def _seed_large_artifact_row(
    db, *, run_id: uuid.UUID, name: str, size_bytes: int
) -> uuid.UUID:
    """Seed an artifact row that CLAIMS to be too large.

    We don't actually allocate the bytes — we just set ``size_bytes``
    above the cap so the runner's pre-check rejects it without ever
    materialising the payload.
    """
    from app.models_automations import AutomationRunArtifact

    art_id = uuid.uuid4()
    db.add(
        AutomationRunArtifact(
            id=art_id,
            run_id=run_id,
            kind="file",
            name=name,
            mime_type="application/octet-stream",
            storage_mode="cas",
            storage_ref="sha256:deadbeef",  # never read for too-large rows
            preview_text=None,
            size_bytes=size_bytes,
        )
    )
    await db.flush()
    return art_id


async def _seed_approval_with_artifacts(
    db,
    *,
    run_id: uuid.UUID,
    artifact_ids: list[uuid.UUID],
) -> uuid.UUID:
    from app.models_automations import AutomationApprovalRequest

    req_id = uuid.uuid4()
    db.add(
        AutomationApprovalRequest(
            id=req_id,
            run_id=run_id,
            reason="contract_violation",
            context={"tool_name": "report_publish", "summary": "review this report"},
            context_artifacts=[str(a) for a in artifact_ids],
            options=["allow_once", "deny"],
        )
    )
    await db.flush()
    return req_id


async def _seed_channel_config(
    db, *, owner_user_id: uuid.UUID, channel_type: str = "slack"
) -> uuid.UUID:
    from app.models import ChannelConfig

    cc_id = uuid.uuid4()
    db.add(
        ChannelConfig(
            id=cc_id,
            user_id=owner_user_id,
            channel_type=channel_type,
            name=f"{channel_type}-test",
            # credentials is a Fernet-encrypted JSON blob in production;
            # for these tests the runner never decodes it (we feed the
            # adapter via runner.adapters directly), so any non-empty
            # string keeps the NOT NULL constraint happy.
            credentials="encrypted-stub",
            webhook_secret="stub-secret",
            is_active=True,
        )
    )
    await db.flush()
    return cc_id


async def _seed_destination(
    db,
    *,
    owner_user_id: uuid.UUID,
    channel_config_id: uuid.UUID,
    kind: str = "slack_channel",
    target_chat_id: str = "C0123ABC",
) -> uuid.UUID:
    from app.models_automations import CommunicationDestination

    dest_id = uuid.uuid4()
    db.add(
        CommunicationDestination(
            id=dest_id,
            owner_user_id=owner_user_id,
            channel_config_id=channel_config_id,
            kind=kind,
            name=f"dest-{kind}-{target_chat_id}",
            config={"chat_id": target_chat_id, "channel_id": target_chat_id},
        )
    )
    await db.flush()
    return dest_id


# ---------------------------------------------------------------------------
# Runner harness — instantiate just enough of GatewayRunner for the test
# ---------------------------------------------------------------------------


def _make_runner(session_maker, adapters: dict[str, object]):
    """Build a minimal GatewayRunner pointing at our session_maker.

    We don't call ``runner.start()`` — that would spin up Redis, the
    delivery consumer, scheduler tasks, etc. We only need
    ``_process_approval_card_delivery`` to work, which uses
    ``self._db_factory`` and ``self.adapters``.
    """
    from app.services.gateway.runner import GatewayRunner

    runner = GatewayRunner(shard=0)
    runner._db_factory = session_maker
    runner.adapters = dict(adapters)
    return runner


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_slack_approval_card_uploads_artifacts_before_posting(
    session_maker,
) -> None:
    """End-to-end: Slack adapter receives upload_file calls per artifact,
    THEN send_approval_card."""
    # 1. Seed everything.
    artifact_id_1 = artifact_id_2 = approval_id = dest_id = cc_id = None
    artifact_bytes_1 = b"# Standup report\n\n- shipped X\n- blocked on Y\n"
    artifact_bytes_2 = b"line1,line2\n1,2\n3,4\n"
    async with session_maker() as db:
        owner_id = await _seed_user(db)
        run_id = await _seed_run(db, owner_user_id=owner_id)
        artifact_id_1 = await _seed_inline_artifact(
            db, run_id=run_id, name="standup.md", content=artifact_bytes_1
        )
        artifact_id_2 = await _seed_inline_artifact(
            db,
            run_id=run_id,
            name="metrics.csv",
            content=artifact_bytes_2,
            mime_type="text/csv",
        )
        approval_id = await _seed_approval_with_artifacts(
            db, run_id=run_id, artifact_ids=[artifact_id_1, artifact_id_2]
        )
        cc_id = await _seed_channel_config(db, owner_user_id=owner_id)
        dest_id = await _seed_destination(
            db,
            owner_user_id=owner_id,
            channel_config_id=cc_id,
            kind="slack_channel",
            target_chat_id="C0123CHAN",
        )
        await db.commit()

    # 2. Mock the adapter — record upload_file + send_approval_card calls
    #    in the order they happen so we can assert ordering.
    call_log: list[tuple[str, dict]] = []

    async def fake_upload_file(**kwargs):
        call_log.append(("upload_file", kwargs))
        return {
            "ok": True,
            "file_id": f"F-{kwargs.get('filename')}",
            "permalink": f"https://example/files/{kwargs.get('filename')}",
        }

    async def fake_send_approval_card(*args, **kwargs):
        call_log.append(("send_approval_card", {"args": args, "kwargs": kwargs}))
        return {"ok": True, "ts": "1700000000.000100", "channel": args[0]}

    adapter = MagicMock(
        spec_set=["channel_type", "upload_file", "send_approval_card"]
    )
    adapter.channel_type = "slack"
    adapter.upload_file = AsyncMock(side_effect=fake_upload_file)
    adapter.send_approval_card = AsyncMock(side_effect=fake_send_approval_card)
    # No DM method, no send_document — exercise the channel path.

    runner = _make_runner(session_maker, {str(cc_id): adapter})

    # 3. Build the parsed envelope the runner consumes.
    envelope = {
        "kind": "approval_card",
        "config_id": str(cc_id),
        "session_key": "",
        "task_id": "",
        "body": json.dumps(
            {
                "input_id": str(approval_id),
                "automation_id": "",
                "tool_name": "report_publish",
                "summary": "review this report and approve",
                "actions": ["allow_once", "deny"],
                "destination_ids": [str(dest_id)],
            }
        ),
        "artifact_refs": [],  # the row's context_artifacts column drives this
    }

    await runner._process_approval_card_delivery(envelope)

    # 4. Verify both uploads happened, in artifact-list order, BEFORE
    #    the card was posted.
    upload_calls = [c for c in call_log if c[0] == "upload_file"]
    card_calls = [c for c in call_log if c[0] == "send_approval_card"]
    assert len(upload_calls) == 2, (
        f"expected 2 upload_file calls, got {len(upload_calls)}"
    )
    assert len(card_calls) == 1
    # Ordering — every upload happens before the card post.
    last_upload_idx = max(i for i, c in enumerate(call_log) if c[0] == "upload_file")
    card_idx = next(i for i, c in enumerate(call_log) if c[0] == "send_approval_card")
    assert last_upload_idx < card_idx, (
        "uploads must complete before the card is posted so the user "
        "sees files appear above the actionable card"
    )

    # 5. Each upload carried the right bytes + filename + channel.
    upload_payloads = [c[1] for c in upload_calls]
    by_filename = {p["filename"]: p for p in upload_payloads}
    assert "standup.md" in by_filename
    assert by_filename["standup.md"]["content"] == artifact_bytes_1
    assert by_filename["standup.md"]["channel_id"] == "C0123CHAN"
    assert "metrics.csv" in by_filename
    assert by_filename["metrics.csv"]["content"] == artifact_bytes_2

    # 6. Card body summary still mentions the original prompt.
    card_args = card_calls[0][1]["args"]
    summary_arg = card_args[4]
    assert "review this report" in summary_arg
    # Annotation line documents the attachments.
    assert "Attached 2 file" in summary_arg

    # 7. delivered_to audit recorded both artifact uploads as ok=True.
    from app.models_automations import AutomationApprovalRequest

    async with session_maker() as db:
        req = await db.scalar(
            select(AutomationApprovalRequest).where(
                AutomationApprovalRequest.id == approval_id
            )
        )
        delivered = list(req.delivered_to or [])

    assert delivered, "delivered_to should record the slack post"
    assert delivered[0].get("artifacts"), (
        "delivered_to row must include per-artifact upload audit"
    )
    artifact_audit = delivered[0]["artifacts"]
    assert len(artifact_audit) == 2
    assert all(a.get("ok") for a in artifact_audit)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_oversize_artifact_is_skipped_with_card_annotation(
    session_maker,
) -> None:
    """An artifact > 25 MiB is NOT uploaded; the card body documents the skip."""
    artifact_id_small = artifact_id_huge = approval_id = dest_id = cc_id = None
    small_bytes = b"small"
    HUGE_BYTES = 30 * 1024 * 1024  # 30 MiB > 25 MiB cap
    async with session_maker() as db:
        owner_id = await _seed_user(db)
        run_id = await _seed_run(db, owner_user_id=owner_id)
        artifact_id_small = await _seed_inline_artifact(
            db, run_id=run_id, name="small.txt", content=small_bytes
        )
        artifact_id_huge = await _seed_large_artifact_row(
            db, run_id=run_id, name="enormous.bin", size_bytes=HUGE_BYTES
        )
        approval_id = await _seed_approval_with_artifacts(
            db,
            run_id=run_id,
            artifact_ids=[artifact_id_small, artifact_id_huge],
        )
        cc_id = await _seed_channel_config(db, owner_user_id=owner_id)
        dest_id = await _seed_destination(
            db,
            owner_user_id=owner_id,
            channel_config_id=cc_id,
            kind="slack_channel",
            target_chat_id="C0DEAD",
        )
        await db.commit()

    upload_calls: list[dict] = []

    async def fake_upload_file(**kwargs):
        upload_calls.append(kwargs)
        return {"ok": True, "file_id": "F-1", "permalink": "p"}

    posted_summaries: list[str] = []

    async def fake_send_approval_card(*args, **kwargs):
        posted_summaries.append(args[4])
        return {"ok": True, "ts": "1700000000.000200", "channel": args[0]}

    adapter = MagicMock(
        spec_set=["channel_type", "upload_file", "send_approval_card"]
    )
    adapter.channel_type = "slack"
    adapter.upload_file = AsyncMock(side_effect=fake_upload_file)
    adapter.send_approval_card = AsyncMock(side_effect=fake_send_approval_card)

    runner = _make_runner(session_maker, {str(cc_id): adapter})

    envelope = {
        "kind": "approval_card",
        "config_id": str(cc_id),
        "session_key": "",
        "task_id": "",
        "body": json.dumps(
            {
                "input_id": str(approval_id),
                "automation_id": "",
                "tool_name": "publish",
                "summary": "ready to publish?",
                "actions": ["allow_once", "deny"],
                "destination_ids": [str(dest_id)],
            }
        ),
        "artifact_refs": [],
    }

    await runner._process_approval_card_delivery(envelope)

    # Only the small file uploaded.
    assert len(upload_calls) == 1
    assert upload_calls[0]["filename"] == "small.txt"

    # The card was still posted, and its body documents the skipped file.
    assert len(posted_summaries) == 1
    summary = posted_summaries[0]
    assert "ready to publish" in summary
    assert "Attached 1 file" in summary
    # Skip annotation calls out the offending file by name.
    assert "enormous.bin" in summary
    assert "too large" in summary.lower()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_telegram_approval_card_uses_send_document(session_maker) -> None:
    """Telegram destinations get send_document calls, not upload_file."""
    artifact_id = approval_id = dest_id = cc_id = None
    art_bytes = b"telegram-doc-payload"
    async with session_maker() as db:
        owner_id = await _seed_user(db)
        run_id = await _seed_run(db, owner_user_id=owner_id)
        artifact_id = await _seed_inline_artifact(
            db, run_id=run_id, name="report.txt", content=art_bytes
        )
        approval_id = await _seed_approval_with_artifacts(
            db, run_id=run_id, artifact_ids=[artifact_id]
        )
        cc_id = await _seed_channel_config(
            db, owner_user_id=owner_id, channel_type="telegram"
        )
        dest_id = await _seed_destination(
            db,
            owner_user_id=owner_id,
            channel_config_id=cc_id,
            kind="telegram_chat",
            target_chat_id="123456789",
        )
        await db.commit()

    sent_documents: list[dict] = []
    posted_cards: list[dict] = []

    async def fake_send_document(**kwargs):
        sent_documents.append(kwargs)
        return {"ok": True, "message_id": "42"}

    async def fake_send_approval_card(*args, **kwargs):
        posted_cards.append({"args": args, "kwargs": kwargs})
        return {"ok": True, "message_id": 99, "chat_id": args[0]}

    # MagicMock auto-creates every attribute on access, which would make
    # hasattr(adapter, "upload_file") return True even though the
    # telegram adapter has no such method. Use spec_set with the exact
    # method names so hasattr behaves like the real Slack vs Telegram
    # surface.
    adapter = MagicMock(spec_set=["channel_type", "send_document", "send_approval_card"])
    adapter.channel_type = "telegram"
    adapter.send_document = AsyncMock(side_effect=fake_send_document)
    adapter.send_approval_card = AsyncMock(side_effect=fake_send_approval_card)

    runner = _make_runner(session_maker, {str(cc_id): adapter})

    envelope = {
        "kind": "approval_card",
        "config_id": str(cc_id),
        "session_key": "",
        "task_id": "",
        "body": json.dumps(
            {
                "input_id": str(approval_id),
                "automation_id": "",
                "tool_name": "publish",
                "summary": "review the doc",
                "actions": ["allow_once", "deny"],
                "destination_ids": [str(dest_id)],
            }
        ),
        "artifact_refs": [],
    }

    await runner._process_approval_card_delivery(envelope)

    assert len(sent_documents) == 1, "telegram adapter must receive send_document"
    assert sent_documents[0]["filename"] == "report.txt"
    assert sent_documents[0]["content"] == art_bytes
    assert sent_documents[0]["chat_id"] == "123456789"

    assert len(posted_cards) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_envelope_artifact_refs_override_row_context(session_maker) -> None:
    """Producer-supplied envelope artifact_refs are honoured, deduped vs row."""
    art_envelope = art_row = approval_id = dest_id = cc_id = None
    async with session_maker() as db:
        owner_id = await _seed_user(db)
        run_id = await _seed_run(db, owner_user_id=owner_id)
        art_envelope = await _seed_inline_artifact(
            db, run_id=run_id, name="from-envelope.txt", content=b"e"
        )
        art_row = await _seed_inline_artifact(
            db, run_id=run_id, name="from-row.txt", content=b"r"
        )
        approval_id = await _seed_approval_with_artifacts(
            db, run_id=run_id, artifact_ids=[art_row]
        )
        cc_id = await _seed_channel_config(db, owner_user_id=owner_id)
        dest_id = await _seed_destination(
            db,
            owner_user_id=owner_id,
            channel_config_id=cc_id,
            kind="slack_channel",
            target_chat_id="C-EOR",
        )
        await db.commit()

    upload_calls: list[dict] = []

    async def fake_upload_file(**kwargs):
        upload_calls.append(kwargs)
        return {"ok": True, "file_id": "F", "permalink": "p"}

    adapter = MagicMock(
        spec_set=["channel_type", "upload_file", "send_approval_card"]
    )
    adapter.channel_type = "slack"
    adapter.upload_file = AsyncMock(side_effect=fake_upload_file)
    adapter.send_approval_card = AsyncMock(
        return_value={"ok": True, "ts": "1700000000.000300", "channel": "C-EOR"}
    )

    runner = _make_runner(session_maker, {str(cc_id): adapter})

    envelope = {
        "kind": "approval_card",
        "config_id": str(cc_id),
        "session_key": "",
        "task_id": "",
        "body": json.dumps(
            {
                "input_id": str(approval_id),
                "automation_id": "",
                "tool_name": "publish",
                "summary": "x",
                "actions": ["allow_once"],
                "destination_ids": [str(dest_id)],
            }
        ),
        # Envelope adds art_envelope; the row already has art_row.
        # Both must be uploaded; neither must be deduped to zero.
        "artifact_refs": [str(art_envelope)],
    }

    await runner._process_approval_card_delivery(envelope)

    filenames = {c["filename"] for c in upload_calls}
    assert filenames == {"from-envelope.txt", "from-row.txt"}, (
        f"expected union of envelope+row artifacts, got {filenames}"
    )
