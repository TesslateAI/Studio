"""Pure-functional builders for approval-card payloads (Phase 4).

These helpers exist as a separate module so the unit tests don't have to
construct full Slack/Telegram/Discord adapter fakes — they just call
``build_slack_blocks(...)`` and assert on the JSON shape.

The ``action_id`` / ``callback_data`` shape is the load-bearing contract:

  * Slack ``action_id``     — ``"automation_approve:<input_id>:<choice>"``
  * Telegram ``callback_data`` — ``"approve:<input_id>:<choice>"``
  * Discord ``custom_id``    — ``"approve:<input_id>:<choice>"``

The inbound discriminator on each adapter checks the *prefix* and routes
the payload directly to ``/api/chat/approval/{input_id}/respond`` —
button clicks NEVER enter ``_pending_messages`` (the chat-session queue).
That guarantee is the whole point of using a recognizable prefix.

``choice`` is one of: ``allow_once`` · ``allow_for_run`` ·
``allow_permanently`` · ``deny`` (matching the worked-example list in
``ultrathink-i-want-to-glittery-pond.md`` §"HITL via gateway").
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "SLACK_ACTION_PREFIX",
    "TELEGRAM_CALLBACK_PREFIX",
    "DISCORD_CUSTOM_ID_PREFIX",
    "DEFAULT_ACTIONS",
    "ACTION_LABELS",
    "build_slack_blocks",
    "build_telegram_inline_keyboard",
    "build_discord_components",
    "parse_action_id",
]


# Prefix constants — keep these in sync with the inbound discriminator
# checks in slack.py / telegram.py / discord_bot.py.
SLACK_ACTION_PREFIX = "automation_approve:"
TELEGRAM_CALLBACK_PREFIX = "approve:"
DISCORD_CUSTOM_ID_PREFIX = "approve:"


DEFAULT_ACTIONS: tuple[str, ...] = (
    "allow_once",
    "allow_for_run",
    "allow_permanently",
    "deny",
)

ACTION_LABELS: dict[str, str] = {
    "allow_once": "Allow Once",
    "allow_for_run": "Allow For Run",
    "allow_permanently": "Allow Permanently",
    "deny": "Deny",
    # Legacy approval responses (kept for backward compat with
    # PendingUserInputManager which already knows about these).
    "allow_all": "Allow All",
    "stop": "Stop",
}

# Slack button styles — green for the safe "once" path, red for deny.
_SLACK_STYLE_BY_CHOICE: dict[str, str] = {
    "allow_once": "primary",
    "allow_for_run": "primary",
    "allow_permanently": "primary",
    "deny": "danger",
    "allow_all": "primary",
    "stop": "danger",
}


def _label(choice: str) -> str:
    return ACTION_LABELS.get(choice, choice.replace("_", " ").title())


# ---------------------------------------------------------------------------
# Slack — block_actions
# ---------------------------------------------------------------------------


def build_slack_blocks(
    *,
    input_id: str,
    automation_id: str,
    tool_name: str,
    summary: str,
    actions: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Build a Slack ``blocks`` payload for an approval card.

    The returned list is ready to drop into ``chat.postMessage``:

        client.chat_postMessage(channel=..., blocks=build_slack_blocks(...))

    Each button's ``action_id`` is
    ``"automation_approve:<input_id>:<choice>"`` so the inbound
    discriminator can route the click without touching the chat session
    queue.
    """
    actions_list = list(actions) if actions else list(DEFAULT_ACTIONS)
    summary_text = (summary or "").strip() or f"Approval needed for `{tool_name}`"

    block_action_id_for = lambda choice: (  # noqa: E731
        f"{SLACK_ACTION_PREFIX}{input_id}:{choice}"
    )

    elements: list[dict[str, Any]] = []
    for choice in actions_list:
        button: dict[str, Any] = {
            "type": "button",
            "text": {"type": "plain_text", "text": _label(choice), "emoji": False},
            "action_id": block_action_id_for(choice),
            "value": choice,
        }
        style = _SLACK_STYLE_BY_CHOICE.get(choice)
        if style:
            button["style"] = style
        elements.append(button)

    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Tesslate approval needed*\n*Tool:* `{tool_name}`",
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": summary_text[:2900]},
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"automation `{automation_id}` · "
                        f"input `{input_id}`"
                    ),
                }
            ],
        },
        {"type": "actions", "elements": elements},
    ]


