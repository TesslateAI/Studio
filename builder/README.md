# AI Application Builder

An amazing application builder with real-time AI chat assistance and live preview capabilities.

## Features

- 🤖 Smart AI chat assistant powered by OpenAI-compatible APIs
- 👥 Multi-user support with authentication
- 📁 Project isolation for each user
- 🔄 Real-time file streaming visualization
- 👁️ Live preview of projects in iframe
- 🎨 Beautiful dark theme UI

## Setup

1. Clone this repository
2. Copy `.env.example` to `.env` and fill in your API keys
3. Install dependencies:
   ```bash
   # Backend
   cd backend
   uv sync
   
   # Frontend
   cd ../frontend
   npm install
   ```

## Running the Application

### Backend (Terminal 1):
```bash
cd backend
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend (Terminal 2):
```bash
cd frontend
npm run dev
```

Visit http://localhost:5173 to use the application.

## Architecture

- **Backend**: FastAPI with SQLite database, JWT authentication
- **Frontend**: React with TypeScript, Tailwind CSS, Monaco Editor
- **Real-time**: WebSocket for chat streaming and file updates
- **Storage**: User projects stored in `users/{user_id}/projects/{project_id}/`

## Environment Variables

- `SECRET_KEY`: JWT secret key for authentication
- `DATABASE_URL`: SQLite database connection string
- `OPENAI_API_KEY`: Your OpenAI API key (or compatible API key)
- `OPENAI_API_BASE`: OpenAI API base URL (default: https://api.openai.com/v1)
- `OPENAI_MODEL`: Model to use (e.g., gpt-3.5-turbo, Llama-4-Maverick-17B-128E-Instruct-FP8)
- `VITE_API_URL`: Backend API URL for frontend