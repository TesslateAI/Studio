#!/bin/bash

# Script to build and deploy Tesslate Studio to local Kubernetes cluster
# This assumes the local K8s cluster is already running via k8s-local-setup.sh

set -e

echo "=== Deploying Tesslate Studio to Local Kubernetes ==="

# Configuration
REGISTRY="localhost:30500"
NAMESPACE="tesslate"
PROJECT_ROOT=$(pwd)

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if we're in the right directory
if [ ! -d "builder" ]; then
    echo -e "${RED}Error: 'builder' directory not found. Please run this script from the Tesslate Studio root directory.${NC}"
    exit 1
fi

# Check if k8s-local-master container is running
if ! docker ps | grep -q k8s-local-master; then
    echo -e "${RED}Error: k8s-local-master container is not running.${NC}"
    echo "Please run ./k8s-local-setup.sh first"
    exit 1
fi

echo -e "${GREEN}Step 1: Creating Kubernetes manifests${NC}"

# Create k8s directory for manifests
mkdir -p k8s-manifests

# Create namespace manifest
cat > k8s-manifests/00-namespace.yaml <<EOF
apiVersion: v1
kind: Namespace
metadata:
  name: tesslate
EOF

# Create PostgreSQL manifest (using SQLite data migration later)
cat > k8s-manifests/01-postgres.yaml <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: postgres-secret
  namespace: tesslate
type: Opaque
data:
  # WARNING: Replace with your own secure password encoded in base64
  # Use: echo -n "YOUR_SECURE_PASSWORD" | base64
  postgres-password: REPLACE_WITH_BASE64_ENCODED_PASSWORD
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: postgres-pvc
  namespace: tesslate
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 5Gi
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: postgres
  namespace: tesslate
spec:
  replicas: 1
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      containers:
      - name: postgres
        image: postgres:15-alpine
        env:
        - name: POSTGRES_DB
          value: tesslate
        - name: POSTGRES_USER
          value: postgres
        - name: POSTGRES_PASSWORD
          valueFrom:
            secretKeyRef:
              name: postgres-secret
              key: postgres-password
        ports:
        - containerPort: 5432
        volumeMounts:
        - name: postgres-storage
          mountPath: /var/lib/postgresql/data
      volumes:
      - name: postgres-storage
        persistentVolumeClaim:
          claimName: postgres-pvc
---
apiVersion: v1
kind: Service
metadata:
  name: postgres
  namespace: tesslate
spec:
  selector:
    app: postgres
  ports:
  - port: 5432
    targetPort: 5432
EOF

# Create backend Dockerfile for Kubernetes
cat > builder/backend/Dockerfile.k8s <<'EOF'
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir psycopg2-binary

# Copy application code
COPY . .

# Create directories
RUN mkdir -p /app/users /app/templates

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

# Use environment variable for database URL
ENV DATABASE_URL="sqlite:///./builder.db"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
EOF

# Create backend manifest
cat > k8s-manifests/02-backend.yaml <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: backend-secret
  namespace: tesslate
type: Opaque
data:
  secret-key: $(echo -n "your-secret-key-change-in-production" | base64)
  # WARNING: Replace "YOUR_PASSWORD" with your actual secure postgres password
  database-url: $(echo -n "postgresql://postgres:YOUR_PASSWORD@postgres:5432/tesslate" | base64)
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: backend-config
  namespace: tesslate
data:
  DEV_MODE: "true"
  CORS_ORIGINS: '["http://localhost:30080", "http://localhost:3000", "http://frontend-service"]'
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: backend
  namespace: tesslate
