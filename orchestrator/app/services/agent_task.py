"""
Agent Task Payload

Serializable payload for dispatching agent tasks to the ARQ worker fleet.
Contains all context needed to reconstruct and run an agent on a worker pod.
"""

import json
import logging
from dataclasses import asdict, dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class AgentTaskPayload:
    """
    Serializable payload for agent task dispatch via ARQ.

    Contains everything a worker needs to:
    1. Load the correct agent from DB
    2. Build the execution context
    3. Run agent.run() with full tool access
    4. Save the result to DB
    """

    # Task identification
    task_id: str  # Unique ID for this execution (used for Redis Pub/Sub channel)

    # User context
    user_id: str  # UUID string
    chat_id: str  # UUID string
    message: str  # User's message
    project_id: str = ""  # UUID string — empty for standalone chats
    project_slug: str = ""
    team_id: str = ""  # UUID string — empty for user-scope/standalone chats

    # Agent configuration
    agent_id: str | None = None  # MarketplaceAgent ID (None = default agent)
    model_name: str = ""

    # Execution context
    edit_mode: str | None = None
    view_context: dict | None = None
    container_id: str | None = None  # UUID string
    container_name: str | None = None
    container_directory: str | None = None

    # History and project info
    chat_history: list[dict] = field(default_factory=list)
    project_context: dict = field(default_factory=dict)

    # External invocation
    webhook_callback_url: str | None = None  # POST result to this URL on completion

    # Channel context (for messaging channel-triggered tasks)
    channel_config_id: str | None = None  # ChannelConfig UUID
    channel_jid: str | None = None  # Canonical address (e.g., "telegram:123456")
    channel_type: str | None = None  # "telegram", "slack", "discord", "whatsapp"

    # Attachments (images, pasted text, file references)
    attachments: list[dict] = field(default_factory=list)

    # API key scope restrictions (None = no restriction, list = only these scopes allowed)
    api_key_scopes: list[str] | None = None

    # Gateway routing (Communication Protocol v2)
    gateway_deliver: str | None = None  # "origin", "telegram", "discord:channel_id", etc.
    session_key: str | None = None  # Per-platform session key
    schedule_id: str | None = None  # AgentSchedule UUID if triggered by cron

    # Desktop multi-agent ticket tracking (None = not ticket-bound)
    agent_task_id: str | None = None  # AgentTask UUID; worker atomically claims it on pickup

    def to_dict(self) -> dict:
        """Serialize to dict for ARQ job dispatch."""
        return asdict(self)

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict) -> "AgentTaskPayload":
        """Deserialize from dict."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_json(cls, json_str: str) -> "AgentTaskPayload":
        """Deserialize from JSON string."""
        return cls.from_dict(json.loads(json_str))
