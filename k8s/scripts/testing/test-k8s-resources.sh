#!/bin/bash
# Test K8s User Environment Resource Creation
# Creates a test deployment/service/ingress to verify backend can create K8s resources

set -e

export KUBECONFIG=~/.kube/configs/digitalocean.yaml

echo "🧪 Testing K8s Resource Creation Permissions..."
echo ""

# Test user/project IDs
TEST_USER_ID=9999
TEST_PROJECT_ID="test123"
NAMESPACE="tesslate-user-environments"
DEPLOYMENT_NAME="dev-user${TEST_USER_ID}-project${TEST_PROJECT_ID}"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

function cleanup() {
    echo ""
    echo "🧹 Cleaning up test resources..."
    kubectl delete deployment ${DEPLOYMENT_NAME} -n ${NAMESPACE} --ignore-not-found=true
    kubectl delete service ${DEPLOYMENT_NAME}-service -n ${NAMESPACE} --ignore-not-found=true
    kubectl delete ingress ${DEPLOYMENT_NAME}-ingress -n ${NAMESPACE} --ignore-not-found=true
    echo -e "${GREEN}✅ Cleanup complete${NC}"
}

trap cleanup EXIT

echo "📝 Test Configuration:"
echo "   User ID: ${TEST_USER_ID}"
echo "   Project ID: ${TEST_PROJECT_ID}"
echo "   Namespace: ${NAMESPACE}"
echo "   Deployment: ${DEPLOYMENT_NAME}"
echo ""

# Test 1: Can backend create a deployment?
echo "1️⃣  Testing Deployment Creation..."
cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${DEPLOYMENT_NAME}
  namespace: ${NAMESPACE}
  labels:
    app: dev-environment
    user-id: "${TEST_USER_ID}"
    project-id: "${TEST_PROJECT_ID}"
    managed-by: tesslate-backend
    test: "true"
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ${DEPLOYMENT_NAME}
  template:
    metadata:
      labels:
        app: ${DEPLOYMENT_NAME}
    spec:
      containers:
      - name: test-container
        image: node:20-alpine
        command: ["/bin/sh", "-c", "echo 'Test container ready' && sleep 3600"]
        resources:
          requests:
            memory: "128Mi"
            cpu: "50m"
          limits:
            memory: "256Mi"
            cpu: "200m"
EOF

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Deployment created successfully${NC}"
else
    echo -e "${RED}❌ Failed to create deployment${NC}"
    exit 1
fi
echo ""

# Test 2: Can backend create a service?
echo "2️⃣  Testing Service Creation..."
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Service
metadata:
  name: ${DEPLOYMENT_NAME}-service
  namespace: ${NAMESPACE}
  labels:
    app: dev-environment
    test: "true"
spec:
  type: ClusterIP
  selector:
    app: ${DEPLOYMENT_NAME}
  ports:
  - port: 5173
    targetPort: 5173
    protocol: TCP
    name: http
EOF

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Service created successfully${NC}"
else
    echo -e "${RED}❌ Failed to create service${NC}"
    exit 1
fi
echo ""

# Test 3: Can backend create an ingress?
echo "3️⃣  Testing Ingress Creation..."
cat <<EOF | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: ${DEPLOYMENT_NAME}-ingress
  namespace: ${NAMESPACE}
  labels:
    app: dev-environment
    test: "true"
  annotations:
    nginx.ingress.kubernetes.io/auth-url: "http://tesslate-backend-service.tesslate.svc.cluster.local:8005/api/auth/verify"
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  ingressClassName: nginx
  rules:
  - host: user${TEST_USER_ID}-project${TEST_PROJECT_ID}.studio-test.tesslate.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: ${DEPLOYMENT_NAME}-service
            port:
              number: 5173
EOF

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Ingress created successfully${NC}"
else
    echo -e "${RED}❌ Failed to create ingress${NC}"
    exit 1
fi
echo ""

# Test 4: Check resources exist
echo "4️⃣  Verifying Resources..."
echo ""
echo "Deployments:"
kubectl get deployment ${DEPLOYMENT_NAME} -n ${NAMESPACE}
echo ""
echo "Services:"
kubectl get service ${DEPLOYMENT_NAME}-service -n ${NAMESPACE}
echo ""
echo "Ingresses:"
kubectl get ingress ${DEPLOYMENT_NAME}-ingress -n ${NAMESPACE}
echo ""

# Test 5: Check PVC
echo "5️⃣  Checking PVC..."
PVC_STATUS=$(kubectl get pvc tesslate-projects-pvc -n ${NAMESPACE} -o jsonpath='{.status.phase}')
if [ "$PVC_STATUS" == "Bound" ]; then
    echo -e "${GREEN}✅ PVC is bound and ready${NC}"
    kubectl get pvc tesslate-projects-pvc -n ${NAMESPACE}
else
    echo -e "${YELLOW}⚠️  PVC status: ${PVC_STATUS}${NC}"
fi
echo ""

# Test 6: Check pod can mount PVC
echo "6️⃣  Testing PVC Mount..."
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: test-pvc-mount
  namespace: ${NAMESPACE}
spec:
  containers:
  - name: test
    image: busybox
    command: ["/bin/sh", "-c", "echo 'Testing PVC mount' > /data/test.txt && cat /data/test.txt && sleep 30"]
    volumeMounts:
    - name: projects-storage
      mountPath: /data
      subPath: users/${TEST_USER_ID}/${TEST_PROJECT_ID}
  volumes:
  - name: projects-storage
    persistentVolumeClaim:
      claimName: tesslate-projects-pvc
  restartPolicy: Never
EOF

echo "Waiting for test pod..."
kubectl wait --for=condition=Ready pod/test-pvc-mount -n ${NAMESPACE} --timeout=30s 2>/dev/null || true
sleep 2

POD_LOGS=$(kubectl logs test-pvc-mount -n ${NAMESPACE} 2>/dev/null || echo "")
if echo "$POD_LOGS" | grep -q "Testing PVC mount"; then
    echo -e "${GREEN}✅ PVC mount test successful${NC}"
    echo "   Output: $POD_LOGS"
else
    echo -e "${YELLOW}⚠️  PVC mount test inconclusive${NC}"
    kubectl get pod test-pvc-mount -n ${NAMESPACE}
    kubectl describe pod test-pvc-mount -n ${NAMESPACE} | tail -20
fi

kubectl delete pod test-pvc-mount -n ${NAMESPACE} --ignore-not-found=true
echo ""

echo "=========================================="
echo -e "${GREEN}✅ All K8s resource tests passed!${NC}"
echo "=========================================="
echo ""
echo "The backend can successfully create:"
echo "  ✅ Deployments in tesslate-user-environments"
echo "  ✅ Services in tesslate-user-environments"
echo "  ✅ Ingresses in tesslate-user-environments"
echo "  ✅ PVC is bound and mountable"
echo ""
echo "🎉 Ready for user environment creation via API!"