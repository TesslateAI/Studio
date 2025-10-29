# PowerShell script to build and deploy Tesslate Studio to local Kubernetes cluster
# This assumes the local K8s cluster is already running via k8s-local-windows.ps1

Write-Host "=== Deploying Tesslate Studio to Local Kubernetes ===" -ForegroundColor Green

# Configuration
$REGISTRY = "localhost:30500"
$NAMESPACE = "tesslate"
$PROJECT_ROOT = Get-Location

# Check if we're in the right directory
if (-not (Test-Path "builder")) {
    Write-Host "Error: 'builder' directory not found. Please run this script from the Tesslate Studio root directory." -ForegroundColor Red
    exit 1
}

# Check if k8s-local-master container is running
$containerRunning = docker ps --format "table {{.Names}}" | Select-String "k8s-local-master"
if (-not $containerRunning) {
    Write-Host "Error: k8s-local-master container is not running." -ForegroundColor Red
    Write-Host "Please run .\k8s-local-windows.ps1 first" -ForegroundColor Yellow
    exit 1
}

Write-Host "Step 1: Creating Kubernetes manifests" -ForegroundColor Green

# Create k8s directory for manifests
New-Item -ItemType Directory -Force -Path "k8s-manifests" | Out-Null

# Create namespace manifest
@"
apiVersion: v1
kind: Namespace
metadata:
  name: tesslate
"@ | Out-File -FilePath "k8s-manifests\00-namespace.yaml" -Encoding UTF8

# Create PostgreSQL manifest
@"
apiVersion: v1
kind: Secret
metadata:
  name: postgres-secret
  namespace: tesslate
type: Opaque
data:
  # WARNING: Replace with your own secure password encoded in base64
  # Use: [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("YOUR_SECURE_PASSWORD"))
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
"@ | Out-File -FilePath "k8s-manifests\01-postgres.yaml" -Encoding UTF8

# Create backend Dockerfile
@'
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
'@ | Out-File -FilePath "builder\backend\Dockerfile.k8s" -Encoding UTF8

# Create backend manifest
$secretKey = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("your-secret-key-change-in-production"))
$dbUrl = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("postgresql://postgres:tesslate123@postgres:5432/tesslate"))

@"
apiVersion: v1
kind: Secret
metadata:
  name: backend-secret
  namespace: tesslate
type: Opaque
data:
  secret-key: $secretKey
  database-url: $dbUrl
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
          value: "sqlite:///./builder.db"
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
"@ | Out-File -FilePath "k8s-manifests\02-backend.yaml" -Encoding UTF8

# Create frontend nginx.conf
@'
server {
    listen 80;
    server_name localhost;
    root /usr/share/nginx/html;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api {
        proxy_pass http://backend-service:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    location /health {
        access_log off;
        return 200 "healthy\n";
        add_header Content-Type text/plain;
    }
}
'@ | Out-File -FilePath "builder\frontend\nginx.conf" -Encoding UTF8 -NoNewline

# Create frontend Dockerfile
@'
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
'@ | Out-File -FilePath "builder\frontend\Dockerfile.k8s" -Encoding UTF8

# Create frontend manifest
@"
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
"@ | Out-File -FilePath "k8s-manifests\03-frontend.yaml" -Encoding UTF8

# Create Ingress manifest
@"
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
"@ | Out-File -FilePath "k8s-manifests\04-ingress.yaml" -Encoding UTF8

Write-Host "Step 2: Building Docker images" -ForegroundColor Green

# Build backend image
Write-Host "Building backend image..." -ForegroundColor Yellow
docker build -t "${REGISTRY}/tesslate-backend:latest" -f builder\backend\Dockerfile.k8s builder\backend\

# Build frontend image
Write-Host "Building frontend image..." -ForegroundColor Yellow
docker build -t "${REGISTRY}/tesslate-frontend:latest" -f builder\frontend\Dockerfile.k8s builder\frontend\

Write-Host "Step 3: Setting up local Docker registry in K8s" -ForegroundColor Green

# Create registry in Kubernetes
$registryManifest = @"
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
"@

# Apply registry manifest
$registryManifest | docker exec -i k8s-local-master kubectl apply -f -

Write-Host "Waiting for registry to be ready..." -ForegroundColor Yellow
Start-Sleep -Seconds 10

Write-Host "Step 4: Pushing images to local registry" -ForegroundColor Green

