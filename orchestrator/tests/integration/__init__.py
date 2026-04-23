"""
Integration tests for OpenSail.

Integration tests use a real PostgreSQL database (on port 5433) and real FastAPI
ASGI transport. Each test runs in its own transaction that rolls back after completion
for perfect isolation with zero cleanup overhead.
"""
