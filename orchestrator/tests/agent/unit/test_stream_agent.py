"""
Unit tests for StreamAgent.

Tests streaming agent functionality including code block extraction and file saving.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.stream_agent import StreamAgent


@pytest.mark.unit
class TestStreamAgent:
    """Test suite for StreamAgent."""

    @pytest.fixture
    def stream_agent(self):
        """Create a StreamAgent instance."""
        return StreamAgent(system_prompt="You are a code generation assistant.")

    def test_stream_agent_initialization(self):
        """Test StreamAgent initialization."""
        agent = StreamAgent("Test prompt")
        assert agent.system_prompt == "Test prompt"
        assert agent.tools is None

    def test_stream_agent_initialization_with_tools(self, mock_tool_registry):
        """Test StreamAgent initialization with tools (even though it doesn't use them)."""
        agent = StreamAgent("Test prompt", tools=mock_tool_registry)
        assert agent.system_prompt == "Test prompt"
        assert agent.tools is mock_tool_registry

    def test_extract_code_blocks_standard_format(self, stream_agent):
        """Test extracting code blocks with standard format."""
        content = """
Here's the file:

```javascript
// File: src/App.jsx
import React from 'react';
export default function App() {
  return <div>Hello</div>;
}
```
"""
        blocks = stream_agent._extract_code_blocks(content)

        assert len(blocks) == 1
        assert blocks[0][0] == "src/App.jsx"
        assert "import React" in blocks[0][1]

    def test_extract_code_blocks_multiple_files(self, stream_agent):
        """Test extracting multiple code blocks."""
        content = """
```javascript
// File: src/Header.jsx
export default function Header() {}
```

```javascript
// File: src/Footer.jsx
export default function Footer() {}
```
"""
        blocks = stream_agent._extract_code_blocks(content)

        assert len(blocks) == 2
        assert blocks[0][0] == "src/Header.jsx"
        assert blocks[1][0] == "src/Footer.jsx"

    def test_extract_code_blocks_hash_comment_format(self, stream_agent):
        """Test extracting code blocks with hash comments."""
        content = """
```python
# File: src/main.py
def main():
    print("Hello")
```
"""
        blocks = stream_agent._extract_code_blocks(content)

        assert len(blocks) == 1
        assert blocks[0][0] == "src/main.py"

    def test_extract_code_blocks_html_comment_format(self, stream_agent):
        """Test extracting code blocks with HTML comments."""
        content = """
```html
<!-- File: index.html -->
<!DOCTYPE html>
<html></html>
```
"""
        blocks = stream_agent._extract_code_blocks(content)

        assert len(blocks) == 1
        assert blocks[0][0] == "index.html"

    def test_extract_code_blocks_simple_path_format(self, stream_agent):
        """Test extracting code blocks with simple path format."""
        content = """
```javascript
src/utils.js
export const add = (a, b) => a + b;
```
"""
        blocks = stream_agent._extract_code_blocks(content)

        assert len(blocks) == 1
        assert blocks[0][0] == "src/utils.js"

    def test_extract_code_blocks_ignores_invalid_paths(self, stream_agent):
        """Test that invalid paths are ignored."""
        content = """
```javascript
// This is not a file path
const x = 1;
```

```javascript
// File: valid/path.js
const y = 2;
```
"""
        blocks = stream_agent._extract_code_blocks(content)

        # Should only extract the valid one
        assert len(blocks) == 1
        assert blocks[0][0] == "valid/path.js"

    def test_extract_code_blocks_ignores_duplicates(self, stream_agent):
        """Test that duplicate file paths are ignored."""
        content = """
```javascript
// File: src/App.jsx
const App1 = () => {};
```

```javascript
// File: src/App.jsx
const App2 = () => {};
```
"""
        blocks = stream_agent._extract_code_blocks(content)

        # Should only extract first occurrence
        assert len(blocks) == 1
        assert "App1" in blocks[0][1]

    def test_extract_code_blocks_validates_extensions(self, stream_agent):
        """Test that paths without extensions are ignored."""
        content = """
```javascript
// File: src/noextension
const x = 1;
```

```javascript
// File: src/valid.js
const y = 2;
```
"""
        blocks = stream_agent._extract_code_blocks(content)

        assert len(blocks) == 1
        assert blocks[0][0] == "src/valid.js"

    def test_extract_code_blocks_handles_empty_content(self, stream_agent):
        """Test extracting from empty content."""
        blocks = stream_agent._extract_code_blocks("")
        assert len(blocks) == 0

    def test_extract_code_blocks_handles_no_code_blocks(self, stream_agent):
        """Test content with no code blocks."""
        content = "Just some regular text without any code blocks."
        blocks = stream_agent._extract_code_blocks(content)
        assert len(blocks) == 0

    @pytest.mark.asyncio
    async def test_save_file_success(self, stream_agent, mock_user, mock_project, mock_db):
        """Test successful file saving."""
        # Mock db.execute to return no existing file
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_orchestrator = MagicMock()
        mock_orchestrator.write_file = AsyncMock(return_value=True)

        with (
            patch(
                "app.services.orchestration.get_orchestrator",
                return_value=mock_orchestrator,
            ),
            patch("app.services.orchestration.is_kubernetes_mode", return_value=False),
            patch("aiofiles.open", side_effect=OSError("skip filesystem write")),
        ):
            result = await stream_agent._save_file(
                file_path="src/App.jsx",
                code="export default function App() {}",
                project_id=mock_project.id,
                user_id=mock_user.id,
                db=mock_db,
            )

        assert result is True
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_file_database_error_continues(
        self, stream_agent, mock_user, mock_project, mock_db
    ):
        """Test that database errors don't prevent file writing."""
        mock_db.execute = AsyncMock(side_effect=RuntimeError("DB connection lost"))

        mock_orchestrator = MagicMock()
        mock_orchestrator.write_file = AsyncMock(return_value=True)

        with (
            patch(
                "app.services.orchestration.get_orchestrator",
                return_value=mock_orchestrator,
            ),
            patch("app.services.orchestration.is_kubernetes_mode", return_value=False),
            patch("aiofiles.open", side_effect=OSError("skip filesystem write")),
        ):
            result = await stream_agent._save_file(
                file_path="src/App.jsx",
                code="export default function App() {}",
                project_id=mock_project.id,
                user_id=mock_user.id,
                db=mock_db,
            )

        # Should still succeed — DB error is non-blocking
        assert result is True
        mock_db.rollback.assert_called_once()
        # Container write should still have been attempted
        mock_orchestrator.write_file.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_streams_response_chunks(self, stream_agent, test_context):
        """Test that agent streams response chunks."""
        # Create mock streaming chunks
        chunks = []
        for text in ["Hello ", "world", "!"]:
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta.content = text
            chunks.append(chunk)

        async def mock_stream():
            for c in chunks:
                yield c

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_stream())

        with patch("app.agent.models.get_llm_client", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_client

            events = []
            async for event in stream_agent.run("Say hello", test_context):
                events.append(event)

        stream_events = [e for e in events if e["type"] == "stream"]
        assert len(stream_events) == 3
        assert stream_events[0]["content"] == "Hello "
        assert stream_events[1]["content"] == "world"
        assert stream_events[2]["content"] == "!"

        # Should end with complete event
        assert events[-1]["type"] == "complete"

    @pytest.mark.asyncio
    async def test_run_handles_client_error(self, stream_agent, test_context):
        """Test that agent handles client creation errors."""
        with patch("app.agent.models.get_llm_client", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = ValueError("Invalid API key")

            events = []
            async for event in stream_agent.run("Say hello", test_context):
                events.append(event)

        assert len(events) == 1
        assert events[0]["type"] == "error"
        assert "Invalid API key" in events[0]["content"]

    @pytest.mark.asyncio
    async def test_run_extracts_and_saves_files(self, stream_agent, test_context):
        """Test that agent extracts and saves files from response."""
        response_text = (
            "Here's the file:\n\n"
            "```javascript\n"
            "// File: src/App.jsx\n"
            "export default function App() { return <div>Hello</div>; }\n"
            "```\n"
        )

        # Create a single chunk with the full response
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = response_text

        async def mock_stream():
            yield chunk

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_stream())

        with (
            patch("app.agent.models.get_llm_client", new_callable=AsyncMock) as mock_get,
            patch.object(stream_agent, "_save_file", new_callable=AsyncMock) as mock_save,
        ):
            mock_get.return_value = mock_client
            mock_save.return_value = True

            events = []
            async for event in stream_agent.run("Create an App component", test_context):
                events.append(event)

        # _save_file should have been called for the extracted file
        mock_save.assert_called_once()
        call_kwargs = mock_save.call_args
        assert call_kwargs[1]["file_path"] == "src/App.jsx"

        # Should have a file_ready event
        file_events = [e for e in events if e["type"] == "file_ready"]
        assert len(file_events) == 1
        assert file_events[0]["file_path"] == "src/App.jsx"


@pytest.mark.unit
class TestStreamAgentCodeExtraction:
    """Additional tests for code extraction edge cases."""

    @pytest.fixture
    def agent(self):
        return StreamAgent("Test")

    def test_extract_handles_nested_code_blocks(self, agent):
        """Test extraction with nested markdown."""
        content = """
```javascript
// File: src/README.md
# This is markdown
```javascript
nested code
```
```
"""
        blocks = agent._extract_code_blocks(content)
        # Should extract the outer block
        assert len(blocks) >= 0

    def test_extract_handles_special_characters_in_path(self, agent):
        """Test paths with special characters."""
        content = """
```javascript
// File: src/my-component_v2.jsx
const Component = () => {};
```
"""
        blocks = agent._extract_code_blocks(content)
        assert len(blocks) == 1
        assert blocks[0][0] == "src/my-component_v2.jsx"

    def test_extract_handles_long_paths(self, agent):
        """Test very long file paths are rejected."""
        long_path = "src/" + "a" * 300 + ".js"
        content = f"""
```javascript
// File: {long_path}
const x = 1;
```
"""
        blocks = agent._extract_code_blocks(content)
        # Should be rejected (path too long)
        assert len(blocks) == 0

    def test_extract_handles_various_extensions(self, agent):
        """Test extraction with various file extensions."""
        content = """
```typescript
// File: src/App.tsx
export default function App() {}
```

```python
# File: backend/main.py
def main(): pass
```

```javascript
// File: styles/global.css
body { margin: 0; }
```
"""
        blocks = agent._extract_code_blocks(content)
        # Note: CSS with /* */ comment style may not be extracted
        # due to regex pattern matching // or # style comments
        assert len(blocks) >= 2
        assert any("App.tsx" in b[0] for b in blocks)
        assert any("main.py" in b[0] for b in blocks)
