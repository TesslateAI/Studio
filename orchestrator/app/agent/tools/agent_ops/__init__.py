"""Multi-agent delegation tools (configured marketplace agents).

Currently exports the ``call_agent`` tool used by the @-mention picker:
when a user types ``@coworker-agent`` in chat, the calling agent gets a
``call_agent`` entry in its registry that runs the named **configured
marketplace agent** stateless and returns its output.

This is the multi-agent layer. It is distinct from the in-process
subagent tools (``task`` / ``wait_agent`` / ``send_message_to_agent`` /
``close_agent`` / ``list_agents``) that live in
``packages/tesslate-agent/.../delegation_ops/``: those let an agent
provision ephemeral specialist children with prompts it crafts inline,
run in-process, and never touch the DB. The two layers compose — a
delegated agent invoked via ``call_agent`` keeps full access to the
``task`` tool family.

Multi-agent cap: ``call_agent`` is only registered when
``payload.mention_agent_ids`` is non-empty, so plain chats see zero
added tokens. Delegated runs are dispatched with
``mention_agent_ids=[]``, which structurally prevents multi-agent
ping-pong (the delegated agent never gets ``call_agent`` in its
registry). The in-process ``task`` family remains available — that's
a different layer.
"""

from .call_agent import register_call_agent_tool

__all__ = ["register_call_agent_tool"]
