"""
Send Message Tool

Allows agents to proactively send messages to users via configured channels:
- chat: Appears as an agent event in the chat stream (default)
- discord: Sends via Discord webhook (if configured)
- webhook: Posts to external webhook URL (if external agent API invocation)
"""

import logging
from datetime import UTC, datetime
from typing import Any

from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)


async def send_message_executor(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """
    Send a message to the user via configured notification channel.

    Args:
        params: {
            message: str,  # Message content (required)
            channel: str,  # Channel: 'discord', 'webhook', or 'chat' (default: 'chat')
        }
        context: Execution context with webhook_callback_url, etc.

    Returns:
        Dict with delivery status
    """
    message = params.get("message")
    channel = params.get("channel", "chat")

    if not message:
        raise ValueError("message parameter is required")

    if not message.strip():
        return error_output(
            message="Message content cannot be empty",
            suggestion="Provide a meaningful message to send",
        )

    if channel not in ("chat", "discord", "webhook"):
        return error_output(
            message=f"Invalid channel '{channel}'",
            suggestion="Use 'chat', 'discord', or 'webhook'",
        )

    if channel == "chat":
        # Chat channel: message appears in the agent's response stream
        # The message content is returned as part of the tool result,
        # which the agent will include in its response
        return success_output(
            message=f"Message sent to chat",
            notification=message,
            channel="chat",
        )

    elif channel == "discord":
        try:
            from ....config import get_settings

            settings = get_settings()
            webhook_url = settings.agent_discord_webhook_url

            if not webhook_url:
                return error_output(
                    message="Discord webhook not configured",
                    suggestion="Set AGENT_DISCORD_WEBHOOK_URL in environment to enable Discord notifications",
                )

            from ....services.discord_service import DiscordWebhookService

            discord = DiscordWebhookService(webhook_url=webhook_url)
            embed = {
                "title": "Agent Notification",
                "description": message[:4000],  # Discord embed limit
                "color": 0x7C3AED,  # Purple (Tesslate brand)
                "timestamp": datetime.now(UTC).isoformat(),
                "footer": {"text": "Tesslate Agent"},
            }
            await discord._send_webhook(embeds=[embed])

            return success_output(
                message="Message sent to Discord",
                channel="discord",
            )

        except Exception as e:
            logger.error(f"Failed to send Discord message: {e}")
            return error_output(
                message=f"Failed to send Discord message: {str(e)}",
                suggestion="Check Discord webhook configuration",
            )

    elif channel == "webhook":
        webhook_url = context.get("webhook_callback_url")
        if not webhook_url:
            return error_output(
                message="No webhook URL configured for this session",
                suggestion="This channel is only available for external agent API invocations with a webhook_callback_url",
            )

        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    webhook_url,
                    json={
                        "type": "agent_notification",
                        "message": message,
                        "task_id": context.get("task_id"),
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                )
                response.raise_for_status()

            return success_output(
                message="Message sent to webhook",
                channel="webhook",
            )

        except Exception as e:
            logger.error(f"Failed to send webhook message: {e}")
            return error_output(
                message=f"Failed to send webhook message: {str(e)}",
                suggestion="Check webhook URL and ensure it's accessible",
            )

    return error_output(message="Unexpected channel state")


def register_send_message_tools(registry):
    """Register send_message tool."""

    registry.register(
        Tool(
            name="send_message",
            description="Send a message to the user via configured notification channel (Discord webhook, external webhook, or in-chat). Use to proactively notify the user of important findings, task completion, or alerts.",
            parameters={
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Message content to send to the user",
                    },
                    "channel": {
                        "type": "string",
                        "description": "Notification channel: 'chat' (default, appears in chat), 'discord' (webhook), or 'webhook' (external callback URL)",
                        "default": "chat",
                        "enum": ["chat", "discord", "webhook"],
                    },
                },
                "required": ["message"],
            },
            executor=send_message_executor,
            category=ToolCategory.WEB,
            examples=[
                '{"tool_name": "send_message", "parameters": {"message": "Build completed successfully! The app is ready at port 3000."}}',
                '{"tool_name": "send_message", "parameters": {"message": "Found 3 critical security vulnerabilities in dependencies.", "channel": "discord"}}',
            ],
        )
    )

    logger.info("Registered 1 send_message tool")
