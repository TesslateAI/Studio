"""
Send Message Tool

Allows agents to proactively send messages to users via configured channels:
- chat: Appears as an agent event in the chat stream (default)
- discord: Sends via Discord webhook (if configured)
- webhook: Posts to external webhook URL (if external agent API invocation)
- reply: Responds via the originating messaging channel (Telegram, Slack, etc.)
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

    if not channel.startswith("platform:") and channel not in (
        "chat",
        "discord",
        "webhook",
        "reply",
    ):
        return error_output(
            message=f"Invalid channel '{channel}'",
            suggestion="Use 'chat', 'discord', 'webhook', 'reply', or 'platform:<type>:<chat_id>'",
        )

    if channel == "chat":
        # Chat channel: message appears in the agent's response stream
        # The message content is returned as part of the tool result,
        # which the agent will include in its response
        return success_output(
            message="Message sent to chat",
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

    elif channel == "reply":
        # Reply channel: respond via the originating messaging channel
        channel_config_id = context.get("channel_config_id")
        channel_jid = context.get("channel_jid")
        channel_type = context.get("channel_type")

        if not channel_config_id or not channel_jid or not channel_type:
            return error_output(
                message="Reply channel is only available for channel-triggered tasks",
                suggestion="Use 'chat' channel instead, or invoke this agent via a messaging channel (Telegram, Slack, etc.)",
            )

        try:
            from ....services.channels.registry import decrypt_credentials, get_channel

            # Load the ChannelConfig from DB to get encrypted credentials
            db = context.get("db")
            if not db:
                return error_output(
                    message="Database session not available in execution context",
                    suggestion="This is an internal error — please report it",
                )

            from sqlalchemy import select

            from ....models import ChannelConfig

            result = await db.execute(
                select(ChannelConfig).where(ChannelConfig.id == channel_config_id)
            )
            config = result.scalar_one_or_none()
            if not config:
                return error_output(
                    message=f"Channel config '{channel_config_id}' not found",
                    suggestion="The channel configuration may have been deleted",
                )

            credentials = decrypt_credentials(config.credentials)
            channel_instance = get_channel(channel_type, credentials)

            sender = params.get("sender")
            await channel_instance.send_message(
                jid=channel_jid,
                text=message,
                sender=sender,
            )

            return success_output(
                message=f"Message sent to {channel_type} channel",
                channel="reply",
                channel_type=channel_type,
            )

        except Exception as e:
            logger.error(f"Failed to send reply message via {channel_type}: {e}")
            return error_output(
                message=f"Failed to send reply message via {channel_type}: {str(e)}",
                suggestion="Check channel configuration and credentials",
            )

    if channel.startswith("platform:"):
        # Platform channel: "platform:telegram:123456" → send via ChannelConfig
        parts = channel.split(":", 2)
        if len(parts) < 3:
            return error_output(
                message=f"Invalid platform channel format '{channel}'",
                suggestion="Use 'platform:<type>:<chat_id>' (e.g., 'platform:telegram:123456')",
            )

        platform_type = parts[1]
        target_chat_id = parts[2]

        try:
            db = context.get("db")
            if not db:
                return error_output(message="Database session not available")

            from sqlalchemy import select

            from ....models import ChannelConfig
            from ....services.channels.registry import decrypt_credentials, get_channel

            user_id = context.get("user_id")
            result = await db.execute(
                select(ChannelConfig)
                .where(
                    ChannelConfig.user_id == user_id,
                    ChannelConfig.channel_type == platform_type,
                    ChannelConfig.is_active.is_(True),
                )
                .limit(1)
            )
            config = result.scalar_one_or_none()
            if not config:
                return error_output(
                    message=f"No active {platform_type} channel configured",
                    suggestion=f"Set up a {platform_type} channel in Settings → Channels",
                )

            credentials = decrypt_credentials(config.credentials)
            channel_instance = get_channel(platform_type, credentials)
            await channel_instance.send_message(
                jid=f"{platform_type}:{target_chat_id}",
                text=message,
            )

            return success_output(
                message=f"Message sent to {platform_type}:{target_chat_id}",
                channel="platform",
                platform=platform_type,
            )

        except Exception as e:
            logger.error("Failed to send platform message: %s", e)
            return error_output(
                message=f"Failed to send to {platform_type}: {str(e)}",
                suggestion="Check channel configuration and chat ID",
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
                        "description": "Notification channel: 'chat' (default), 'discord' (webhook), 'webhook' (external callback), 'reply' (originating channel), or 'platform:<type>:<chat_id>' (e.g., 'platform:telegram:123456')",
                        "default": "chat",
                    },
                    "sender": {
                        "type": "string",
                        "description": "Optional sender identity for pool/swarm messages (only used with 'reply' channel)",
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
