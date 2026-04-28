"""Unit tests for the slash-command / mention parser."""

from __future__ import annotations

import pytest

from app.services.gateway.triggers.common import (
    parse_bot_mention,
    parse_slash_command,
)


# ---------------------------------------------------------------------------
# Slash command parser
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected_name,expected_args",
    [
        # Slack — slash command stripped server-side leaves "run <name> ..."
        ("run standup", "standup", []),
        ("run standup arg1 arg2", "standup", ["arg1", "arg2"]),
        # User typed the full command (Telegram-style).
        ("/automation_run standup", "standup", []),
        ("/automation_run standup arg1", "standup", ["arg1"]),
        # Discord-style: slash command with subcommand "run".
        ("/automation run standup", "standup", []),
        # Stray whitespace.
        ("  run   standup   ", "standup", []),
    ],
)
def test_parse_slash_command_recognized(raw, expected_name, expected_args):
    parsed = parse_slash_command(raw)
    assert parsed.kind == "automation"
    assert parsed.name == expected_name
    assert parsed.args == expected_args


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "/automation",       # missing run + name
        "run",                # missing name
        "run !!!bad-name!!!",  # invalid characters
    ],
)
def test_parse_slash_command_unknown(raw):
    parsed = parse_slash_command(raw)
    assert parsed.kind == "unknown"


# ---------------------------------------------------------------------------
# Bot-mention parser
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected_alias,expected_name,expected_args",
    [
        # Slack — bot mention encoded as <@UBOT>.
        ("<@U123ABC> summarize_commits foo bar", "U123ABC", "summarize_commits",
         ["foo", "bar"]),
        # Telegram — @botname.
        ("@github_app summarize_commits tesslate/studio yesterday", "github_app",
         "summarize_commits", ["tesslate/studio", "yesterday"]),
    ],
)
def test_parse_bot_mention_recognized(raw, expected_alias, expected_name, expected_args):
    parsed = parse_bot_mention(raw)
    assert parsed.kind == "app_action"
    assert parsed.app_alias == expected_alias
    assert parsed.name == expected_name
    assert parsed.args == expected_args


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "no leading mention",
        "<@U123>",       # has alias but no action name
        "@bot",          # alias only
        "@bot !!!bad",  # invalid action name
    ],
)
def test_parse_bot_mention_unknown(raw):
    parsed = parse_bot_mention(raw)
    assert parsed.kind == "unknown"
