"""
End-to-end tests for complete agent workflows.

Tests realistic scenarios like:
- Creating a new component from scratch
- Modifying existing files
- Multi-step workflows with multiple tool calls
- Error recovery
"""

import pytest
from unittest.mock import AsyncMock, Mock
from app.agent.iterative_agent import IterativeAgent
from app.agent.stream_agent import StreamAgent
from app.agent.tools.registry import ToolRegistry, Tool, ToolCategory
from app.agent.models import ModelAdapter


@pytest.mark.e2e
@pytest.mark.slow
class TestAgentE2EWorkflows:
    """End-to-end workflow tests for agents."""

    @pytest.fixture
    def full_tool_registry(self):
        """Create a registry with common file operation tools."""
        registry = ToolRegistry()

        # Mock file storage
        file_storage = {}

        async def read_file_tool(params, context):
            file_path = params['file_path']
            if file_path in file_storage:
                return {
                    "message": f"Read file {file_path}",
                    "content": file_storage[file_path],
                    "file_path": file_path
                }
            return {
                "message": f"File {file_path} does not exist",
                "exists": False
            }

        async def write_file_tool(params, context):
            file_path = params['file_path']
            content = params['content']
            file_storage[file_path] = content
            return {
                "message": f"Wrote to {file_path}",
                "file_path": file_path,
                "preview": content[:100]
            }

        async def list_files_tool(params, context):
            return {
                "message": "Listed files",
                "files": list(file_storage.keys())
            }

        registry.register(Tool(
            name="read_file",
            description="Read a file",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"}
                },
                "required": ["file_path"]
            },
            executor=read_file_tool,
            category=ToolCategory.FILE_OPS
        ))

        registry.register(Tool(
            name="write_file",
            description="Write a file",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "content": {"type": "string"}
                },
                "required": ["file_path", "content"]
            },
            executor=write_file_tool,
            category=ToolCategory.FILE_OPS
        ))

        registry.register(Tool(
            name="list_files",
            description="List files",
            parameters={"type": "object", "properties": {}},
            executor=list_files_tool,
            category=ToolCategory.FILE_OPS
        ))

        return registry

    @pytest.mark.asyncio
    async def test_create_component_workflow(
        self,
        full_tool_registry,
        test_context
    ):
        """Test complete workflow: create a new React component."""
        class ComponentCreationModel(ModelAdapter):
            def __init__(self):
                self.responses = [
                    # Step 1: List files to understand structure
                    """
THOUGHT: First, I'll check what files exist.

<tool_call>
<tool_name>list_files</tool_name>
<parameters>
{}
</parameters>
</tool_call>
""",
                    # Step 2: Create the component
                    """
THOUGHT: Now I'll create the Button component.

<tool_call>
<tool_name>write_file</tool_name>
<parameters>
{
  "file_path": "src/components/Button.jsx",
  "content": "import React from 'react';\\n\\nexport default function Button({ children, onClick }) {\\n  return <button onClick={onClick}>{children}</button>;\\n}"
}
</parameters>
</tool_call>
""",
                    # Step 3: Complete
                    "TASK_COMPLETE"
                ]
                self.call_count = 0

            async def chat(self, messages, **kwargs):
                response = self.responses[min(self.call_count, len(self.responses) - 1)]
                self.call_count += 1
                for char in response:
                    yield char

            def get_model_name(self):
                return "component-creator"

        agent = IterativeAgent(
            system_prompt="You are a React developer.",
            tools=full_tool_registry,
            model=ComponentCreationModel(),
            max_iterations=5
        )

        events = []
        async for event in agent.run("Create a Button component", test_context):
            events.append(event)

        # Verify workflow completed successfully
        complete_events = [e for e in events if e['type'] == 'complete']
        assert len(complete_events) == 1
        assert complete_events[0]['data']['success'] is True

        # Verify correct number of tool calls
        step_events = [e for e in events if e['type'] == 'agent_step']
        assert len(step_events) >= 2

        # Verify tools were called in correct order
        assert step_events[0]['data']['tool_calls'][0]['name'] == 'list_files'
        assert step_events[1]['data']['tool_calls'][0]['name'] == 'write_file'

    @pytest.mark.asyncio
    async def test_read_modify_write_workflow(
        self,
        full_tool_registry,
        test_context
    ):
        """Test workflow: read existing file, modify, and write back."""
        # Pre-populate with an existing file
        async def setup_file(params, context):
            return {}

        # Add initial file to storage (accessing the closure)
        for tool in full_tool_registry._tools.values():
            if tool.name == "write_file":
                # Pre-create a file
                await tool.executor(
                    {"file_path": "src/App.jsx", "content": "const greeting = 'Hello';"},
                    test_context
                )

        class ModifyFileModel(ModelAdapter):
            def __init__(self):
                self.responses = [
                    # Step 1: Read existing file
                    """
THOUGHT: I'll read the current file first.

<tool_call>
<tool_name>read_file</tool_name>
<parameters>
{"file_path": "src/App.jsx"}
</parameters>
</tool_call>
""",
                    # Step 2: Write modified version
                    """
THOUGHT: Now I'll update it.

<tool_call>
<tool_name>write_file</tool_name>
<parameters>
{
  "file_path": "src/App.jsx",
  "content": "const greeting = 'Hello World';"
}
</parameters>
</tool_call>
""",
                    "TASK_COMPLETE"
                ]
                self.call_count = 0

            async def chat(self, messages, **kwargs):
                response = self.responses[min(self.call_count, len(self.responses) - 1)]
                self.call_count += 1
                for char in response:
                    yield char

            def get_model_name(self):
                return "modifier"

        agent = IterativeAgent(
            system_prompt="Modify files",
            tools=full_tool_registry,
            model=ModifyFileModel(),
            max_iterations=5
        )

        events = []
        async for event in agent.run("Update greeting to 'Hello World'", test_context):
            events.append(event)

        # Verify successful completion
        complete_events = [e for e in events if e['type'] == 'complete']
        assert len(complete_events) == 1
        assert complete_events[0]['data']['success'] is True

        # Verify read then write
        step_events = [e for e in events if e['type'] == 'agent_step']
        assert step_events[0]['data']['tool_calls'][0]['name'] == 'read_file'
        assert step_events[1]['data']['tool_calls'][0]['name'] == 'write_file'

    @pytest.mark.asyncio
    async def test_error_recovery_workflow(
        self,
        full_tool_registry,
        test_context
    ):
        """Test agent recovering from errors."""
        class ErrorRecoveryModel(ModelAdapter):
            def __init__(self):
                self.responses = [
                    # Step 1: Try to read non-existent file (will fail)
                    """
<tool_call>
<tool_name>read_file</tool_name>
<parameters>
{"file_path": "nonexistent.jsx"}
</parameters>
</tool_call>
""",
                    # Step 2: Create the file instead
                    """
THOUGHT: File doesn't exist, I'll create it.

<tool_call>
<tool_name>write_file</tool_name>
<parameters>
{
  "file_path": "nonexistent.jsx",
  "content": "export default function Component() {}"
}
</parameters>
</tool_call>
""",
                    "TASK_COMPLETE"
                ]
                self.call_count = 0

            async def chat(self, messages, **kwargs):
                response = self.responses[min(self.call_count, len(self.responses) - 1)]
                self.call_count += 1
                for char in response:
                    yield char

            def get_model_name(self):
                return "error-recovery"

        agent = IterativeAgent(
            system_prompt="Handle errors",
            tools=full_tool_registry,
            model=ErrorRecoveryModel(),
            max_iterations=5
        )

        events = []
        async for event in agent.run("Read or create component", test_context):
            events.append(event)

        # Should complete despite initial error
        complete_events = [e for e in events if e['type'] == 'complete']
        assert len(complete_events) == 1
        assert complete_events[0]['data']['success'] is True

        # Verify error was encountered and recovered
        step_events = [e for e in events if e['type'] == 'agent_step']
        first_result = step_events[0]['data']['tool_results'][0]
        assert first_result['success'] is True  # Tool execution succeeds
        assert 'does not exist' in first_result['result']['message']  # But file not found

    @pytest.mark.asyncio
    async def test_multi_file_creation_workflow(
        self,
        full_tool_registry,
        test_context
    ):
        """Test creating multiple related files."""
        class MultiFileModel(ModelAdapter):
            def __init__(self):
                self.responses = [
                    """
<tool_call>
<tool_name>write_file</tool_name>
<parameters>
{"file_path": "src/Header.jsx", "content": "export default function Header() {}"}
</parameters>
</tool_call>
""",
                    """
<tool_call>
<tool_name>write_file</tool_name>
<parameters>
{"file_path": "src/Footer.jsx", "content": "export default function Footer() {}"}
</parameters>
</tool_call>
""",
                    """
<tool_call>
<tool_name>write_file</tool_name>
<parameters>
{"file_path": "src/Layout.jsx", "content": "import Header from './Header';\\nimport Footer from './Footer';"}
</parameters>
</tool_call>
""",
                    "TASK_COMPLETE"
                ]
                self.call_count = 0

            async def chat(self, messages, **kwargs):
                response = self.responses[min(self.call_count, len(self.responses) - 1)]
                self.call_count += 1
                for char in response:
                    yield char

            def get_model_name(self):
                return "multi-file"

        agent = IterativeAgent(
            system_prompt="Create components",
            tools=full_tool_registry,
            model=MultiFileModel(),
            max_iterations=10
        )

        events = []
        async for event in agent.run("Create Header, Footer, and Layout", test_context):
            events.append(event)

        # Should create all 3 files
        step_events = [e for e in events if e['type'] == 'agent_step']
        assert len(step_events) >= 3

        # Verify all files were created
        file_creations = [
            step['data']['tool_calls'][0]['parameters']['file_path']
            for step in step_events
            if step['data']['tool_calls']
        ]
        assert 'src/Header.jsx' in file_creations
        assert 'src/Footer.jsx' in file_creations
        assert 'src/Layout.jsx' in file_creations


@pytest.mark.e2e
class TestStreamAgentE2E:
    """End-to-end tests for StreamAgent."""

    @pytest.mark.asyncio
    async def test_stream_agent_basic_workflow(
        self,
        test_context,
        mock_db
    ):
        """Test StreamAgent basic streaming workflow."""
        # This is a simplified test since StreamAgent requires more infrastructure
        # (OpenAI client, file system, etc.)

        # Mock OpenAI client
        class MockOpenAIClient:
            async def chat_completions_create(self, **kwargs):
                async def mock_stream():
                    chunks = ["Hello", " ", "World"]
                    for chunk_text in chunks:
                        chunk = Mock()
                        chunk.choices = [Mock()]
                        chunk.choices[0].delta.content = chunk_text
                        yield chunk
                return mock_stream()

        # This test demonstrates the structure but would need full mocking
        # of file system and OpenAI client to run
        agent = StreamAgent(
            system_prompt="You are a helpful assistant.",
            tools=None
        )

        # In a real test, we'd mock all dependencies and verify:
        # 1. Streaming works
        # 2. Code blocks are extracted
        # 3. Files are saved
        # For now, this demonstrates the test structure
        assert agent.system_prompt == "You are a helpful assistant."
