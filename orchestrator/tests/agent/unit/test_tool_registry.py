"""
Unit tests for ToolRegistry.

Tests tool registration, lookup, execution, and scoped registries.
"""

import pytest
from app.agent.tools.registry import ToolRegistry, Tool, ToolCategory, create_scoped_tool_registry


@pytest.mark.unit
class TestToolRegistry:
    """Test suite for ToolRegistry."""

    @pytest.fixture
    def registry(self):
        """Create a fresh tool registry for testing."""
        return ToolRegistry()

    @pytest.fixture
    def mock_tool_executor(self):
        """Create a mock tool executor function."""
        async def executor(params, context):
            return {
                "message": f"Executed with {params}",
                "success": True
            }
        return executor

    def test_register_tool(self, registry, mock_tool_executor):
        """Test registering a new tool."""
        tool = Tool(
            name="test_tool",
            description="A test tool",
            parameters={
                "type": "object",
                "properties": {
                    "param1": {"type": "string"}
                },
                "required": ["param1"]
            },
            executor=mock_tool_executor,
            category=ToolCategory.FILE_OPS
        )

        registry.register(tool)

        assert registry.get("test_tool") is not None
        assert registry.get("test_tool").name == "test_tool"

    def test_register_overwrites_existing(self, registry, mock_tool_executor):
        """Test that registering same tool name overwrites previous."""
        tool1 = Tool(
            name="test_tool",
            description="First version",
            parameters={},
            executor=mock_tool_executor,
            category=ToolCategory.FILE_OPS
        )

        tool2 = Tool(
            name="test_tool",
            description="Second version",
            parameters={},
            executor=mock_tool_executor,
            category=ToolCategory.FILE_OPS
        )

        registry.register(tool1)
        registry.register(tool2)

        assert registry.get("test_tool").description == "Second version"

    def test_get_nonexistent_tool(self, registry):
        """Test getting a tool that doesn't exist."""
        tool = registry.get("nonexistent_tool")

        assert tool is None

    def test_list_all_tools(self, registry, mock_tool_executor):
        """Test listing all registered tools."""
        tool1 = Tool(
            name="tool1",
            description="Tool 1",
            parameters={},
            executor=mock_tool_executor,
            category=ToolCategory.FILE_OPS
        )

        tool2 = Tool(
            name="tool2",
            description="Tool 2",
            parameters={},
            executor=mock_tool_executor,
            category=ToolCategory.SHELL
        )

        registry.register(tool1)
        registry.register(tool2)

        tools = registry.list_tools()

        assert len(tools) == 2
        assert any(t.name == "tool1" for t in tools)
        assert any(t.name == "tool2" for t in tools)

    def test_list_tools_by_category(self, registry, mock_tool_executor):
        """Test filtering tools by category."""
        file_tool = Tool(
            name="read_file",
            description="Read a file",
            parameters={},
            executor=mock_tool_executor,
            category=ToolCategory.FILE_OPS
        )

        shell_tool = Tool(
            name="bash_exec",
            description="Execute bash command",
            parameters={},
            executor=mock_tool_executor,
            category=ToolCategory.SHELL
        )

        registry.register(file_tool)
        registry.register(shell_tool)

        file_tools = registry.list_tools(category=ToolCategory.FILE_OPS)
        shell_tools = registry.list_tools(category=ToolCategory.SHELL)

        assert len(file_tools) == 1
        assert file_tools[0].name == "read_file"
        assert len(shell_tools) == 1
        assert shell_tools[0].name == "bash_exec"

    @pytest.mark.asyncio
    async def test_execute_tool_success(self, registry):
        """Test successful tool execution."""
        async def success_executor(params, context):
            return {
                "output": f"Processed {params['input']}",
                "status": "ok"
            }

        tool = Tool(
            name="process_tool",
            description="Process data",
            parameters={},
            executor=success_executor,
            category=ToolCategory.FILE_OPS
        )

        registry.register(tool)

        result = await registry.execute(
            tool_name="process_tool",
            parameters={"input": "test_data"},
            context={}
        )

        assert result["success"] is True
        assert result["tool"] == "process_tool"
        assert "Processed test_data" in result["result"]["output"]

    @pytest.mark.asyncio
    async def test_execute_tool_not_found(self, registry):
        """Test executing a non-existent tool."""
        result = await registry.execute(
            tool_name="nonexistent_tool",
            parameters={},
            context={}
        )

        assert result["success"] is False
        assert "Unknown tool" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_tool_executor_exception(self, registry):
        """Test handling of exceptions during tool execution."""
        async def failing_executor(params, context):
            raise ValueError("Something went wrong")

        tool = Tool(
            name="failing_tool",
            description="A tool that fails",
            parameters={},
            executor=failing_executor,
            category=ToolCategory.FILE_OPS
        )

        registry.register(tool)

        result = await registry.execute(
            tool_name="failing_tool",
            parameters={},
            context={}
        )

        assert result["success"] is False
        assert "Something went wrong" in result["error"]

    def test_tool_to_prompt_format(self, mock_tool_executor):
        """Test converting tool to prompt format."""
        tool = Tool(
            name="test_tool",
            description="A test tool with parameters",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the file"
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to write"
                    }
                },
                "required": ["file_path"]
            },
            executor=mock_tool_executor,
            category=ToolCategory.FILE_OPS,
            examples=["Example usage"]
        )

        prompt_text = tool.to_prompt_format()

        assert "test_tool" in prompt_text
        assert "A test tool with parameters" in prompt_text
        assert "file_path" in prompt_text
        assert "Path to the file" in prompt_text
        assert "required" in prompt_text
        assert "optional" in prompt_text
        assert "Example usage" in prompt_text

    def test_get_system_prompt_section(self, registry, mock_tool_executor):
        """Test generating system prompt section with tools."""
        file_tool = Tool(
            name="read_file",
            description="Read a file",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "File path"}
                },
                "required": ["file_path"]
            },
            executor=mock_tool_executor,
            category=ToolCategory.FILE_OPS
        )

        shell_tool = Tool(
            name="bash_exec",
            description="Execute command",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Command to execute"}
                },
                "required": ["command"]
            },
            executor=mock_tool_executor,
            category=ToolCategory.SHELL
        )

        registry.register(file_tool)
        registry.register(shell_tool)

        prompt = registry.get_system_prompt_section()

        assert "read_file" in prompt
        assert "bash_exec" in prompt
        assert "File Operations" in prompt
        assert "Shell Commands" in prompt

    @pytest.mark.asyncio
    async def test_execute_with_context(self, registry, test_context):
        """Test that context is passed to tool executor."""
        received_context = {}

        async def context_checker(params, context):
            received_context.update(context)
            return {"message": "Context received"}

        tool = Tool(
            name="context_tool",
            description="Check context",
            parameters={},
            executor=context_checker,
            category=ToolCategory.FILE_OPS
        )

        registry.register(tool)

        await registry.execute(
            tool_name="context_tool",
            parameters={},
            context=test_context
        )

        assert "user_id" in received_context
        assert "project_id" in received_context
        assert received_context["user_id"] == test_context["user_id"]


