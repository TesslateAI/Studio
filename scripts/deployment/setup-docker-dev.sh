#!/bin/bash
# Tesslate Studio - Docker Development Setup Script
# This script helps you quickly set up the development environment

set -e  # Exit on error

echo "=================================="
echo "Tesslate Studio Docker Setup"
echo "=================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}Error: Docker is not running. Please start Docker Desktop and try again.${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Docker is running${NC}"

# Change to project root directory
cd "$(dirname "$0")/../.."

# Create root .env if it doesn't exist
if [ ! -f .env ]; then
    echo "Creating .env file..."
    cp .env.example .env
    echo -e "${GREEN}✓ Created .env${NC}"
    echo -e "${YELLOW}⚠ IMPORTANT: Edit .env and set your SECRET_KEY and LITELLM_MASTER_KEY${NC}"
else
    echo -e "${GREEN}✓ .env already exists${NC}"
fi

# Create traefik acme.json if it doesn't exist
if [ ! -f traefik/acme.json ]; then
    echo "Creating traefik/acme.json..."
    touch traefik/acme.json
    chmod 600 traefik/acme.json 2>/dev/null || true  # Ignore chmod errors on Windows
    echo -e "${GREEN}✓ Created traefik/acme.json${NC}"
else
    echo -e "${GREEN}✓ traefik/acme.json already exists${NC}"
fi

# Check if required environment variables are set
echo ""
echo "Checking configuration..."

if grep -q "your-secret-key-here-change-this-in-production" .env 2>/dev/null; then
    echo -e "${YELLOW}⚠ WARNING: SECRET_KEY is not configured in .env${NC}"
    NEEDS_CONFIG=true
fi

if grep -q "your-litellm-master-key-here" .env 2>/dev/null; then
    echo -e "${YELLOW}⚠ WARNING: LITELLM_MASTER_KEY is not configured in .env${NC}"
    NEEDS_CONFIG=true
fi

if [ "$NEEDS_CONFIG" = true ]; then
    echo ""
    echo -e "${YELLOW}Please edit .env and set:${NC}"
    echo "  1. SECRET_KEY (must be at least 32 characters)"
    echo "  2. LITELLM_MASTER_KEY (for your LiteLLM proxy)"
    echo ""
    read -p "Press Enter when you've updated .env, or Ctrl+C to exit..."
fi

echo ""
echo "=================================="
echo "Starting Docker Compose..."
echo "=================================="

# Start services
docker compose up -d

echo ""
echo -e "${GREEN}✓ Services started successfully!${NC}"
echo ""
echo "=================================="
echo "Access the application:"
echo "=================================="
echo "  Frontend:  http://studio.localhost"
echo "  Backend:   http://api.localhost"
echo "  Traefik:   http://traefik.localhost:8080"
echo ""
echo "=================================="
echo "Useful commands:"
echo "=================================="
echo "  View logs:        docker compose logs -f"
echo "  Stop services:    docker compose down"
echo "  Restart:          docker compose restart"
echo ""
echo -e "${GREEN}Setup complete! Happy coding! 🚀${NC}"
