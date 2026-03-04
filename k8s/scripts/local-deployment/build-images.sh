#!/bin/bash

# Tesslate Studio - Build Docker Images

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
REGISTRY=${1:-"localhost:30500"}

echo "========================================"
echo "Building Tesslate Studio Docker Images"
echo "Registry: $REGISTRY"
echo "========================================"

# Check if Docker is available
if ! docker --version &> /dev/null; then
    echo "Error: Docker is not installed or not in PATH"
    exit 1
fi

# Build backend image
echo "[1/4] Building backend image..."
cd $PROJECT_ROOT/builder/backend

# Create Dockerfile if it doesn't exist
cat > Dockerfile.k8s <<EOF
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \\
    gcc \\
    postgresql-client \\
    netcat-traditional \\
    curl \\
    && rm -rf /var/lib/apt/lists/*

# Install uv for faster Python package management
RUN pip install uv

# Copy project files
COPY pyproject.toml ./
COPY app ./app
COPY template ./template

# Install Python dependencies using uv
RUN uv pip install --system -e .

# Create non-root user
RUN useradd -m -u 1001 appuser && chown -R appuser:appuser /app
USER appuser

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \\
  CMD curl -f http://localhost:8005/health || exit 1

EXPOSE 8005

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8005"]
EOF

docker build -t tesslate-backend:latest -f Dockerfile.k8s .
docker tag tesslate-backend:latest $REGISTRY/tesslate-backend:latest

# Build frontend image
echo "[2/4] Building frontend image..."
cd $PROJECT_ROOT/builder/frontend

# Create nginx config
cat > nginx.conf <<EOF
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    # Gzip
    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_types text/plain text/css text/xml text/javascript application/javascript application/json application/xml+rss;

    # Frontend routes
    location / {
        try_files \$uri \$uri/ /index.html;
    }

    # API proxy
    location /api {
        proxy_pass http://tesslate-backend-service:8005;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_cache_bypass \$http_upgrade;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

# Create Dockerfile
cat > Dockerfile.k8s <<EOF
FROM node:20-alpine as builder

WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
EOF

docker build -t tesslate-frontend:latest -f Dockerfile.k8s .
docker tag tesslate-frontend:latest $REGISTRY/tesslate-frontend:latest

# Push to registry if not using local
if [ "$REGISTRY" != "localhost:30500" ]; then
    echo "[3/4] Pushing backend image to registry..."
    docker push $REGISTRY/tesslate-backend:latest

    echo "[4/4] Pushing frontend image to registry..."
    docker push $REGISTRY/tesslate-frontend:latest
else
    echo "[3/4] Using local images (not pushing to registry)"
    echo "[4/4] Images are available locally"
fi

echo ""
echo "========================================"
echo "Build Complete!"
echo "========================================"
echo ""
echo "Images built:"
echo "  - tesslate-backend:latest"
echo "  - tesslate-frontend:latest"
echo ""
echo "Tagged for registry:"
echo "  - $REGISTRY/tesslate-backend:latest"
echo "  - $REGISTRY/tesslate-frontend:latest"
echo "========================================"