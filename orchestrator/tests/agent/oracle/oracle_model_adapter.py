"""
Oracle Model Adapter

Replays scripted LLM responses for deterministic agent testing.
Each scenario specifies the exact sequence of model responses the agent should receive.
"""

import json
import logging
from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)


class OracleModelAdapter:
    """
    Mock model adapter that replays scripted responses from an oracle scenario.

    Each turn in the scenario has:
    - thought: Optional thinking text
    - tool_calls: List of {name, parameters} the model "decides" to call
    - response_text: Final text response (for last turn or between tool calls)

    The adapter yields events in the same format as the real model adapters:
    - text_delta events for streaming text
    - tool_calls_delta/tool_calls_complete for tool invocations
    - done when the turn is complete
    """

    def __init__(self, scenario: dict):
        self.scenario = scenario
        self.turns = scenario.get("turns", [])
        self.turn_index = 0
        self.model_name = scenario.get("model_name", "oracle/test")

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs,
    ) -> AsyncGenerator[dict, None]:
        """
        Yield events for the current turn in the scenario.

        Matches the interface used by the agent's run loop.
        """
        if self.turn_index >= len(self.turns):
            # No more turns - yield a simple done
            yield {"type": "text_delta", "content": "Oracle scenario complete."}
            yield {"type": "done", "finish_reason": "stop"}
            return

        turn = self.turns[self.turn_index]
        self.turn_index += 1

        # Yield thought/thinking if present
        thought = turn.get("thought", "")
        if thought:
            yield {"type": "thinking_delta", "content": thought}

        # Yield tool calls if present
        tool_calls = turn.get("tool_calls", [])
        if tool_calls:
            for i, tc in enumerate(tool_calls):
                yield {
                    "type": "tool_calls_delta",
                    "index": i,
                    "tool_call": {
                        "id": f"oracle_call_{self.turn_index}_{i}",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc.get("parameters", {})),
                        },
                    },
                }
            yield {"type": "tool_calls_complete"}
            yield {"type": "done", "finish_reason": "tool_calls"}
        else:
            # Text response
            response_text = turn.get("response_text", "")
            if response_text:
                yield {"type": "text_delta", "content": response_text}
            yield {"type": "done", "finish_reason": "stop"}

    def get_model_name(self) -> str:
        return self.model_name
