# Channel & MCP Models

This document covers the models that power Tesslate Studio's messaging channel integrations (Telegram, Slack, Discord, WhatsApp) and the Model Context Protocol (MCP) server system for extending agent capabilities.

**File**: `orchestrator/app/models.py`

## ChannelConfig Model

ChannelConfig stores the configuration for external messaging channels that users connect to their projects. Each channel links to a default agent that handles incoming messages.

### Schema

```python
class ChannelConfig(Base):
    __tablename__ = "channel_configs"

    # Identity
    id: UUID
    user_id: UUID               # Foreign key to User
    project_id: UUID            # Foreign key to Project (nullable)

    # Channel configuration
    channel_type: str           # telegram, slack, discord, whatsapp (max 20 chars)
    name: str                   # Display name (max 100 chars)
    credentials: str            # Fernet-encrypted JSON (bot tokens, API keys, etc.)
    webhook_secret: str         # Random secret for URL signing (64 chars)

    # Default agent for this channel
    default_agent_id: UUID      # Foreign key to MarketplaceAgent (nullable)

    # Status
    is_active: bool             # Is channel enabled?

    # Timestamps
    created_at: datetime
    updated_at: datetime
```

### Key Relationships

```python
user = relationship("User", backref="channel_configs")
project = relationship("Project", backref="channel_configs")
default_agent = relationship("MarketplaceAgent", foreign_keys=[default_agent_id])
```

### Common Queries

**Get user's channel configurations**:
```python
result = await db.execute(
    select(ChannelConfig)
    .where(ChannelConfig.user_id == user.id)
    .where(ChannelConfig.is_active == True)
)
channels = result.scalars().all()
```

**Get channels for a project**:
```python
result = await db.execute(
    select(ChannelConfig)
    .where(ChannelConfig.project_id == project.id)
    .where(ChannelConfig.is_active == True)
)
channels = result.scalars().all()
```

**Create a Telegram channel**:
```python
channel = ChannelConfig(
    user_id=user.id,
    project_id=project.id,
    channel_type="telegram",
    name="My Telegram Bot",
    credentials=encrypt_json({"bot_token": "123456:ABC-DEF..."}),
    webhook_secret=secrets.token_hex(32),
    default_agent_id=agent.id,
    is_active=True
)
db.add(channel)
await db.commit()
```

### Notes

- Credentials are Fernet-encrypted at rest; the JSON structure varies by channel type
- The `webhook_secret` is used to validate incoming webhook requests from messaging platforms
- A channel can optionally be scoped to a specific project via `project_id`
- The `default_agent_id` determines which agent processes incoming messages on this channel

---

## ChannelMessage Model

ChannelMessage provides an audit log of all messages sent and received through messaging channels.

### Schema

```python
class ChannelMessage(Base):
    __tablename__ = "channel_messages"

    # Identity
    id: UUID
    channel_config_id: UUID     # Foreign key to ChannelConfig

    # Message details
    direction: str              # "inbound" or "outbound" (max 10 chars)
    jid: str                    # Canonical address / chat identifier (max 255 chars)
    sender_name: str            # For swarm: which agent identity sent (nullable, max 100 chars)
    content: str                # Message text content
    platform_message_id: str    # Platform-specific message ID (nullable, max 255 chars)
    task_id: str                # Associated agent task ID (nullable)
    status: str                 # delivered, failed, pending (max 20 chars, default: "delivered")

    # Timestamps
    created_at: datetime        # Indexed for efficient time-range queries
```

### Key Relationships

```python
channel_config = relationship("ChannelConfig", backref="messages")
```

### Common Queries

**Get message history for a channel**:
```python
result = await db.execute(
    select(ChannelMessage)
    .where(ChannelMessage.channel_config_id == channel_id)
    .order_by(ChannelMessage.created_at.desc())
    .limit(50)
)
messages = result.scalars().all()
```

**Log an inbound message**:
```python
msg = ChannelMessage(
    channel_config_id=channel.id,
    direction="inbound",
    jid="user123@telegram",
    content="Build me a landing page",
    platform_message_id="msg_abc123",
    status="delivered"
)
db.add(msg)
await db.commit()
```

**Log an outbound agent response**:
```python
msg = ChannelMessage(
    channel_config_id=channel.id,
    direction="outbound",
    jid="user123@telegram",
    sender_name="Tesslate Agent",
    content="I've created the landing page...",
    task_id=task_id,
    status="delivered"
)
db.add(msg)
await db.commit()
```

### Notes

- The `jid` field stores a canonical address (e.g., Telegram chat ID, Slack channel ID)
- The `sender_name` field supports agent swarm scenarios where multiple agent identities may respond
- The `task_id` links outbound messages back to the agent task that generated them
- The `created_at` column is indexed for efficient time-range queries on message history

---

## UserMcpConfig Model

UserMcpConfig tracks per-user MCP (Model Context Protocol) server installations from the marketplace. MCP servers extend agent capabilities by providing additional tools, resources, and prompts.