# ---------------------------------------------------------------------------
# Telegram — inline_keyboard
# ---------------------------------------------------------------------------


def build_telegram_inline_keyboard(
    *,
    input_id: str,
    actions: list[str] | tuple[str, ...] | None = None,
    columns: int = 2,
) -> list[list[dict[str, Any]]]:
    """Build a Telegram ``reply_markup.inline_keyboard`` 2D array.

    Each button's ``callback_data`` is ``"approve:<input_id>:<choice>"``
    (Telegram caps callback_data at 64 bytes — a UUID + short choice
    fits comfortably).
    """
    actions_list = list(actions) if actions else list(DEFAULT_ACTIONS)
    rows: list[list[dict[str, Any]]] = []
    cur: list[dict[str, Any]] = []
    for choice in actions_list:
        cb = f"{TELEGRAM_CALLBACK_PREFIX}{input_id}:{choice}"
        # Hard guard against the 64-byte callback_data limit.
        if len(cb.encode("utf-8")) > 64:
            # Truncate the choice if needed — input_id (UUID = 36) +
            # prefix (8) leaves 20 bytes for choice. All current choices
            # fit; this is defensive for future extensions.
            cb = cb[:64]
        cur.append({"text": _label(choice), "callback_data": cb})
        if len(cur) >= columns:
            rows.append(cur)
            cur = []
    if cur:
        rows.append(cur)
    return rows


# ---------------------------------------------------------------------------
# Discord — components (buttons in a View)
# ---------------------------------------------------------------------------


# Discord ButtonStyle enum integer values:
#   1 = primary (blurple), 2 = secondary (grey), 3 = success (green),
#   4 = danger (red), 5 = link.
_DISCORD_STYLE_BY_CHOICE: dict[str, int] = {
    "allow_once": 3,         # success
    "allow_for_run": 1,      # primary
    "allow_permanently": 1,  # primary
    "deny": 4,               # danger
    "allow_all": 1,
    "stop": 4,
}


def build_discord_components(
    *,
    input_id: str,
    actions: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Build a Discord ``components`` payload (action-row of buttons).

    The shape matches Discord's REST API: ``components: [{type:1, components:[{type:2, ...}, ...]}]``.
    Each button's ``custom_id`` is ``"approve:<input_id>:<choice>"``.
    """
    actions_list = list(actions) if actions else list(DEFAULT_ACTIONS)
    buttons: list[dict[str, Any]] = []
    for choice in actions_list:
        buttons.append(
            {
                "type": 2,  # button
                "style": _DISCORD_STYLE_BY_CHOICE.get(choice, 2),
                "label": _label(choice),
                "custom_id": f"{DISCORD_CUSTOM_ID_PREFIX}{input_id}:{choice}",
            }
        )
    return [{"type": 1, "components": buttons}]


# ---------------------------------------------------------------------------
# Inbound discriminator helper
# ---------------------------------------------------------------------------


def parse_action_id(
    action_id: str,
) -> tuple[str | None, str | None]:
    """Parse ``approve:<input_id>:<choice>`` (Telegram/Discord) or
    ``automation_approve:<input_id>:<choice>`` (Slack) into
    ``(input_id, choice)``.

    Returns ``(None, None)`` if the prefix doesn't match — the caller
    treats ``(None, None)`` as "this is NOT an approval click; route it
    through the normal chat path."
    """
    if not action_id:
        return None, None
    raw = action_id.strip()
    if raw.startswith(SLACK_ACTION_PREFIX):
        body = raw[len(SLACK_ACTION_PREFIX):]
    elif raw.startswith(TELEGRAM_CALLBACK_PREFIX):
        body = raw[len(TELEGRAM_CALLBACK_PREFIX):]
    else:
        return None, None
    # Body is ``<input_id>:<choice>``; input_id is a UUID so we split on
    # the LAST colon to be tolerant of future-format choices that contain
    # punctuation. (Today they don't.)
    if ":" not in body:
        return None, None
    input_id, _, choice = body.rpartition(":")
    if not input_id or not choice:
        return None, None
    return input_id, choice
