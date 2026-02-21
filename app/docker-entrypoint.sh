#!/bin/sh
set -e

# Generate runtime config from environment variables
# This runs BEFORE nginx starts, ensuring config.js is available when the app loads
envsubst '${VITE_API_URL} ${VITE_PUBLIC_POSTHOG_KEY} ${VITE_PUBLIC_POSTHOG_HOST}' \
  < /etc/nginx/templates/config.js.template \
  > /usr/share/nginx/html/config.js

echo "[entrypoint] Generated /usr/share/nginx/html/config.js from environment variables"
cat /usr/share/nginx/html/config.js

# Start nginx
exec nginx -g 'daemon off;'