spec:
  replicas: 1
  selector:
    matchLabels:
      app: backend
  template:
    metadata:
      labels:
        app: backend
    spec:
      containers:
      - name: backend
        image: ${REGISTRY}/tesslate-backend:latest
        imagePullPolicy: Always
        ports:
        - containerPort: 8000
        env:
        - name: SECRET_KEY
          valueFrom:
            secretKeyRef:
              name: backend-secret
              key: secret-key
        - name: DATABASE_URL
          value: "sqlite:///./builder.db"  # Start with SQLite, migrate later
        - name: DEV_MODE
          valueFrom:
            configMapKeyRef:
              name: backend-config
              key: DEV_MODE
        volumeMounts:
        - name: data
          mountPath: /app/data
        - name: users
          mountPath: /app/users
      volumes:
      - name: data
        emptyDir: {}
      - name: users
        emptyDir: {}
---
apiVersion: v1
kind: Service
metadata:
  name: backend-service
  namespace: tesslate
spec:
  selector:
    app: backend
  ports:
  - port: 8000
    targetPort: 8000
EOF

# Create frontend nginx.conf
cat > builder/frontend/nginx.conf <<'EOF'
server {
    listen 80;
    server_name localhost;
    root /usr/share/nginx/html;
    index index.html;

    # Frontend routes
    location / {
        try_files $uri $uri/ /index.html;
    }

    # API proxy
    location /api {
        proxy_pass http://backend-service:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # Health check
    location /health {
        access_log off;
        return 200 "healthy\n";
        add_header Content-Type text/plain;
    }
}
EOF

# Create frontend Dockerfile for Kubernetes
cat > builder/frontend/Dockerfile.k8s <<'EOF'
FROM node:20-alpine as builder

WORKDIR /app

# Copy package files
COPY package*.json ./
RUN npm ci

# Copy source code
COPY . .

# Build the application
RUN npm run build

# Production stage
FROM nginx:alpine

# Copy built files
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
EOF

# Create frontend manifest
cat > k8s-manifests/03-frontend.yaml <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: frontend
  namespace: tesslate
spec:
  replicas: 1
  selector:
    matchLabels:
      app: frontend
  template:
    metadata:
      labels:
        app: frontend
    spec:
      containers:
      - name: frontend
        image: ${REGISTRY}/tesslate-frontend:latest
        imagePullPolicy: Always
        ports:
        - containerPort: 80
        resources:
          requests:
            memory: "128Mi"
            cpu: "100m"
          limits:
            memory: "256Mi"
            cpu: "200m"
---
apiVersion: v1
kind: Service
metadata:
  name: frontend-service
  namespace: tesslate
spec:
  selector:
    app: frontend
  ports:
  - port: 80
    targetPort: 80
EOF

# Create Ingress manifest
cat > k8s-manifests/04-ingress.yaml <<EOF
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: tesslate-ingress
  namespace: tesslate
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
spec:
  ingressClassName: nginx
  rules:
  - host: tesslate.local
    http:
      paths:
      - path: /api
        pathType: Prefix
        backend:
          service:
            name: backend-service
            port:
              number: 8000
      - path: /
        pathType: Prefix
        backend:
          service:
            name: frontend-service
            port:
              number: 80
EOF

echo -e "${GREEN}Step 2: Building Docker images${NC}"

# Build backend image
echo "Building backend image..."
docker build -t ${REGISTRY}/tesslate-backend:latest -f builder/backend/Dockerfile.k8s builder/backend/

# Build frontend image
echo "Building frontend image..."
docker build -t ${REGISTRY}/tesslate-frontend:latest -f builder/frontend/Dockerfile.k8s builder/frontend/

echo -e "${GREEN}Step 3: Setting up local Docker registry in K8s${NC}"

# Create registry in Kubernetes
docker exec k8s-local-master kubectl apply -f - <<'EOF'
apiVersion: v1
kind: Namespace
metadata:
  name: registry
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: docker-registry
  namespace: registry
spec:
  replicas: 1
  selector:
    matchLabels:
      app: docker-registry
  template:
    metadata:
      labels:
        app: docker-registry
    spec:
      containers:
      - name: registry
        image: registry:2
        ports:
        - containerPort: 5000
        volumeMounts:
        - name: registry-storage
          mountPath: /var/lib/registry
      volumes:
      - name: registry-storage
        emptyDir: {}
---
apiVersion: v1
kind: Service
metadata:
  name: docker-registry
  namespace: registry
spec:
  selector:
    app: docker-registry
  type: NodePort
  ports:
  - port: 5000
    targetPort: 5000
    nodePort: 30500
EOF

# Wait for registry to be ready
echo "Waiting for registry to be ready..."
sleep 10

echo -e "${GREEN}Step 4: Pushing images to local registry${NC}"

# Tag and push images
docker tag ${REGISTRY}/tesslate-backend:latest ${REGISTRY}/tesslate-backend:latest
docker tag ${REGISTRY}/tesslate-frontend:latest ${REGISTRY}/tesslate-frontend:latest

# Configure Docker to use insecure registry
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]]; then
    echo "Note: On Windows, ensure Docker Desktop is configured to use insecure registry localhost:30500"