@pytest.mark.unit
class TestScopedToolRegistry:
    """Test suite for scoped tool registries."""

    @pytest.fixture
    def mock_tool_executor(self):
        """Create a mock tool executor function."""
        async def executor(params, context):
            return {
                "message": f"Executed with {params}",
                "success": True
            }
        return executor

    @pytest.fixture
    def populated_registry(self, mock_tool_executor):
        """Create a registry with multiple tools."""
        registry = ToolRegistry()

        tools = [
            Tool("read_file", "Read file", {}, mock_tool_executor, ToolCategory.FILE_OPS),
            Tool("write_file", "Write file", {}, mock_tool_executor, ToolCategory.FILE_OPS),
            Tool("bash_exec", "Execute bash", {}, mock_tool_executor, ToolCategory.SHELL),
            Tool("get_project_info", "Get info", {}, mock_tool_executor, ToolCategory.PROJECT),
        ]

        for tool in tools:
            registry.register(tool)

        return registry

    def test_create_scoped_registry_subset(self, populated_registry, mock_tool_executor, monkeypatch):
        """Test creating a scoped registry with subset of tools."""
        # Mock get_tool_registry to return our populated registry
        from app.agent.tools import registry as registry_module
        monkeypatch.setattr(registry_module, "get_tool_registry", lambda: populated_registry)

        scoped = create_scoped_tool_registry(["read_file", "write_file"])

        assert scoped.get("read_file") is not None
        assert scoped.get("write_file") is not None
        assert scoped.get("bash_exec") is None
        assert scoped.get("get_project_info") is None
        assert len(scoped._tools) == 2

    def test_create_scoped_registry_missing_tools(self, populated_registry, monkeypatch):
        """Test creating scoped registry with some non-existent tools."""
        from app.agent.tools import registry as registry_module
        monkeypatch.setattr(registry_module, "get_tool_registry", lambda: populated_registry)

        scoped = create_scoped_tool_registry(["read_file", "nonexistent_tool"])

        assert scoped.get("read_file") is not None
        assert scoped.get("nonexistent_tool") is None
        assert len(scoped._tools) == 1

    def test_create_scoped_registry_empty_list(self, populated_registry, monkeypatch):
        """Test creating scoped registry with empty tool list."""
        from app.agent.tools import registry as registry_module
        monkeypatch.setattr(registry_module, "get_tool_registry", lambda: populated_registry)

        scoped = create_scoped_tool_registry([])

        assert len(scoped._tools) == 0

    @pytest.mark.asyncio
    async def test_scoped_registry_isolation(self, populated_registry, monkeypatch):
        """Test that scoped registry doesn't affect global registry."""
        from app.agent.tools import registry as registry_module
        monkeypatch.setattr(registry_module, "get_tool_registry", lambda: populated_registry)

        scoped = create_scoped_tool_registry(["read_file"])

        # Global registry should still have all tools
        assert len(populated_registry._tools) == 4

        # Scoped registry should only have one
        assert len(scoped._tools) == 1


