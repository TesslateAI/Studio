"""
Agent Task Payload

Serializable payload for dispatching agent tasks to the ARQ worker fleet.
Contains all context needed to reconstruct and run an agent on a worker pod.
"""

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any

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
    project_id: str  # UUID string
    project_slug: str
    chat_id: str  # UUID string
    message: str  # User's message

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