### Schema

```python
class UserMcpConfig(Base):
    __tablename__ = "user_mcp_configs"

    # Identity
    id: UUID
    user_id: UUID               # Foreign key to User
    marketplace_agent_id: UUID  # Foreign key to MarketplaceAgent (item_type='mcp_server')

    # Configuration
    credentials: str            # Fernet-encrypted JSON (API keys, tokens) — nullable
    enabled_capabilities: JSON  # List of enabled capabilities (default: ["tools", "resources", "prompts"])
    is_active: bool             # Is this MCP server enabled?

    # Timestamps
    created_at: datetime
    updated_at: datetime
```

### Key Relationships

```python
user = relationship("User", backref="mcp_configs")
marketplace_agent = relationship("MarketplaceAgent", backref="mcp_installs")
```

### Common Queries

**Get user's installed MCP servers**:
```python
result = await db.execute(
    select(UserMcpConfig)
    .options(selectinload(UserMcpConfig.marketplace_agent))
    .where(UserMcpConfig.user_id == user.id)
    .where(UserMcpConfig.is_active == True)
)
mcp_configs = result.scalars().all()
```

**Install an MCP server for a user**:
```python
config = UserMcpConfig(
    user_id=user.id,
    marketplace_agent_id=mcp_agent.id,
    credentials=encrypt_json({"api_key": "sk-..."}),
    enabled_capabilities=["tools", "resources"],
    is_active=True
)
db.add(config)
await db.commit()
```

**Disable an MCP server**:
```python
config.is_active = False
await db.commit()
```

### Notes

- MCP servers are stored as MarketplaceAgent rows in the marketplace (with appropriate `item_type`)
- Credentials are Fernet-encrypted at rest; the JSON structure varies by MCP server
- The `enabled_capabilities` field lets users selectively enable tools, resources, or prompts from an MCP server
- Users can install the same MCP server with different credentials (e.g., different API keys for dev/prod)

---

## AgentMcpAssignment Model

AgentMcpAssignment tracks which MCP servers are attached to which agents, per user. This is a three-way junction table enabling users to give specific agents access to specific MCP servers.

### Schema

```python
class AgentMcpAssignment(Base):
    __tablename__ = "agent_mcp_assignments"

    # Identity
    id: UUID
    agent_id: UUID              # Foreign key to MarketplaceAgent (the agent)
    mcp_config_id: UUID         # Foreign key to UserMcpConfig
    user_id: UUID               # Foreign key to User

    # Status
    enabled: bool               # Is this MCP server active on the agent?
    added_at: datetime          # When the MCP server was attached

    # Unique constraint: (agent_id, mcp_config_id, user_id)
```

### Key Relationships

```python
agent = relationship("MarketplaceAgent", foreign_keys=[agent_id])
mcp_config = relationship("UserMcpConfig")
user = relationship("User")
```

### Common Queries

**Get MCP servers attached to an agent for a user**:
```python
result = await db.execute(
    select(UserMcpConfig)
    .join(AgentMcpAssignment, AgentMcpAssignment.mcp_config_id == UserMcpConfig.id)
    .where(AgentMcpAssignment.agent_id == agent_id)
    .where(AgentMcpAssignment.user_id == user.id)
    .where(AgentMcpAssignment.enabled == True)
)
mcp_configs = result.scalars().all()
```

**Attach an MCP server to an agent**:
```python
assignment = AgentMcpAssignment(
    agent_id=agent.id,
    mcp_config_id=mcp_config.id,
    user_id=user.id,
    enabled=True
)
db.add(assignment)
await db.commit()
```

**Detach an MCP server from an agent**:
```python
await db.execute(
    delete(AgentMcpAssignment)
    .where(AgentMcpAssignment.agent_id == agent_id)
    .where(AgentMcpAssignment.mcp_config_id == mcp_config_id)
    .where(AgentMcpAssignment.user_id == user_id)
)
await db.commit()
```

### Notes

- The unique constraint on `(agent_id, mcp_config_id, user_id)` prevents duplicate attachments
- CASCADE deletes: removing the agent, MCP config, or user automatically cleans up assignments
- This model mirrors the structure of `AgentSkillAssignment` for consistency

---

## Summary

The channel and MCP models enable two key extensibility systems:

**Channels** allow users to connect external messaging platforms to Tesslate:
- **ChannelConfig** stores encrypted credentials and routing configuration per platform
- **ChannelMessage** provides a full audit trail of inbound and outbound messages
- Supported platforms: Telegram, Slack, Discord, WhatsApp

**MCP Servers** extend agent capabilities with external tool providers:
- **UserMcpConfig** tracks per-user MCP server installations with encrypted credentials
- **AgentMcpAssignment** links specific MCP servers to specific agents per user
- Capabilities can be selectively enabled (tools, resources, prompts)

Both systems follow the established patterns of encrypted credential storage (Fernet) and per-user junction tables for flexible assignment.