@pytest.mark.unit
class TestToolDataclass:
    """Test suite for Tool dataclass."""

    @pytest.fixture
    def mock_tool_executor(self):
        """Create a mock tool executor function."""
        async def executor(params, context):
            return {
                "message": f"Executed with {params}",
                "success": True
            }
        return executor

    def test_tool_creation(self, mock_tool_executor):
        """Test creating a Tool instance."""
        tool = Tool(
            name="test_tool",
            description="Test description",
            parameters={"type": "object"},
            executor=mock_tool_executor,
            category=ToolCategory.FILE_OPS,
            examples=["Example 1", "Example 2"]
        )

        assert tool.name == "test_tool"
        assert tool.description == "Test description"
        assert tool.category == ToolCategory.FILE_OPS
        assert len(tool.examples) == 2

    def test_tool_creation_without_examples(self, mock_tool_executor):
        """Test creating a Tool without examples."""
        tool = Tool(
            name="test_tool",
            description="Test description",
            parameters={},
            executor=mock_tool_executor,
            category=ToolCategory.FILE_OPS
        )

        assert tool.examples is None

    def test_tool_categories_enum(self):
        """Test ToolCategory enum values."""
        assert ToolCategory.FILE_OPS.value == "file_operations"
        assert ToolCategory.SHELL.value == "shell_commands"
        assert ToolCategory.PROJECT.value == "project_management"
        assert ToolCategory.BUILD.value == "build_operations"
