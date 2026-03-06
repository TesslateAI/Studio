"""
Generate complete tool information output to a text file.
This script creates an IterativeAgent and outputs the complete _get_tool_info() result.
"""

import sys
import os
from pathlib import Path

# Add orchestrator to path
sys.path.insert(0, str(Path(__file__).parent))

from app.agent.iterative_agent import IterativeAgent
from app.agent.tools import get_tool_registry


def main():
    """Generate tool info and save to file."""

    # Create agent with all registered tools
    tools = get_tool_registry()
    agent = IterativeAgent(
        system_prompt="Test agent",
        tools=tools,
        max_iterations=10
    )

    # Get complete tool info
    tool_info = agent._get_tool_info()

    # Save to file
    output_file = Path(__file__).parent / "tool_info_output.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("=" * 80 + "\n")
        f.write("COMPLETE TOOL INFORMATION OUTPUT\n")
        f.write("=" * 80 + "\n\n")
        f.write(tool_info)
        f.write("\n\n" + "=" * 80 + "\n")
        f.write(f"Total tools registered: {len(tools._tools)}\n")
        f.write("=" * 80 + "\n")

    print(f"[OK] Tool information written to: {output_file}")
    print(f"[OK] Total tools registered: {len(tools._tools)}")
    print(f"[OK] Output length: {len(tool_info)} characters")

    # Also print tool list
    print("\nRegistered tools:")
    for i, tool_name in enumerate(sorted(tools._tools.keys()), 1):
        print(f"  {i}. {tool_name}")


if __name__ == "__main__":
    main()
