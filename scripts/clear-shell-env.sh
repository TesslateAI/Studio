#!/bin/bash
# Clear shell environment variables that might override .env file
# Run this if you're having issues with environment variables not matching your .env

echo "Clearing shell environment variables..."
unset APP_DOMAIN
unset ALLOWED_HOSTS
unset APP_PROTOCOL
unset CORS_ORIGINS

echo "✓ Shell environment variables cleared"
echo "Your .env file values will now be used by docker-compose"
echo ""
echo "To apply changes, restart services:"
echo "  docker compose down && docker compose up -d"
