# AI Service

AI-powered code generation and assistance service for Tesslate Studio.

## Features

- Code generation with multiple AI models (OpenAI GPT, Anthropic Claude)
- Code refactoring and explanation
- Interactive chat with streaming support
- Template-based code generation
- Context analysis and suggestions

## Setup

```bash
cd ai-service
uv sync
```

## Configuration

Create a `.env` file:

```env
OPENAI_API_KEY=your_openai_key
ANTHROPIC_API_KEY=your_anthropic_key
PORT=8001
ORCHESTRATOR_URL=http://localhost:8000
```

## Development

```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

## API Endpoints

- `POST /api/v1/generate` - Generate code from prompt
- `POST /api/v1/generate/refactor` - Refactor existing code
- `POST /api/v1/generate/explain` - Explain code functionality
- `POST /api/v1/chat` - Chat with AI
- `WS /api/v1/chat/stream` - Streaming chat via WebSocket
- `GET /api/v1/templates` - List available templates
- `POST /api/v1/templates/generate` - Generate from template

## Testing

```bash
uv run pytest
```