# Configure Docker for insecure registry if needed
Write-Host "Note: Ensure Docker Desktop is configured to use insecure registry localhost:30500" -ForegroundColor Yellow
Write-Host "Docker Desktop > Settings > Docker Engine > Add to insecure-registries: [""localhost:30500""]" -ForegroundColor Gray

# Push images
docker push "${REGISTRY}/tesslate-backend:latest"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to push backend image. Please configure Docker Desktop for insecure registry localhost:30500" -ForegroundColor Red
}

docker push "${REGISTRY}/tesslate-frontend:latest"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to push frontend image. Please configure Docker Desktop for insecure registry localhost:30500" -ForegroundColor Red
}

Write-Host "Step 5: Deploying to Kubernetes" -ForegroundColor Green

# Copy manifests to container
docker cp k8s-manifests k8s-local-master:/tmp/

# Apply all manifests
docker exec k8s-local-master kubectl apply -f /tmp/k8s-manifests/

Write-Host "Step 6: Waiting for deployments to be ready" -ForegroundColor Green

# Wait for deployments
docker exec k8s-local-master kubectl wait --for=condition=available --timeout=300s deployment/backend -n tesslate
docker exec k8s-local-master kubectl wait --for=condition=available --timeout=300s deployment/frontend -n tesslate

Write-Host "Step 7: Installing Ingress Controller if not present" -ForegroundColor Green

# Check if ingress controller exists
$ingressExists = docker exec k8s-local-master kubectl get namespace ingress-nginx 2>$null
if (-not $ingressExists) {
    Write-Host "Installing NGINX Ingress Controller..." -ForegroundColor Yellow
    docker exec k8s-local-master bash -c "curl -fsSL https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.8.1/deploy/static/provider/kind/deploy.yaml | kubectl apply -f -"

    Write-Host "Waiting for Ingress Controller to be ready..." -ForegroundColor Yellow
    Start-Sleep -Seconds 30
}

Write-Host "Step 8: Creating NodePort service for direct access" -ForegroundColor Green

# Create NodePort service for frontend
$nodePortService = @"
apiVersion: v1
kind: Service
metadata:
  name: frontend-nodeport
  namespace: tesslate
spec:
  selector:
    app: frontend
  type: NodePort
  ports:
  - port: 80
    targetPort: 80
    nodePort: 30080
"@

$nodePortService | docker exec -i k8s-local-master kubectl apply -f -

Write-Host "Step 9: Checking deployment status" -ForegroundColor Green

# Show status
docker exec k8s-local-master kubectl get all -n tesslate

Write-Host ""
Write-Host "=== Deployment Complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "Your Tesslate Studio is now running in local Kubernetes!" -ForegroundColor Cyan
Write-Host ""
Write-Host "Access methods:" -ForegroundColor Yellow
Write-Host "1. Via NodePort (direct):" -ForegroundColor White
Write-Host "   - Frontend: http://localhost:30080" -ForegroundColor Gray
Write-Host "   - Backend API: http://localhost:30080/api" -ForegroundColor Gray
Write-Host ""
Write-Host "2. Via kubectl port-forward:" -ForegroundColor White
Write-Host "   docker exec -it k8s-local-master bash" -ForegroundColor Gray
Write-Host "   kubectl port-forward -n tesslate svc/frontend-service 8080:80" -ForegroundColor Gray
Write-Host "   Then access: http://localhost:8080" -ForegroundColor Gray
Write-Host ""
Write-Host "Useful commands:" -ForegroundColor Yellow
Write-Host "- Check pods: docker exec k8s-local-master kubectl get pods -n tesslate" -ForegroundColor White
Write-Host "- Check logs: docker exec k8s-local-master kubectl logs -n tesslate deployment/backend" -ForegroundColor White
Write-Host "- Enter pod: docker exec k8s-local-master kubectl exec -it -n tesslate deployment/backend -- bash" -ForegroundColor White
Write-Host ""
Write-Host "To update the deployment:" -ForegroundColor Yellow
Write-Host "1. Make code changes" -ForegroundColor White
Write-Host "2. Run this script again" -ForegroundColor White
Write-Host ""
Write-Host "To clean up:" -ForegroundColor Yellow
Write-Host "docker exec k8s-local-master kubectl delete namespace tesslate" -ForegroundColor White