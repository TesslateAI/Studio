#!/bin/bash
# =============================================================================
# Kubernetes Context Switcher
# =============================================================================
# Quickly switch kubectl context to a Tesslate environment.
#
# Usage:
#   ./scripts/kctx.sh production         # Switch to production EKS (instant)
#   ./scripts/kctx.sh beta               # Switch to beta EKS (instant)
#   ./scripts/kctx.sh minikube           # Switch to local minikube (instant)
#   ./scripts/kctx.sh production --verify # Switch + verify cluster connectivity
#   ./scripts/kctx.sh                    # Show current context + available environments
# =============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Environment → context mapping
declare -A CONTEXT_MAP=(
    [production]=tesslate-production-eks
    [prod]=tesslate-production-eks
    [beta]=tesslate-beta-eks
    [minikube]=tesslate
    [local]=tesslate
)

# Environment → cluster name (for update-kubeconfig)
declare -A CLUSTER_MAP=(
    [production]=tesslate-production-eks
    [prod]=tesslate-production-eks
    [beta]=tesslate-beta-eks
)

show_status() {
    CURRENT=$(kubectl config current-context 2>/dev/null || echo "none")
    echo -e "${BLUE}Current context:${NC} $CURRENT"
    echo ""
    echo "Available environments:"
    echo "  production (prod)  → tesslate-production-eks"
    echo "  beta               → tesslate-beta-eks"
    echo "  minikube (local)   → tesslate"
    echo ""
    echo "Usage: ./scripts/kctx.sh <environment>"
}

if [ -z "$1" ]; then
    show_status
    exit 0
fi

VERIFY=false
ENV=""
for arg in "$@"; do
    if [ "$arg" = "--verify" ]; then
        VERIFY=true
    else
        ENV="$arg"
    fi
done
CONTEXT="${CONTEXT_MAP[$ENV]}"

if [ -z "$CONTEXT" ]; then
    echo -e "${RED}Unknown environment: $ENV${NC}"
    echo "Valid: production, prod, beta, minikube, local"
    exit 1
fi

# Try switching to the context
if kubectl config use-context "$CONTEXT" >/dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Switched to ${YELLOW}$CONTEXT${NC}"
else
    # Context doesn't exist — try to create it for EKS environments
    CLUSTER="${CLUSTER_MAP[$ENV]}"
    if [ -n "$CLUSTER" ]; then
        echo -e "${YELLOW}Context '$CONTEXT' not found. Fetching kubeconfig for $CLUSTER...${NC}"
        aws eks update-kubeconfig --region us-east-1 --name "$CLUSTER" --alias "$CONTEXT" >/dev/null 2>&1 \
            || { echo -e "${RED}Failed to fetch kubeconfig. Check AWS credentials and cluster name.${NC}"; exit 1; }
        kubectl config use-context "$CONTEXT" >/dev/null 2>&1
        echo -e "${GREEN}✓${NC} Created and switched to ${YELLOW}$CONTEXT${NC}"
    else
        echo -e "${RED}Context '$CONTEXT' not found. Start minikube first: minikube start -p tesslate${NC}"
        exit 1
    fi
fi

# Verify connectivity only when --verify flag is passed
if [ "$VERIFY" = true ]; then
    # First call after context switch is slow (~15-20s for IAM token + TLS)
    # Use background process + wait since macOS lacks `timeout`
    kubectl get ns tesslate >/dev/null 2>&1 &
    KUBE_PID=$!
    WAITED=0
    while kill -0 "$KUBE_PID" 2>/dev/null; do
        if [ "$WAITED" -ge 45 ]; then
            kill "$KUBE_PID" 2>/dev/null
            wait "$KUBE_PID" 2>/dev/null
            echo -e "${YELLOW}⚠ Cluster verification timed out.${NC}"
            exit 0
        fi
        sleep 1
        WAITED=$((WAITED + 1))
    done
    if wait "$KUBE_PID"; then
        echo -e "${GREEN}✓${NC} Cluster reachable"
    else
        echo -e "${YELLOW}⚠ Could not verify cluster connectivity.${NC}"
    fi
fi
