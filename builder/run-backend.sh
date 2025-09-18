#!/bin/bash
cd backend
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8004