else
    # For Linux/Mac, update daemon.json if needed
    echo "Configuring Docker for insecure registry..."
fi

# Push images
docker push ${REGISTRY}/tesslate-backend:latest || echo "Note: If push fails, configure Docker Desktop to allow insecure registry localhost:30500"
docker push ${REGISTRY}/tesslate-frontend:latest || echo "Note: If push fails, configure Docker Desktop to allow insecure registry localhost:30500"

echo -e "${GREEN}Step 5: Deploying to Kubernetes${NC}"

# Copy manifests to container
docker cp k8s-manifests k8s-local-master:/tmp/

# Apply all manifests
docker exec k8s-local-master bash -c "kubectl apply -f /tmp/k8s-manifests/"

echo -e "${GREEN}Step 6: Waiting for deployments to be ready${NC}"

# Wait for deployments
docker exec k8s-local-master kubectl wait --for=condition=available --timeout=300s deployment/backend -n tesslate || true
docker exec k8s-local-master kubectl wait --for=condition=available --timeout=300s deployment/frontend -n tesslate || true

echo -e "${GREEN}Step 7: Installing Ingress Controller if not present${NC}"

# Check if ingress controller exists
docker exec k8s-local-master kubectl get namespace ingress-nginx 2>/dev/null || {
    echo "Installing NGINX Ingress Controller..."
    docker exec k8s-local-master bash -c '
        curl -fsSL https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.8.1/deploy/static/provider/kind/deploy.yaml | kubectl apply -f -
    '

    echo "Waiting for Ingress Controller to be ready..."
    sleep 30
}

echo -e "${GREEN}Step 8: Checking deployment status${NC}"

# Show status
docker exec k8s-local-master kubectl get all -n tesslate

echo ""
echo -e "${GREEN}=== Deployment Complete ===${NC}"
echo ""
echo "Your Tesslate Studio is now running in local Kubernetes!"
echo ""
echo -e "${YELLOW}Access methods:${NC}"
echo "1. Via NodePort (direct):"
echo "   - Frontend: http://localhost:30080"
echo "   - Backend API: http://localhost:30080/api"
echo ""
echo "2. Via kubectl port-forward:"
echo "   docker exec -it k8s-local-master bash"
echo "   kubectl port-forward -n tesslate svc/frontend-service 8080:80"
echo "   Then access: http://localhost:8080"
echo ""
echo -e "${YELLOW}Useful commands:${NC}"
echo "- Check pods: docker exec k8s-local-master kubectl get pods -n tesslate"
echo "- Check logs: docker exec k8s-local-master kubectl logs -n tesslate deployment/backend"
echo "- Enter pod: docker exec k8s-local-master kubectl exec -it -n tesslate deployment/backend -- bash"
echo ""
echo -e "${YELLOW}To update the deployment:${NC}"
echo "1. Make code changes"
echo "2. Run this script again"
echo ""
echo -e "${YELLOW}To clean up:${NC}"
echo "docker exec k8s-local-master kubectl delete namespace tesslate"
EOF